"""Shared test doubles: no network, no API keys."""

from __future__ import annotations

from typing import Any

from backend.workflow.human_review import ReviewDecision


class FakeLLMClient:
    """Scripted ``LLMClient``.

    ``responses`` is either an ordered list of raw strings (each ``chat`` call
    consumes the next one) or a mapping from a substring of the system message
    to the response for that agent.
    """

    def __init__(self, responses: list[str] | dict[str, str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        if isinstance(responses, dict):
            self._by_marker: dict[str, str] | None = responses
            self._queue: list[str] | None = None
        else:
            self._by_marker = None
            self._queue = list(responses or [])

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        if self._by_marker is not None:
            system = messages[0]["content"] if messages else ""
            for marker, response in self._by_marker.items():
                if marker in system:
                    return response
            raise AssertionError(f"FakeLLMClient has no response for: {system[:80]!r}")

        if not self._queue:
            raise AssertionError("FakeLLMClient response queue is empty")
        return self._queue.pop(0)


class FakeReviewer:
    """按 stage 返回预设决策序列的自动评审。"""

    def __init__(self, decisions: dict[str, list[ReviewDecision | dict[str, Any]]]) -> None:
        self._decisions = {stage: list(items) for stage, items in decisions.items()}
        self.calls: list[tuple[str, int, dict[str, Any]]] = []

    def decide(self, stage: str, round: int, artifact: dict[str, Any]) -> ReviewDecision:
        self.calls.append((stage, round, artifact))
        queue = self._decisions.get(stage)
        if not queue:
            raise AssertionError(f"FakeReviewer has no decision left for stage {stage!r}")
        item = queue.pop(0)
        return item if isinstance(item, ReviewDecision) else ReviewDecision.model_validate(item)
