"""Dependency-aware invalidation for reviewer-requested revisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from backend.workflow.catalog import WorkflowPlan


class InvalidRevisionTarget(ValueError):
    """Raised when a reviewer targets a stage outside the active plan."""


def downstream_closure(plan: WorkflowPlan, targets: Sequence[str]) -> tuple[str, ...]:
    """Return each target and all of its dependents in plan order."""
    active = set(plan.stage_ids)
    unknown = set(targets) - active
    if unknown:
        raise InvalidRevisionTarget(f"revision targets are not enabled: {sorted(unknown)}")

    affected = set(targets)
    changed = True
    while changed:
        changed = False
        for stage in plan.stages:
            if stage.stage_id not in affected and set(stage.depends_on) & affected:
                affected.add(stage.stage_id)
                changed = True
    return tuple(stage.stage_id for stage in plan.stages if stage.stage_id in affected)


def build_invalidation_update(
    state: Mapping[str, Any],
    targets: Sequence[str],
    plan: WorkflowPlan,
) -> dict[str, Any]:
    """Invalidate targets and dependents without deleting historical result payloads."""
    impacted = downstream_closure(plan, targets)
    stage_states = state.get("stages") or {}
    impacted_set = set(impacted)
    stages: dict[str, dict[str, Any]] = {}
    for stage_id in impacted:
        previous = dict(stage_states.get(stage_id, {}))
        stage = plan.require(stage_id)
        stages[stage_id] = {
            **previous,
            "status": "stale",
            "gate_status": "pending" if stage.gate_node else "not_required",
            "input_versions": {},
        }

    requested = set(targets)
    revision_queue = [stage_id for stage_id in plan.stage_ids if stage_id in requested]
    completed = [
        stage_id
        for stage_id in plan.stage_ids
        if stage_id in set(state.get("completed") or ()) and stage_id not in impacted_set
    ]
    return {
        "completed": completed,
        "stages": stages,
        "revision_queue": revision_queue,
        "review_status": "needs_revision",
        "review_approved_snapshot": None,
        "document_status": "stale",
        "document_snapshot": {},
    }
