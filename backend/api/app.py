"""FastAPI 应用：工作流 API + 单文件前端托管。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from backend.api.models import ReviewRequest, RunCreated, RunRequest, RunStatus
from backend.api.service import get_manager

# backend/api/app.py -> 仓库根目录
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="ProductMind AI", version="0.1.0")


@app.post("/api/runs", response_model=RunCreated, status_code=201)
def create_run(request: RunRequest) -> RunCreated:
    """创建并异步启动一次工作流运行。"""
    run_id = get_manager().start(request.idea.strip())
    return RunCreated(run_id=run_id)


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
    try:
        manager.submit_review(run_id, request.model_dump())
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
    """托管单文件前端。"""
    index_path = _FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="frontend not found")
    return FileResponse(index_path)
