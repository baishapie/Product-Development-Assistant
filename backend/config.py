"""应用配置：从环境变量 / ``.env`` 加载。

所有密钥与 Provider 设置都在这里注入，业务代码不硬编码；``get_settings()``
是唯一入口。LLM 接入为 LangChain ChatModel（OpenAI 兼容），Provider 预设决定
默认端点与模型，显式环境变量可覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["openai", "deepseek", "qwen"]

# 各 Provider 的默认 OpenAI 兼容端点 / 模型；显式环境变量可覆盖。
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
}


@dataclass(frozen=True)
class LLMConfig:
    """已解析、与 Provider 无关的 ChatModel 配置。"""

    provider: str
    base_url: str
    api_key: str
    model: str
    timeout: int
    temperature: float


class Settings(BaseSettings):
    """强类型应用配置；环境变量大小写不敏感。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM ---
    llm_provider: ProviderName = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout: int = 60
    llm_temperature: float = 0.3
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    qwen_api_key: str = ""

    # --- Workflow ---
    agent_max_retries: int = 1
    max_review_rounds: int = 3
    max_routing_steps: int = 12
    auto_approve: bool = False
    output_dir: Path = Path("./output")

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False

    # --- Langfuse tracing (optional) ---
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"

    # --- RAG (Phase 2) ---
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "bge-m3"
    chroma_persist_dir: Path = Path("./data/chroma")

    def _resolve_api_key(self) -> str:
        """优先 ``LLM_API_KEY``，否则按 Provider 取对应 Key。"""
        if self.llm_api_key:
            return self.llm_api_key
        return {
            "openai": self.openai_api_key,
            "deepseek": self.deepseek_api_key,
            "qwen": self.qwen_api_key,
        }.get(self.llm_provider, "")

    def provider_config(self) -> LLMConfig:
        """解析 Provider 预设，并由显式环境变量覆盖。"""
        preset = PROVIDER_PRESETS[self.llm_provider]
        return LLMConfig(
            provider=self.llm_provider,
            base_url=self.llm_base_url or preset["base_url"],
            api_key=self._resolve_api_key(),
            model=self.llm_model or preset["model"],
            timeout=self.llm_timeout,
            temperature=self.llm_temperature,
        )


@lru_cache
def get_settings() -> Settings:
    """返回缓存的 ``Settings`` 单例。"""
    return Settings()
