"""Human review gates used between selected workflow stages."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from backend.agents.factory import get_mapping
from backend.config import Settings
from backend.workflow.state import AgentState

logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    """Raised when a review response cannot be interpreted safely."""


class ReviewDecision(BaseModel):
    decision: Literal["approved", "revise"]
    feedback: str = ""


class Reviewer(Protocol):
    def decide(self, stage: str, round: int, artifact: dict[str, Any]) -> ReviewDecision: ...


def _coerce_decision(value: Any) -> ReviewDecision:
    if isinstance(value, ReviewDecision):
        return value
    if isinstance(value, Mapping):
        try:
            return ReviewDecision.model_validate(value)
        except ValidationError as exc:
            raise WorkflowError(f"invalid review decision: {exc}") from exc
    raise WorkflowError(f"unsupported review decision type: {type(value)!r}")


def _obtain_decision(
    stage: str,
    round_no: int,
    artifact: Mapping[str, Any],
    settings: Settings,
    reviewer: Reviewer | None,
) -> ReviewDecision:
    if reviewer is not None:
        return _coerce_decision(reviewer.decide(stage, round_no, dict(artifact)))
    if settings.auto_approve:
        return ReviewDecision(decision="approved")

    from langgraph.types import interrupt

    payload = {
        "stage": stage,
        "artifact": dict(artifact),
        "round": round_no,
        "max_rounds": settings.max_review_rounds,
        "prompt": "Approve this stage or request a revision with actionable feedback.",
    }
    return _coerce_decision(interrupt(payload))


def make_human_review(
    stage: str,
    settings: Settings,
    reviewer: Reviewer | None = None,
) -> Callable[[AgentState], dict[str, Any]]:
    def node(state: AgentState) -> dict[str, Any]:
        rounds = int((state.get("review_rounds") or {}).get(stage, 0))
        artifact = get_mapping(get_mapping(state, "results"), stage)
        decision = _obtain_decision(stage, rounds + 1, artifact, settings, reviewer)

        if decision.decision == "revise" and decision.feedback.strip():
            return {
                "current_task": f"review_{stage}",
                "review_stage": stage,
                "review_decision": "revise",
                "review_feedback": decision.feedback.strip(),
                "review_rounds": {stage: rounds + 1},
                "gate_status": {stage: "revise"},
            }
        if decision.decision == "revise":
            logger.warning("revise without feedback treated as approved", extra={"stage": stage})
        return {
            "current_task": f"review_{stage}",
            "review_stage": stage,
            "review_decision": "approved",
            "review_feedback": None,
            "gate_status": {stage: "approved"},
        }

    return node
