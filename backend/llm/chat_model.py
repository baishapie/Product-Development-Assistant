"""构建 LangChain ChatModel（OpenAI 兼容）。

LangChain ``create_agent`` 需要 ``BaseChatModel``，因此 LLM 访问统一经此工厂；
Provider 差异只体现在 ``base_url`` / ``model`` / ``api_key``。
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from backend.config import Settings


def create_chat_model(settings: Settings) -> BaseChatModel:
    """按 ``Settings`` 构建 OpenAI 兼容 ChatModel。

    ``max_retries=0``：重试交给工作流节点（``AGENT_MAX_RETRIES``）统一控制。
    """
    config = settings.provider_config()
    return ChatOpenAI(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key or "not-set",
        temperature=config.temperature,
        timeout=config.timeout,
        max_retries=0,
    )
