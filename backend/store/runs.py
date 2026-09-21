"""运行元数据存储：内存实现与 PostgreSQL 实现。

设计：``storage_backend=memory`` 时使用内存表（默认，离线可用）；
``storage_backend=postgres`` 时元数据入 PG，检查点由 ``PostgresSaver`` 管理。
PG 不可用时自动降级为内存并记录错误，保证服务仍可启动。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.config import Settings

logger = logging.getLogger(__name__)

# 允许写入 runs 表的列
_COLUMNS = {"status", "current_task", "plan", "completed", "error", "output_path", "review"}
# 需按 JSONB 写入的列
_JSON_COLUMNS = {"plan", "completed", "review"}

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    idea          TEXT NOT NULL,
    status        TEXT NOT NULL,
    current_task  TEXT,
    plan          JSONB NOT NULL DEFAULT '[]'::jsonb,
    completed     JSONB NOT NULL DEFAULT '[]'::jsonb,
    error         TEXT,
    output_path   TEXT,
    review        JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_runs_status  ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Storage:
    """存储句柄：backend + 元数据仓库 + 检查点 + 清理函数。"""

    backend: str
    store: Any
    checkpointer: Any
    closer: Callable[[], None] | None = None


class MemoryRunStore:
    """进程内存储（默认 / 降级），接口与 ``PostgresRunStore`` 一致。"""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def init_schema(self) -> None:  # noqa: D401 - 接口占位
        """内存实现无需建表。"""

    def create(self, run_id: str, idea: str) -> None:
        with self._lock:
            self._rows[run_id] = {
                "run_id": run_id,
                "thread_id": run_id,
                "idea": idea,
                "status": "running",
                "current_task": None,
                "plan": [],
                "completed": [],
                "error": None,
                "output_path": None,
                "review": None,
                "created_at": _now(),
                "updated_at": _now(),
            }

    def update(self, run_id: str, **fields: Any) -> None:
        with self._lock:
            row = self._rows.get(run_id)
            if row is None:
                return
            for key, value in fields.items():
                if key in _COLUMNS:
                    row[key] = value
            row["updated_at"] = _now()

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(run_id)
            return dict(row) if row else None

    def list(
        self, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> tuple[int, list[dict[str, Any]]]:
        with self._lock:
            rows = [dict(r) for r in self._rows.values()]
        if status:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return len(rows), rows[offset : offset + limit]

    def close(self) -> None:  # noqa: D401 - 接口占位
        """内存实现无需释放。"""


class PostgresRunStore:
    """PostgreSQL 运行元数据仓库（psycopg 连接池）。"""

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 5) -> None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )

    def init_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(_DDL)
        logger.info("postgres: runs schema ensured")

    def create(self, run_id: str, idea: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, thread_id, idea, status, plan, completed) "
                "VALUES (%s, %s, %s, 'running', '[]'::jsonb, '[]'::jsonb)",
                (run_id, run_id, idea),
            )

    def update(self, run_id: str, **fields: Any) -> None:
        from psycopg.types.json import Jsonb

        data = {k: v for k, v in fields.items() if k in _COLUMNS}
        if not data:
            return
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in data.items():
            assignments.append(f"{key} = %s")
            values.append(Jsonb(value) if key in _JSON_COLUMNS and value is not None else value)
        values.append(run_id)
        sql = f"UPDATE runs SET {', '.join(assignments)}, updated_at = now() WHERE run_id = %s"
        with self._pool.connection() as conn:
            conn.execute(sql, values)

    @staticmethod
    def _normalize(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return row
        for key in ("created_at", "updated_at"):
            value = row.get(key)
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
        return row

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,)).fetchone()
        return self._normalize(row)

    def list(
        self, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> tuple[int, list[dict[str, Any]]]:
        where = "WHERE status = %s" if status else ""
        filter_values: list[Any] = [status] if status else []
        with self._pool.connection() as conn:
            total = conn.execute(
                f"SELECT count(*) AS n FROM runs {where}", filter_values
            ).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                [*filter_values, limit, offset],
            ).fetchall()
        return int(total), [self._normalize(dict(row)) for row in rows]

    def close(self) -> None:
        self._pool.close()


def build_storage(settings: Settings) -> Storage:
    """按配置构建存储；PG 不可用时降级为内存。"""
    if settings.storage_backend != "postgres":
        from langgraph.checkpoint.memory import MemorySaver

        logger.info("storage: backend=memory (no persistence)")
        return Storage("memory", MemoryRunStore(), MemorySaver(), None)

    tunnel = None
    try:
        from backend.infra.postgres import build_dsn, create_checkpointer
        from backend.infra.ssh_tunnel import SSHTunnel

        local = None
        if settings.ssh_enabled:
            tunnel = SSHTunnel(settings)
            local = tunnel.start()
        logger.info(
            "postgres: connecting",
            extra={
                "host": settings.pg_host,
                "port": settings.pg_port,
                "db": settings.pg_db,
                "user": settings.pg_user,
                "ssh": settings.ssh_enabled,
            },
        )
        dsn = build_dsn(settings, local)
        store = PostgresRunStore(dsn)
        store.init_schema()
        checkpointer, cp_closer = create_checkpointer(dsn)

        def closer() -> None:
            cp_closer.__exit__(None, None, None)
            store.close()
            if tunnel is not None:
                tunnel.stop()

        logger.info(
            "storage: backend=postgres ready",
            extra={"db": settings.pg_db, "ssh": settings.ssh_enabled},
        )
        return Storage("postgres", store, checkpointer, closer)
    except Exception as exc:  # noqa: BLE001 - 降级保证服务可启动
        logger.error("postgres storage unavailable, falling back to memory: %s", exc)
        if tunnel is not None:
            tunnel.stop()
        from langgraph.checkpoint.memory import MemorySaver

        return Storage("memory", MemoryRunStore(), MemorySaver(), None)
