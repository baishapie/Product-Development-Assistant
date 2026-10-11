"""State contract shared by the deterministic LangGraph workflow."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge partial keyed updates without clobbering unrelated entries."""
    return {**left, **right}


def merge_stage_maps(
    left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Merge stage metadata one stage at a time."""
    merged = {stage_id: dict(value) for stage_id, value in left.items()}
    for stage_id, patch in right.items():
        merged[stage_id] = {**merged.get(stage_id, {}), **patch}
    return merged


def merge_last(_left: Any, right: Any) -> Any:
    """Use the latest update for a single-owner state channel."""
    return right


class AgentState(TypedDict):
    """Complete runtime state; nodes return only partial updates."""

    run_id: str
    idea: str
    plan: list[str]
    next_action: str | None
    iteration_count: int
    completed: Annotated[list[str], merge_last]
    current_task: Annotated[str | None, merge_last]
    results: Annotated[dict[str, dict[str, Any]], merge_dict]
    product_document: str
    output_path: str
    status: Annotated[str, merge_last]
    error: Annotated[str | None, merge_last]
    retries: Annotated[dict[str, int], merge_dict]
    review_stage: str | None
    review_decision: Annotated[str | None, merge_last]
    review_feedback: Annotated[str | None, merge_last]
    review_issue_lists: Annotated[dict[str, list[dict[str, Any]]], merge_dict]
    review_issues: Annotated[list[dict[str, Any]], merge_last]
    review_issue_ledger: Annotated[dict[str, dict[str, Any]], merge_dict]
    review_rounds: Annotated[dict[str, int], merge_dict]
    gate_status: Annotated[dict[str, str], merge_dict]
    messages: Annotated[list[dict[str, str]], operator.add]
    stages: Annotated[dict[str, dict[str, Any]], merge_stage_maps]
    revision_queue: Annotated[list[str], merge_last]
    review_status: Annotated[str, merge_last]
    review_result: Annotated[dict[str, Any], merge_last]
    review_approved_snapshot: Annotated[dict[str, int] | None, merge_last]
    document_status: Annotated[str, merge_last]
    document_snapshot: Annotated[dict[str, int], merge_last]
    route_decision: Annotated[dict[str, Any], merge_last]


def new_state(idea: str, run_id: str | None = None) -> AgentState:
    """Create a fresh run with every channel initialized."""
    return {
        "run_id": run_id or "",
        "idea": idea,
        "plan": [],
        "next_action": None,
        "iteration_count": 0,
        "completed": [],
        "current_task": None,
        "results": {},
        "product_document": "",
        "output_path": "",
        "status": "running",
        "error": None,
        "retries": {},
        "review_stage": None,
        "review_decision": None,
        "review_feedback": None,
        "review_issue_lists": {},
        "review_issues": [],
        "review_issue_ledger": {},
        "review_rounds": {},
        "gate_status": {},
        "messages": [],
        "stages": {},
        "revision_queue": [],
        "review_status": "pending",
        "review_result": {},
        "review_approved_snapshot": None,
        "document_status": "pending",
        "document_snapshot": {},
        "route_decision": {},
    }
