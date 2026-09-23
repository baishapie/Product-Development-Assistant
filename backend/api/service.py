"""工作流运行管理：后台线程执行 + 持久化 + 恢复 + 轮询 + 人工确认。

- ``run_id == thread_id``，与 Checkpointer 对齐，使 ``interrupt()`` 暂停后可恢复。
- ``storage_backend=postgres`` 时元数据入 PG、检查点由 ``PostgresSaver`` 持久化；
  不可用时自动降级为内存（``MemorySaver`` + 内存表）。
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.config import Settings, get_settings
from backend.llm.tracing import build_langfuse_callback
from backend.store.runs import Storage, build_storage
from backend.workflow.state import new_state

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

# 待确认视图字段
_REVIEW_FIELDS = ("stage", "round", "max_rounds", "artifact")


@dataclass
class Run:
    """一次运行的运行时状态。"""

    run_id: str
    thread_id: str
    idea: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    record: dict[str, Any] | None = None  # 从存储加载的记录（无实时 result 时用）
    lock: threading.Lock = field(default_factory=threading.Lock)


class RunManager:
    """管理多个工作流运行（按 run 加锁，后台线程执行，可选持久化）。"""

    def __init__(self, settings: Settings, graph: CompiledStateGraph | None = None) -> None:
        self._settings = settings
        self._graph = graph
        self._graph_lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self._storage: Storage | None = None
        self._storage_lock = threading.Lock()
        callback = build_langfuse_callback(settings)
        self._callbacks: list[Any] = [callback] if callback is not None else []

    # ------------------------------------------------------------------ storage
    def _ensure_storage(self) -> Storage:
        if self._storage is None:
            with self._storage_lock:
                if self._storage is None:
                    self._storage = build_storage(self._settings)
        return self._storage

    def _get_graph(self) -> CompiledStateGraph:
        if self._graph is None:
            with self._graph_lock:
                if self._graph is None:
                    from backend.workflow.graph import build_graph

                    storage = self._ensure_storage()
                    self._graph = build_graph(self._settings, checkpointer=storage.checkpointer)
        return self._graph

    # ------------------------------------------------------------------ lifecycle
    def start(self, idea: str) -> str:
        """创建并异步启动一次运行，返回 ``run_id``。"""
        run_id = uuid.uuid4().hex
        run = Run(run_id=run_id, thread_id=run_id, idea=idea)
        with self._lock:
            self._runs[run_id] = run
        self._ensure_storage().store.create(run_id, idea)
        self._spawn(run, new_state(idea, run_id=run_id))
        return run_id

    def get(self, run_id: str) -> Run | None:
        """取实时 Run；不在内存则从存储加载（跨重启可用）。"""
        with self._lock:
            run = self._runs.get(run_id)
        if run is not None:
            return run
        row = self._ensure_storage().store.get(run_id)
        if row is None:
            return None
        run = Run(
            run_id=row["run_id"],
            thread_id=row["thread_id"],
            idea=row["idea"],
            record=row,
        )
        with self._lock:
            self._runs[run_id] = run
        return run

    def list_runs(
        self, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> tuple[int, list[dict[str, Any]]]:
        return self._ensure_storage().store.list(status=status, limit=limit, offset=offset)

    def submit_review(self, run_id: str, payload: dict[str, Any]) -> None:
        """用人工决策恢复一次已暂停的运行。"""
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if self._pending_review(run) is None:
            raise ValueError("run is not awaiting review")
        from langgraph.types import Command

        run.result.pop("__interrupt__", None)
        self._ensure_storage()
        self._spawn(run, Command(resume=payload))

    def resume(self, run_id: str) -> None:
        """从检查点继续一次异常中断的运行（仅 PostgreSQL 后端）。"""
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        storage = self._ensure_storage()
        if storage.backend != "postgres":
            raise ValueError("storage backend does not support resume")
        snapshot = self._get_graph().get_state({"configurable": {"thread_id": run.thread_id}})
        if not getattr(snapshot, "next", None):
            raise ValueError("run has no pending step to resume")
        self._spawn(run, None)

    def recover(self) -> None:
        """启动扫描：恢复被异常中断的 ``running`` 任务。"""
        storage = self._ensure_storage()
        if storage.backend != "postgres" or not self._settings.recover_on_startup:
            return
        _, rows = storage.store.list(status="running", limit=1000, offset=0)
        for row in rows:
            run = Run(row["run_id"], row["thread_id"], row["idea"], record=row)
            with self._lock:
                self._runs[run.run_id] = run
            try:
                snapshot = self._get_graph().get_state(
                    {"configurable": {"thread_id": run.thread_id}}
                )
            except Exception:  # noqa: BLE001 - 单个失败不影响其它
                logger.exception("recover failed", extra={"run_id": run.run_id})
                continue
            if getattr(snapshot, "next", None):
                logger.info("resuming interrupted run", extra={"run_id": run.run_id})
                self._spawn(run, None)
            else:
                self._sync_from_snapshot(run, snapshot)

    def close(self) -> None:
        if self._storage is not None and self._storage.closer is not None:
            self._storage.closer()
            self._storage = None

    # ------------------------------------------------------------------ execution
    def _spawn(self, run: Run, input_value: Any) -> None:
        threading.Thread(target=self._execute, args=(run, input_value), daemon=True).start()

    def _execute(self, run: Run, input_value: Any) -> None:
        graph = self._get_graph()
        with run.lock:
            try:
                result = graph.invoke(input_value, config=self._invoke_config(run))
                run.result = dict(result)
                run.error = None
            except Exception as exc:  # noqa: BLE001 - 运行失败写入状态供轮询
                run.error = str(exc)
                run.result = {**run.result, "status": "failed", "error": str(exc)}
            self._persist(run)

    def _invoke_config(self, run: Run) -> dict[str, Any]:
        settings = self._settings
        recursion_limit = 4 * settings.max_routing_steps + 4 * settings.max_review_rounds + 8
        config: dict[str, Any] = {
            "configurable": {"thread_id": run.thread_id},
            "recursion_limit": recursion_limit,
        }
        if self._callbacks:
            config["callbacks"] = self._callbacks
        return config

    # ------------------------------------------------------------------ status
    @staticmethod
    def _interrupt(run: Run) -> dict[str, Any] | None:
        interrupts = run.result.get("__interrupt__")
        if not interrupts:
            return None
        first = interrupts[0]
        value = getattr(first, "value", first)
        return dict(value) if isinstance(value, dict) else {"prompt": str(value)}

    def _pending_review(self, run: Run) -> dict[str, Any] | None:
        review = self._interrupt(run)
        if review is not None:
            return review
        if run.record and run.record.get("review"):
            return dict(run.record["review"])
        return None

    def status(self, run: Run) -> dict[str, Any]:
        """汇总运行状态，供 API 返回。"""
        if not run.result and run.record:
            return self._status_from_record(run.record)

        base: dict[str, Any] = {
            "run_id": run.run_id,
            "idea": run.idea,
            "current_task": run.result.get("current_task"),
            "completed": run.result.get("completed", []),
            "plan": run.result.get("plan", []),
            "error": run.error or run.result.get("error"),
        }
        if run.error:
            return {**base, "status": "failed", "review": None}

        review = self._pending_review(run)
        if review is not None:
            status = "awaiting_review"
        elif run.result.get("status") == "done":
            status = "done"
        elif run.result.get("status") == "failed":
            status = "failed"
        else:
            status = "running"
        review_view = (
            {key: review.get(key) for key in _REVIEW_FIELDS} if review is not None else None
        )
        return {**base, "status": status, "review": review_view}

    @staticmethod
    def _status_from_record(record: dict[str, Any]) -> dict[str, Any]:
        review = record.get("review")
        review_view = {key: review.get(key) for key in _REVIEW_FIELDS} if review else None
        return {
            "run_id": record["run_id"],
            "idea": record.get("idea"),
            "status": record["status"],
            "current_task": record.get("current_task"),
            "completed": record.get("completed") or [],
            "plan": record.get("plan") or [],
            "error": record.get("error"),
            "review": review_view,
        }

    def document(self, run: Run) -> str | None:
        """返回生成的 Markdown（未完成则 None）。"""
        if run.result:
            return run.result.get("product_document") or None
        path = (run.record or {}).get("output_path")
        if path:
            from pathlib import Path

            file = Path(path)
            if file.exists():
                return file.read_text(encoding="utf-8")
        return None

    # ------------------------------------------------------------------ persistence
    def _persist(self, run: Run) -> None:
        fields: dict[str, Any] = {
            "current_task": run.result.get("current_task"),
            "plan": run.result.get("plan") or [],
            "completed": run.result.get("completed") or [],
        }
        if run.error:
            fields.update(status="failed", error=run.error)
        else:
            review = self._interrupt(run)
            if review is not None:
                fields.update(
                    status="awaiting_review",
                    review={key: review.get(key) for key in _REVIEW_FIELDS},
                )
            elif run.result.get("status") == "done":
                fields.update(status="done", output_path=run.result.get("output_path"), error=None)
            elif run.result.get("status") == "failed":
                fields.update(status="failed", error=run.result.get("error"))
            else:
                fields.update(status="running")
        self._ensure_storage().store.update(run.run_id, **fields)

    def _sync_from_snapshot(self, run: Run, snapshot: Any) -> None:
        values = dict(getattr(snapshot, "values", {}) or {})
        review = None
        for task in getattr(snapshot, "tasks", ()) or ():
            for item in getattr(task, "interrupts", ()) or ():
                value = getattr(item, "value", None)
                if isinstance(value, dict):
                    review = {key: value.get(key) for key in _REVIEW_FIELDS}
                    break
        status = values.get("status", "running")
        if review is not None:
            status = "awaiting_review"
        self._ensure_storage().store.update(
            run.run_id,
            status=status,
            current_task=values.get("current_task"),
            plan=values.get("plan") or [],
            completed=values.get("completed") or [],
            output_path=values.get("output_path"),
            error=values.get("error"),
            review=review,
        )


_manager: RunManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> RunManager:
    """获取全局运行管理器（首次调用时创建，延迟建存储/图）。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = RunManager(get_settings())
    return _manager


def set_manager(manager: RunManager | None) -> None:
    """替换全局运行管理器（测试用）。"""
    global _manager
    _manager = manager
