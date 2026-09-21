"""PostgreSQL 连接：DSN 构建与 LangGraph 检查点（延迟导入）。"""

from __future__ import annotations

import logging
from typing import Any

from backend.config import Settings

logger = logging.getLogger(__name__)


def build_dsn(settings: Settings, local: tuple[str, int] | None = None) -> str:
    """生成连接串；``local`` 为 SSH 隧道本地端点（启用时）。"""
    host, port = local if local else (settings.pg_host, settings.pg_port)
    return (
        f"postgresql://{settings.pg_user}:{settings.pg_password}"
        f"@{host}:{port}/{settings.pg_db}?sslmode={settings.pg_sslmode}"
    )


def create_checkpointer(dsn: str) -> tuple[Any, Any]:
    """创建并初始化 ``PostgresSaver``，返回 ``(saver, closer)``。

    ``closer`` 用于应用退出时释放底层连接/上下文。
    """
    from langgraph.checkpoint.postgres import PostgresSaver

    logger.info("postgres: initializing checkpoint schema")
    cm = PostgresSaver.from_conn_string(dsn)
    saver = cm.__enter__()
    saver.setup()
    logger.info("postgres: checkpoint schema ready")
    return saver, cm
