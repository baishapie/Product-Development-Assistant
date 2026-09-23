"""FastAPI 应用：工作流 API + 单文件前端托管。"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from backend.api.models import (
    ReviewRequest,
    RunCreated,
    RunList,
    RunRequest,
    RunStatus,
    RunSummary,
)
from backend.api.service import get_manager

logger = logging.getLogger(__name__)

# backend/api/app.py -> 仓库根目录
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时尝试恢复中断任务，退出时释放存储/隧道。"""
    try:
        get_manager().recover()
    except Exception:  # noqa: BLE001 - 恢复失败不阻塞启动
        logger.exception("startup recover failed")
    yield
    try:
        get_manager().close()
    except Exception:  # noqa: BLE001
        logger.exception("shutdown close failed")


app = FastAPI(title="ProductMind AI", version="0.1.0", lifespan=lifespan)

# 运行状态查询接口（前端高频轮询）不记请求日志
_STATUS_POLL = re.compile(r"^/api/runs/[^/]+/?$")
_BODY_LIMIT = 2000


def _short(text: str, limit: int = _BODY_LIMIT) -> str:
    return text if len(text) <= limit else f"{text[:limit]}...(共 {len(text)} 字符)"


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每次请求的参数与响应码；跳过运行状态查询（轮询）接口。"""
    path = request.url.path
    if request.method == "GET" and _STATUS_POLL.match(path):
        return await call_next(request)

    body_text = ""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        raw = await request.body()
        if raw:
            body_text = _short(raw.decode("utf-8", "replace"))

    response = await call_next(request)

    logger.info(
        "http request",
        extra={
            "method": request.method,
            "path": path,
            "query": request.url.query,
            "body": body_text,
            "status": response.status_code,
        },
    )
    return response


@app.post("/api/runs", response_model=RunCreated, status_code=201)
def create_run(request: RunRequest) -> RunCreated:
    """创建并异步启动一次工作流运行。"""
    idea = request.idea.strip()
    logger.info("POST /api/runs", extra={"idea_len": len(idea)})
    run_id = get_manager().start(idea)
    logger.info("run created", extra={"run_id": run_id})
    return RunCreated(run_id=run_id)


@app.get("/api/runs", response_model=RunList)
def list_runs(status: str | None = None, limit: int = 20, offset: int = 0) -> RunList:
    """列出历史任务（支持按状态筛选与分页）。"""
    total, rows = get_manager().list_runs(status=status, limit=limit, offset=offset)
    return RunList(total=total, items=[RunSummary.model_validate(row) for row in rows])


@app.get("/api/runs/{run_id}", response_model=RunStatus)
def get_run(run_id: str) -> RunStatus:
    """查询运行状态（前端轮询）。"""
    manager = get_manager()
    run = manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return RunStatus.model_validate(manager.status(run))


@app.post("/api/runs/{run_id}/review", status_code=202)
def submit_review(run_id: str, request: ReviewRequest) -> dict[str, str]:
    """提交人工确认（approved / revise）以恢复运行。"""
    manager = get_manager()
    if manager.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    logger.info("POST review", extra={"run_id": run_id, "decision": request.decision})
    try:
        manager.submit_review(run_id, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "accepted"}


@app.post("/api/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: str) -> dict[str, str]:
    """从检查点恢复一次异常中断的运行。"""
    manager = get_manager()
    if manager.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    logger.info("POST resume", extra={"run_id": run_id})
    try:
        manager.resume(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "accepted"}


@app.get("/api/runs/{run_id}/document")
def get_document(run_id: str) -> PlainTextResponse:
    """返回生成的 Markdown 文档。"""
    manager = get_manager()
    run = manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    document = manager.document(run)
    if not document:
        raise HTTPException(status_code=409, detail="document not ready")
    return PlainTextResponse(document, media_type="text/markdown; charset=utf-8")


@app.get("/")
def index() -> FileResponse:
    """托管单文件前端（控制台）。"""
    index_path = _FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="frontend not found")
    return FileResponse(index_path)


@app.get("/tasks")
def tasks_page() -> FileResponse:
    """托管任务管理页面（查看/恢复/重跑）。"""
    tasks_path = _FRONTEND_DIR / "tasks.html"
    if not tasks_path.exists():
        raise HTTPException(status_code=404, detail="tasks page not found")
    return FileResponse(tasks_path)
