"""Pure deterministic scheduling policy for the Supervisor node."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.workflow.catalog import WorkflowPlan


@dataclass(frozen=True)
class Decision:
    """One legal next graph node selected from the current state."""

    target: str
    action: str
    reason: str
    stage_id: str | None = None


def _legacy_stage_current(state: Mapping[str, Any], stage_id: str) -> bool:
    completed = set(state.get("completed") or ())
    results = state.get("results") or {}
    return stage_id in completed and isinstance(results.get(stage_id), Mapping)


def artifact_snapshot(state: Mapping[str, Any], plan: WorkflowPlan) -> dict[str, int]:
    """Return current artifacts whose dependency versions match exactly."""
    stages = state.get("stages") or {}
    results = state.get("results") or {}
    legacy_checkpoint = not bool(stages)
    snapshot: dict[str, int] = {}

    for stage in plan.stages:
        if not stage.required or not set(stage.depends_on) <= snapshot.keys():
            continue
        expected_inputs = {dependency: snapshot[dependency] for dependency in stage.depends_on}
        runtime = stages.get(stage.stage_id) if isinstance(stages, Mapping) else None
        if isinstance(runtime, Mapping) and runtime:
            if runtime.get("status") != "current":
                continue
            if not isinstance(results.get(stage.stage_id), Mapping):
                continue
            if dict(runtime.get("input_versions") or {}) != expected_inputs:
                continue
            version = runtime.get("artifact_version")
            if isinstance(version, int) and version > 0:
                snapshot[stage.stage_id] = version
            continue
        if legacy_checkpoint and _legacy_stage_current(state, stage.stage_id):
            snapshot[stage.stage_id] = 1
    return snapshot


def _dependencies_approved(
    state: Mapping[str, Any], plan: WorkflowPlan, stage_id: str, snapshot: Mapping[str, int]
) -> bool:
    gates = state.get("gate_status") or {}
    stage = plan.require(stage_id)
    return all(
        not plan.require(dependency).gate_node or gates.get(dependency) == "approved"
        for dependency in stage.depends_on
    ) and set(stage.depends_on) <= snapshot.keys()


def decide_next(
    state: Mapping[str, Any],
    plan: WorkflowPlan,
    *,
    max_routing_steps: int = 100,
) -> Decision:
    """Select the next node; this function is deterministic and side-effect free."""
    status = state.get("status")
    if status in {"failed", "done", "complete"}:
        return Decision("end", "terminate", f"run_status_{status}")
    if int(state.get("iteration_count") or 0) >= max_routing_steps:
        return Decision("end", "fail", "max_routing_steps_exceeded")

    snapshot = artifact_snapshot(state, plan)
    gates = state.get("gate_status") or {}
    revision_queue = tuple(state.get("revision_queue") or ())

    # Reviewer targets have priority, but their prerequisites are still scheduled first.
    for stage_id in plan.stage_ids:
        if stage_id in revision_queue and stage_id not in snapshot:
            if _dependencies_approved(state, plan, stage_id, snapshot):
                return Decision(
                    plan.require(stage_id).node,
                    "revise",
                    "reviewer_requested_revision",
                    stage_id,
                )

    for stage in plan.stages:
        if not stage.required:
            continue
        current = stage.stage_id in snapshot
        if not current:
            if set(stage.depends_on) <= snapshot.keys():
                return Decision(stage.node, "execute", "stage_not_current", stage.stage_id)
            continue
        if stage.gate_node and gates.get(stage.stage_id) != "approved":
            return Decision(stage.gate_node, "gate", "stage_gate_pending", stage.stage_id)

    if len(snapshot) != len(plan.stage_ids):
        return Decision("end", "fail", "no_routable_stage")

    approved_snapshot = dict(state.get("review_approved_snapshot") or {})
    if state.get("review_status") != "approved" or approved_snapshot != snapshot:
        return Decision("reviewer", "review", "current_snapshot_not_approved")

    if (
        state.get("document_status") != "current"
        or dict(state.get("document_snapshot") or {}) != snapshot
        or not state.get("product_document")
    ):
        return Decision("document", "document", "approved_snapshot_needs_document")
    return Decision("end", "terminate", "workflow_complete")
