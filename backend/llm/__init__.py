"""LLM provider abstraction: client protocol + factory (OpenAI-compatible)."""

from backend.llm.base import LLMClient, LLMError
from backend.llm.factory import create_llm
from backend.llm.openai_client import OpenAIClient

__all__ = ["LLMClient", "LLMError", "OpenAIClient", "create_llm"]
