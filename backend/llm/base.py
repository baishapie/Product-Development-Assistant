"""LLM client protocol and error type.

Agents depend only on ``LLMClient``; concrete providers live behind it.
"""

from __future__ import annotations

from typing import Protocol


class LLMError(Exception):
    """Raised when an LLM request fails (transport, timeout, auth, shape)."""


class LLMClient(Protocol):
    """Provider-agnostic chat interface used by all agents."""

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        """Return the assistant text for ``messages``."""
        ...
