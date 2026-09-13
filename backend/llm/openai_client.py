"""OpenAI-compatible chat client.

OpenAI / DeepSeek / Qwen (DashScope compatible mode) / third-party relays all
speak the OpenAI protocol, so a single implementation serves them all; only the
``base_url`` / ``api_key`` / ``model`` differ (resolved in ``backend.config``).
"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from backend.config import LLMConfig
from backend.llm.base import LLMClient, LLMError

logger = logging.getLogger(__name__)


class OpenAIClient(LLMClient):
    """Chat client over any OpenAI-compatible endpoint."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        tracing: bool = False,
        client: Any | None = None,
    ) -> None:
        self._config = config
        self._tracing = tracing
        self._client: Any | None = client

    @property
    def config(self) -> LLMConfig:
        """Resolved configuration this client was built from."""
        return self._config

    def _ensure_client(self) -> Any:
        """Lazily build the underlying client (and wrap it for tracing)."""
        if self._client is None:
            client: Any = OpenAI(
                api_key=self._config.api_key or "not-set",
                base_url=self._config.base_url,
                timeout=self._config.timeout,
                max_retries=0,
            )
            if self._tracing:
                client = self._wrap_for_tracing(client)
            self._client = client
        return self._client

    @staticmethod
    def _wrap_for_tracing(client: Any) -> Any:
        """Wrap a client so LLM calls appear in LangSmith traces."""
        try:
            from langsmith.wrappers import wrap_openai

            return wrap_openai(client)
        except Exception:  # pragma: no cover - tracing is optional
            logger.warning("LangSmith tracing requested but wrap_openai unavailable")
            return client

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature if temperature is None else temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            response = self._ensure_client().chat.completions.create(**kwargs)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize all provider errors
            raise LLMError(
                "LLM request failed "
                f"(model={self._config.model}, base_url={self._config.base_url}): {exc}"
            ) from exc

        try:
            return response.choices[0].message.content or ""
        except (AttributeError, IndexError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {exc}") from exc
