"""LLM 接入层：ChatModel + 可选 Langfuse 追踪（延迟导入，避免拖慢启动）。"""

from __future__ import annotations

from typing import Any

__all__ = ["build_langfuse_callback", "create_chat_model"]


def __getattr__(name: str) -> Any:
    if name == "create_chat_model":
        from backend.llm.chat_model import create_chat_model

        return create_chat_model
    if name == "build_langfuse_callback":
        from backend.llm.tracing import build_langfuse_callback

        return build_langfuse_callback
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
