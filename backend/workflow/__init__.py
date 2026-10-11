"""Workflow public API with heavy graph imports deferred until requested."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "AgentState",
    "Decision",
    "ReviewDecision",
    "Reviewer",
    "WorkflowError",
    "WorkflowPlan",
    "allowed_next",
    "artifact_snapshot",
    "build_graph",
    "decide_next",
    "get_plan",
    "make_human_review",
    "merge_dict",
    "new_state",
    "route_supervisor",
]

_STATE_EXPORTS = {"AgentState", "merge_dict", "new_state"}
_CATALOG_EXPORTS = {"WorkflowPlan", "get_plan"}
_POLICY_EXPORTS = {"Decision", "artifact_snapshot", "decide_next"}
_GRAPH_EXPORTS = {"allowed_next", "build_graph", "route_supervisor"}
_HUMAN_EXPORTS = {"ReviewDecision", "Reviewer", "WorkflowError", "make_human_review"}


def __getattr__(name: str) -> Any:
    if name in _STATE_EXPORTS:
        return getattr(import_module("backend.workflow.state"), name)
    if name in _CATALOG_EXPORTS:
        return getattr(import_module("backend.workflow.catalog"), name)
    if name in _POLICY_EXPORTS:
        return getattr(import_module("backend.workflow.policy"), name)
    if name in _GRAPH_EXPORTS:
        return getattr(import_module("backend.workflow.graph"), name)
    if name in _HUMAN_EXPORTS:
        return getattr(import_module("backend.workflow.human_review"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
