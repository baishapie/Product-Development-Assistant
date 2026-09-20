"""LangGraph 工作流：状态、Supervisor 动态路由图、人工闸门（延迟导入）。"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AgentState",
    "ReviewDecision",
    "Reviewer",
    "WorkflowError",
    "allowed_next",
    "build_graph",
    "make_human_review",
    "merge_dict",
    "new_state",
    "route_supervisor",
]

_STATE_EXPORTS = {"AgentState", "merge_dict", "new_state"}
_GRAPH_EXPORTS = {"allowed_next", "build_graph", "route_supervisor"}
_HUMAN_EXPORTS = {"ReviewDecision", "Reviewer", "WorkflowError", "make_human_review"}


def __getattr__(name: str) -> Any:
    if name in _STATE_EXPORTS:
        from backend.workflow import state

        return getattr(state, name)
    if name in _GRAPH_EXPORTS:
        from backend.workflow import graph

        return getattr(graph, name)
    if name in _HUMAN_EXPORTS:
        from backend.workflow import human_review

        return getattr(human_review, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
