"""可选的可观测集成：Langfuse（基于 OpenTelemetry）。

仅在明确启用且提供密钥时构造 Langfuse 的 LangChain ``CallbackHandler``；
否则返回 ``None``，保证未配置 / 离线测试时不产生任何副作用。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.config import Settings

logger = logging.getLogger(__name__)


def build_langfuse_callback(settings: Settings) -> Any | None:
    """启用且具备密钥时返回 Langfuse CallbackHandler，否则 ``None``。"""
    if not settings.langfuse_enabled:
        return None
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning("LANGFUSE_ENABLED=true but keys are missing; tracing disabled")
        return None

    # Langfuse SDK 从环境变量读取配置，需在构造前写入
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_BASE_URL"] = settings.langfuse_base_url

    try:
        from langfuse.langchain import CallbackHandler
    except ImportError as exc:  # pragma: no cover - 未安装 langfuse
        logger.warning("langfuse not installed; tracing disabled: %s", exc)
        return None
    try:
        # 不传 public_key：由 SDK 依据上面的环境变量自动初始化全局 client
        return CallbackHandler()
    except Exception as exc:  # pragma: no cover - 初始化失败
        logger.warning("failed to init Langfuse callback: %s", exc)
        return None
