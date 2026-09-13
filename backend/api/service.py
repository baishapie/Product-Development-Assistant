"""工作流运行管理：后台线程执行 + 轮询状态 + 提交人工确认。

一次运行对应一个唯一 ``thread_id``（即 ``run_id``），与内存 Checkpointer 配合，
使 ``interrupt()`` 暂停后可用 ``Command(resume=...)`` 在同一线程继续。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from backend.config import Settings, get_settings
from backend.workflow.graph import build_graph
from backend.workflow.state import new_state


@dataclass
class Run:
    """一次运行的运行时状态。"""

    run_id: str
    thread_id: str
    idea: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class RunManager:
    """管理多个工作流运行（按 run 加锁，后台线程执行）。"""

    def __init__(self, settings: Settings, graph: CompiledStateGraph | None = None) -> None:
        self._settings = settings
        self._graph = graph or build_graph(settings)
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def start(self, idea: str) -> str:
        """创建并异步启动一次运行，返回 ``run_id``。"""
        run_id = uuid.uuid4().hex
        run = Run(run_id=run_id, thread_id=run_id, idea=idea)
        with self._lock:
            self._runs[run_id] = run
        self._spawn(run, new_state(idea))
        return run_id

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def submit_review(self, run_id: str, payload: dict[str, Any]) -> None:
        """用人工决策恢复一次已暂停的运行。"""
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if self._interrupt(run) is None:
            raise ValueError("run is not awaiting review")
        # 清除旧中断，避免恢复线程写入新状态前轮询读到过期结果
        run.result.pop("__interrupt__", None)
        self._spawn(run, Command(resume=payload))

    def _spawn(self, run: Run, input_value: Any) -> None:
        threading.Thread(target=self._execute, args=(run, input_value), daemon=True).start()

    def _execute(self, run: Run, input_value: Any) -> None:
        config = {"configurable": {"thread_id": run.thread_id}}
        with run.lock:
            try:
                result = self._graph.invoke(input_value, config=config)
                run.result = dict(result)
                run.error = None
            except Exception as exc:
                run.error = str(exc)
                run.result = {**run.result, "status": "failed", "error": str(exc)}

    @staticmethod
    def _interrupt(run: Run) -> dict[str, Any] | None:
        """取出 ``interrupt`` 载荷（无则 None）。"""
        interrupts = run.result.get("__interrupt__")
        if not interrupts:
            return None
        first = interrupts[0]
        value = getattr(first, "value", first)
        return dict(value) if isinstance(value, dict) else {"prompt": str(value)}

    def status(self, run: Run) -> dict[str, Any]:
        """汇总运行状态，供 API 返回。"""
        base: dict[str, Any] = {
            "run_id": run.run_id,
            "current_task": run.result.get("current_task"),
            "completed": run.result.get("completed", []),
            "plan": run.result.get("plan", []),
            "error": run.error or run.result.get("error"),
        }
        if run.error:
            return {**base, "status": "failed", "review": None}

        review = self._interrupt(run)
        if review is not None:
            status = "awaiting_review"
        elif run.result.get("status") == "done":
            status = "done"
        elif run.result.get("status") == "failed":
            status = "failed"
        else:
            status = "running"

        review_view = (
            {
                "stage": review.get("stage"),
                "round": review.get("round"),
                "max_rounds": review.get("max_rounds"),
                "artifact": review.get("artifact") or {},
            }
            if review is not None
            else None
        )
        return {**base, "status": status, "review": review_view}

    def document(self, run: Run) -> str | None:
        """返回生成的 Markdown（未完成则 None）。"""
        document = run.result.get("product_document")
        return document or None


_manager: RunManager | None = None


def get_manager() -> RunManager:
    """获取全局运行管理器（首次调用时构建图）。"""
    global _manager
    if _manager is None:
        settings = get_settings()
        settings.export_langsmith_env()
        _manager = RunManager(settings)
    return _manager


def set_manager(manager: RunManager | None) -> None:
    """替换全局运行管理器（测试用）。"""
    global _manager
    _manager = manager
