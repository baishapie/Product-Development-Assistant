"""Factory that builds the configured LLM client."""

from __future__ import annotations

from backend.config import Settings
from backend.llm.base import LLMClient
from backend.llm.openai_client import OpenAIClient


def create_llm(settings: Settings) -> LLMClient:
    """Build an LLM client from settings (provider preset + explicit overrides)."""
    return OpenAIClient(settings.provider_config(), tracing=settings.langsmith_tracing)
