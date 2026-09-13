"""Application configuration loaded from environment / ``.env``.

All secrets and provider settings are injected here; nothing is hardcoded in
business code. ``get_settings()`` is the single entry point.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["openai", "deepseek", "qwen"]

# Default OpenAI-compatible endpoints / models per provider.
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
    """Resolved, provider-agnostic LLM client settings."""

    provider: str
    base_url: str
    api_key: str
    model: str
    timeout: int
    temperature: float


class Settings(BaseSettings):
    """Typed application settings. Environment variables are case-insensitive."""

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
    auto_approve: bool = False
    output_dir: Path = Path("./output")

    # --- LangSmith monitoring (optional) ---
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "productmind-ai"

    # --- RAG (Phase 2) ---
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "bge-m3"
    chroma_persist_dir: Path = Path("./data/chroma")

    def _resolve_api_key(self) -> str:
        if self.llm_api_key:
            return self.llm_api_key
        return {
            "openai": self.openai_api_key,
            "deepseek": self.deepseek_api_key,
            "qwen": self.qwen_api_key,
        }.get(self.llm_provider, "")

    def provider_config(self) -> LLMConfig:
        """Resolve provider preset, overridden by explicit environment values."""
        preset = PROVIDER_PRESETS[self.llm_provider]
        return LLMConfig(
            provider=self.llm_provider,
            base_url=self.llm_base_url or preset["base_url"],
            api_key=self._resolve_api_key(),
            model=self.llm_model or preset["model"],
            timeout=self.llm_timeout,
            temperature=self.llm_temperature,
        )

    def export_langsmith_env(self) -> None:
        """Push LangSmith settings into ``os.environ`` so tracing attaches.

        No-op when tracing is disabled, keeping offline tests unaffected.
        """
        if not self.langsmith_tracing:
            return
        os.environ["LANGSMITH_TRACING"] = "true"
        if self.langsmith_api_key:
            os.environ["LANGSMITH_API_KEY"] = self.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = self.langsmith_project


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` singleton."""
    return Settings()
