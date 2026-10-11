"""LangGraph wiring for the deterministic product-document workflow."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from backend.agents import (
    AGENT_SPECS,
    AgentSpec,
    ReviewResult,
    build_agent,
    extract_structured,
)
from backend.config import Settings
from backend.llm.chat_model import create_chat_model
from backend.tools.document_generator import render_document, save_document
from backend.workflow.catalog import WorkflowPlan, get_plan
from backend.workflow.human_review import Reviewer, make_human_review
from backend.workflow.invalidation import build_invalidation_update
from backend.workflow.policy import Decision, artifact_snapshot, decide_next
from backend.workflow.state import AgentState

logger = logging.getLogger(__name__)

REVIEWER_SPEC: AgentSpec = AGENT_SPECS["reviewer"]
_SECRET_TOKEN_PATTERN = re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{6,}|Bearer\s+\S+)\b")
_ERROR_MESSAGE_LIMIT = 500


def _safe_error_log_value(value: Any, settings: Settings) -> str | None:
    """Return a bounded, single-line diagnostic value with configured keys redacted."""
    if not isinstance(value, (str, int, float)):
        return None

    text = str(value)
    for name in ("llm_api_key", "openai_api_key", "deepseek_api_key", "qwen_api_key"):
        secret = getattr(settings, name, None)
        if isinstance(secret, str) and secret:
            text = text.replace(secret, "[REDACTED]")
    text = _SECRET_TOKEN_PATTERN.sub("[REDACTED]", text)
    return " ".join(text.split())[:_ERROR_MESSAGE_LIMIT]


def _provider_error_log_fields(exc: Exception, settings: Settings) -> dict[str, Any]:
    """Extract only safe, useful fields from an OpenAI-compatible API error body."""
    fields: dict[str, Any] = {}
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        fields["http_status"] = status_code

    body = getattr(exc, "body", None)
    if not isinstance(body, Mapping):
        return fields

    error_body = body.get("error", body)
    if isinstance(error_body, str):
        message = error_body
        error_body = {}
    elif not isinstance(error_body, Mapping):
        return fields
    else:
        message = error_body.get("message")

    for source_key, log_key in (
        ("code", "provider_error_code"),
        ("type", "provider_error_type"),
        ("param", "provider_error_param"),
    ):
        value = _safe_error_log_value(error_body.get(source_key), settings)
        if value is not None:
            fields[log_key] = value

    safe_message = _safe_error_log_value(message, settings)
    if safe_message:
        fields["provider_error_message"] = safe_message
    return fields


def _safe_error_summary(exc: Exception) -> str:
    """Keep detailed provider diagnostics in local logs, not run/API error payloads."""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return f"{type(exc).__name__} (HTTP {status_code})"
    return type(exc).__name__



def _notify_agent_call(
    callback: Any | None,
    state: AgentState,
    spec: AgentSpec,
    attempt: int,
    status: str,
    latency_ms: float,
    prompt: str,
    output_text: str | None,
    error: str | None,
    settings: Settings,
) -> None:
    if callback is None:
        return
    try:
        callback(
            {
                "run_id": str(state.get("run_id") or ""),
                "agent": spec.task_id,
                "attempt": attempt,
                "status": status,
                "latency_ms": latency_ms,
                "input": prompt,
                "output": output_text,
                "error": error,
                "model": getattr(settings, "llm_model", None),
            }
        )
    except Exception:
        logger.exception("agent call observer failed", extra={"agent": spec.task_id})


def _invoke_structured(
    agent: Any,
    spec: AgentSpec,
    state: AgentState,
    settings: Settings,
    callback: Any | None,
) -> tuple[BaseModel | None, int, str | None]:
    prompt = spec.build_input(state)
    max_attempts = max(1, int(getattr(settings, "agent_max_retries", 1)) + 1)
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        output: Any = None
        try:
            output = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
            structured = extract_structured(output, spec.output_model)
            _notify_agent_call(
                callback,
                state,
                spec,
                attempt,
                "success",
                (time.monotonic() - started) * 1000,
                prompt,
                repr(structured.model_dump(mode="json")),
                None,
                settings,
            )
            return structured, attempt, None
        except Exception as exc:
            last_error = _safe_error_summary(exc)
            _notify_agent_call(
                callback,
                state,
                spec,
                attempt,
                "failed",
                (time.monotonic() - started) * 1000,
                prompt,
                repr(output) if output is not None else None,
                last_error,
                settings,
            )
            logger.warning(
                "agent invocation failed",
                extra={
                    "run_id": str(state.get("run_id") or ""),
                    "agent": spec.task_id,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "exception_type": type(exc).__name__,
                    **_provider_error_log_fields(exc, settings),
                },
            )
            if attempt < max_attempts:
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 4.0))

    return None, max_attempts, last_error


def _current_inputs(state: AgentState, plan: WorkflowPlan, stage_id: str) -> dict[str, int]:
    snapshot = artifact_snapshot(state, plan)
    stage = plan.get(stage_id)
    if stage is None:
        raise ValueError(f"stage {stage_id!r} is not in workflow plan {plan.name!r}")
    missing = [dependency for dependency in stage.depends_on if dependency not in snapshot]
    if missing:
        raise ValueError(f"stage {stage_id!r} has stale dependencies: {missing}")
    return {dependency: snapshot[dependency] for dependency in stage.depends_on}


def make_agent_node(
    spec: AgentSpec,
    model: BaseChatModel,
    settings: Settings,
    plan: WorkflowPlan,
    on_agent_call: Any | None = None,
) -> Any:
    agent = build_agent(spec, model, settings)

    def node(state: AgentState) -> dict[str, Any]:
        try:
            input_versions = _current_inputs(state, plan, spec.task_id)
        except ValueError as exc:
            return {"status": "failed", "error": str(exc), "current_task": spec.task_id}

        result, attempts, error = _invoke_structured(
            agent, spec, state, settings, on_agent_call
        )
        if result is None:
            return {
                "status": "failed",
                "error": f"{spec.task_id} failed after {attempts} attempt(s): {error}",
                "current_task": spec.task_id,
                "retries": {spec.task_id: attempts},
            }

        payload = result.model_dump(mode="json")
        update = spec.build_state_update(payload)
        update["results"] = {**(update.get("results") or {}), spec.task_id: payload}
        current_snapshot = artifact_snapshot(state, plan)
        current_snapshot[spec.task_id] = int(
            (state.get("stages") or {}).get(spec.task_id, {}).get("artifact_version", 0)
        ) + 1
        update["completed"] = [
            stage.stage_id for stage in plan.stages if stage.stage_id in current_snapshot
        ]
        previous = (state.get("stages") or {}).get(spec.task_id, {})
        version = current_snapshot[spec.task_id]
        gate_status = "pending" if plan.require(spec.task_id).gate_node else "not_required"
        update.update(
            {
                "stages": {
                    spec.task_id: {
                        **previous,
                        "status": "current",
                        "artifact_version": version,
                        "input_versions": input_versions,
                        "gate_status": gate_status,
                    }
                },
                "gate_status": {spec.task_id: gate_status},
                "revision_queue": [
                    stage_id
                    for stage_id in (state.get("revision_queue") or [])
                    if stage_id != spec.task_id
                ],
                "review_approved_snapshot": None,
                "document_status": "stale",
                "document_snapshot": {},
                "status": "running",
                "error": None,
                "current_task": spec.task_id,
                "retries": {spec.task_id: attempts},
            }
        )
        return update

    node.__name__ = f"{spec.task_id}_node"
    return node


def _invalidation_update(
    state: AgentState,
    plan: WorkflowPlan,
    targets: list[str],
) -> dict[str, Any]:
    update = build_invalidation_update(state, targets, plan)
    gate_status = dict(state.get("gate_status") or {})
    for stage_id in (update.get("stages") or {}):
        stage = plan.get(stage_id)
        gate_status[stage_id] = "pending" if stage and stage.gate_node else "not_required"
    update["gate_status"] = gate_status
    return update


def make_gate_node(
    stage_id: str,
    settings: Settings,
    plan: WorkflowPlan,
    reviewer: Reviewer | None = None,
) -> Any:
    stage = plan.get(stage_id)
    if stage is None or stage.gate_node is None:
        raise ValueError(f"stage {stage_id!r} has no review gate")
    gate = make_human_review(stage_id, settings, reviewer)

    def node(state: AgentState) -> dict[str, Any]:
        update = gate(state)
        if update.get("status") == "failed":
            return update
        if update.get("review_decision") != "revise":
            return update

        rounds = int((update.get("review_rounds") or {}).get(stage_id, 0))
        if rounds > settings.max_review_rounds:
            return {
                **update,
                "status": "failed",
                "error": f"{stage_id} review rounds exhausted with unresolved feedback",
            }
        feedback = str(update.get("review_feedback") or "").strip()
        issue = {
            "issue_id": f"human-{stage_id}-{rounds}",
            "target": stage_id,
            "severity": "medium",
            "category": "human_review",
            "problem": feedback,
            "acceptance_criteria": [feedback],
            "suggestion": feedback,
            "status": "open",
        }
        return {
            **update,
            **_invalidation_update(state, plan, [stage_id]),
            "review_issues": [issue],
            "review_issue_lists": {stage_id: [issue]},
            "current_task": stage.gate_node,
        }

    node.__name__ = f"{stage.gate_node}_node"
    return node


def _review_issue_view(issue: Mapping[str, Any]) -> dict[str, Any]:
    """Remove Reviewer-only bookkeeping from a public issue payload."""
    return {key: value for key, value in issue.items() if not key.startswith("_")}


def _has_issue_evidence(issue: Mapping[str, Any]) -> bool:
    """Only let actionable findings block when they have evidence and acceptance criteria."""
    evidence = issue.get("evidence")
    criteria = issue.get("acceptance_criteria")
    return (
        isinstance(evidence, list)
        and any(isinstance(item, str) and item.strip() for item in evidence)
        and isinstance(criteria, list)
        and any(isinstance(item, str) and item.strip() for item in criteria)
    )


def make_reviewer_node(
    model: BaseChatModel,
    settings: Settings,
    plan: WorkflowPlan,
    on_agent_call: Any | None = None,
) -> Any:
    agent = build_agent(REVIEWER_SPEC, model, settings)

    def node(state: AgentState) -> dict[str, Any]:
        round_no = int((state.get("review_rounds") or {}).get("reviewer", 0)) + 1
        result, attempts, error = _invoke_structured(
            agent, REVIEWER_SPEC, state, settings, on_agent_call
        )
        if not isinstance(result, ReviewResult):
            return {
                "status": "failed",
                "error": f"reviewer failed after {attempts} attempt(s): {error}",
                "current_task": "reviewer",
                "retries": {"reviewer": attempts},
            }

        previous_ledger = {
            str(issue_id): dict(issue)
            for issue_id, issue in (state.get("review_issue_ledger") or {}).items()
            if isinstance(issue, Mapping)
        }
        ledger = {issue_id: dict(issue) for issue_id, issue in previous_ledger.items()}
        snapshot = artifact_snapshot(state, plan)
        suggestions = list(result.suggestions)
        seen_ids: set[str] = set()
        duplicate_ids: set[str] = set()

        for issue_model in result.issues:
            issue = issue_model.model_dump(mode="json")
            issue_id = str(issue.get("issue_id") or "").strip()
            if not issue_id:
                suggestions.append(
                    f"未采纳一条阻塞发现：缺少稳定 issue_id（{issue.get('problem', '')}）"
                )
                continue
            if issue_id in seen_ids:
                duplicate_ids.add(issue_id)
                continue
            seen_ids.add(issue_id)
            previous = previous_ledger.get(issue_id)
            if previous is None:
                if not _has_issue_evidence(issue):
                    suggestions.append(
                        f"未采纳无充分证据或验收条件的新问题 {issue_id}：{issue.get('problem', '')}"
                    )
                    continue
                if issue.get("target") not in plan.stage_ids:
                    return {
                        "status": "failed",
                        "error": (
                            f"reviewer returned enabled-evidence issue {issue_id} for "
                            f"stage outside this plan: {issue.get('target')}"
                        ),
                        "results": {"reviewer": result.model_dump(mode="json")},
                        "review_result": result.model_dump(mode="json"),
                        "current_task": "reviewer",
                        "review_rounds": {"reviewer": round_no},
                    }
                # A newly discovered issue always starts open; it cannot be
                # self-verified in the same response that first raises it.
                issue["status"] = "open"
                issue["verification_evidence"] = []
                issue["_identified_target_version"] = snapshot.get(str(issue["target"]))
                issue["_verification_failures"] = 0
                issue["_revision_count"] = 0
                ledger[issue_id] = issue
                continue

            previous_status = str(previous.get("status") or "open")
            proposed_status = str(issue.get("status") or "open")
            target = str(previous.get("target") or issue.get("target") or "")
            if target not in plan.stage_ids:
                return {
                    "status": "failed",
                    "error": f"reviewer ledger issue {issue_id} targets disabled stage {target}",
                    "review_result": result.model_dump(mode="json"),
                    "current_task": "reviewer",
                    "review_rounds": {"reviewer": round_no},
                }

            if previous_status in {"verified", "closed"}:
                # A resolved issue can only reopen after its target artifact changes and
                # the reviewer supplies concrete evidence of a regression.
                resolved_version = previous.get("_resolved_target_version")
                current_version = snapshot.get(target)
                regression_evidence = issue.get("evidence") or []
                can_reopen = (
                    proposed_status not in {"verified", "closed"}
                    and current_version is not None
                    and current_version != resolved_version
                    and any(isinstance(item, str) and item.strip() for item in regression_evidence)
                    and _has_issue_evidence(issue)
                )
                if can_reopen:
                    reopened = dict(previous)
                    reopened.update(
                        {
                            "status": "open",
                            "evidence": regression_evidence,
                            "verification_evidence": [],
                            "_identified_target_version": current_version,
                            "_verification_failures": 0,
                            "_revision_count": 0,
                        }
                    )
                    ledger[issue_id] = reopened
                elif proposed_status not in {"verified", "closed"}:
                    suggestions.append(
                        f"已解决问题 {issue_id} 未满足重开条件，按非阻塞建议处理"
                    )
                continue

            updated = dict(previous)
            # Keep the original issue identity and routing target stable across rounds.
            updated["target"] = target
            if issue.get("evidence"):
                updated["evidence"] = issue["evidence"]
            updated["verification_evidence"] = issue.get("verification_evidence") or []
            current_version = snapshot.get(target)
            artifact_was_revised = (
                current_version is not None
                and current_version != previous.get("_identified_target_version")
            )
            if (
                previous_status == "revision_submitted"
                and artifact_was_revised
                and proposed_status in {"verified", "closed"}
                and any(
                    isinstance(item, str) and item.strip()
                    for item in updated["verification_evidence"]
                )
            ):
                updated["status"] = proposed_status
                updated["_resolved_target_version"] = snapshot.get(target)
                updated["_verification_failures"] = 0
            else:
                updated["status"] = "unresolved"
                if previous_status == "revision_submitted":
                    updated["_verification_failures"] = int(
                        previous.get("_verification_failures") or 0
                    ) + 1
            ledger[issue_id] = updated

        if duplicate_ids:
            return {
                "status": "failed",
                "error": f"reviewer returned duplicate issue_id(s): {sorted(duplicate_ids)}",
                "review_result": result.model_dump(mode="json"),
                "review_rounds": {"reviewer": round_no},
                "current_task": "reviewer",
            }

        # Omission is not evidence of resolution. Carry each prior blocker forward;
        # if a revision had already been submitted, count this as a failed verification.
        for issue_id, previous in previous_ledger.items():
            if issue_id in seen_ids:
                continue
            status = str(previous.get("status") or "open")
            if status in {"verified", "closed"}:
                continue
            carried = dict(previous)
            carried["status"] = "unresolved"
            if status == "revision_submitted":
                carried["_verification_failures"] = int(
                    previous.get("_verification_failures") or 0
                ) + 1
            ledger[issue_id] = carried

        all_issues = [_review_issue_view(issue) for issue in ledger.values()]
        blocking = [
            issue for issue in ledger.values()
            if issue.get("status") not in {"verified", "closed"}
        ]
        blocking.sort(
            key=lambda issue: (
                plan.stage_ids.index(str(issue.get("target")))
                if issue.get("target") in plan.stage_ids
                else len(plan.stage_ids),
                {"high": 0, "medium": 1, "low": 2}.get(str(issue.get("severity")), 1),
            )
        )
        issue_lists = {
            stage_id: [
                _review_issue_view(issue)
                for issue in blocking
                if issue.get("target") == stage_id
            ]
            for stage_id in plan.stage_ids
        }
        payload = result.model_dump(mode="json")
        payload["issues"] = all_issues
        payload["suggestions"] = list(dict.fromkeys(suggestions))
        payload["approved"] = not blocking
        payload["target"] = blocking[0]["target"] if blocking else None
        state_update: dict[str, Any] = {
            "results": {"reviewer": payload},
            "review_result": payload,
            "review_issue_ledger": ledger,
            "review_issues": all_issues,
            "review_issue_lists": issue_lists,
            "review_rounds": {"reviewer": round_no},
            "current_task": "reviewer",
            "retries": {"reviewer": attempts},
        }

        non_converging = [
            str(issue.get("issue_id"))
            for issue in blocking
            if int(issue.get("_verification_failures") or 0) >= 2
        ]
        if non_converging:
            return {
                **state_update,
                "status": "failed",
                "review_status": "failed",
                "error": (
                    "reviewer_not_converging: issue(s) "
                    + ", ".join(non_converging)
                    + " remained unresolved in two consecutive verification rounds"
                ),
            }

        if not blocking:
            return {
                **state_update,
                "review_status": "approved",
                "review_stage": None,
                "review_approved_snapshot": snapshot,
                "revision_queue": [],
                "review_decision": "approved",
                "review_feedback": None,
            }

        # MAX_REVIEW_ROUNDS bounds revision cycles. A final verification pass is
        # still allowed after the last permitted revision.
        revisions_already_submitted = round_no - 1
        if revisions_already_submitted >= settings.max_review_rounds:
            return {
                **state_update,
                "status": "failed",
                "review_status": "failed",
                "error": "max_review_rounds_exceeded: unresolved Reviewer issues remain",
            }

        targets = list(dict.fromkeys(str(issue["target"]) for issue in blocking))
        for issue in blocking:
            issue_id = str(issue["issue_id"])
            queued = dict(ledger[issue_id])
            queued["status"] = "revision_submitted"
            queued["_revision_count"] = int(queued.get("_revision_count") or 0) + 1
            ledger[issue_id] = queued
        state_update["review_issue_ledger"] = ledger
        state_update["review_issues"] = [
            _review_issue_view(issue) for issue in ledger.values()
        ]
        state_update["review_result"]["issues"] = state_update["review_issues"]
        state_update["results"]["reviewer"]["issues"] = state_update["review_issues"]
        feedback = "\n".join(
            str(issue.get("problem") or "").strip()
            for issue in blocking
            if str(issue.get("problem") or "").strip()
        )
        state_update.update(
            {
                "review_decision": "revise",
                "review_stage": targets[0],
                "review_feedback": feedback or "Reviewer requested a revision.",
                "review_status": "needs_revision",
                **_invalidation_update(state, plan, targets),
            }
        )
        return state_update

    node.__name__ = "reviewer_node"
    return node


def make_supervisor_node(settings: Settings, plan: WorkflowPlan) -> Any:
    def node(state: AgentState) -> dict[str, Any]:
        decision: Decision = decide_next(
            state,
            plan,
            max_routing_steps=int(getattr(settings, "max_routing_steps", 100)),
        )
        update: dict[str, Any] = {
            "plan": list(plan.stage_ids),
            "next_action": decision.target,
            "route_decision": {
                "target": decision.target,
                "action": decision.action,
                "reason": decision.reason,
                "stage_id": decision.stage_id,
            },
            "iteration_count": int(state.get("iteration_count") or 0) + 1,
            "current_task": "supervisor",
        }
        if decision.action == "fail":
            update.update(
                {
                    "status": "failed",
                    "error": decision.reason,
                    "next_action": "end",
                }
            )
        elif decision.action == "terminate":
            if decision.reason == "workflow_complete":
                update["status"] = "done"
            update["next_action"] = "end"
        return update

    node.__name__ = "supervisor_node"
    return node


def allowed_next(state: AgentState, settings: Settings) -> list[str]:
    """Compatibility wrapper returning the deterministic Supervisor's single choice."""
    plan = get_plan(settings.agent_set)
    decision = decide_next(
        state,
        plan,
        max_routing_steps=int(getattr(settings, "max_routing_steps", 100)),
    )
    return [decision.target]


def route_supervisor(state: AgentState) -> str:
    return str(state.get("next_action") or "end")


def make_document_node(settings: Settings, plan: WorkflowPlan) -> Any:
    def node(state: AgentState) -> dict[str, Any]:
        snapshot = artifact_snapshot(state, plan)
        approved = dict(state.get("review_approved_snapshot") or {})
        if state.get("review_status") != "approved" or approved != snapshot:
            return {
                "status": "failed",
                "error": "refusing to write a document from an unapproved or stale snapshot",
                "current_task": "document",
            }
        content = render_document(state)
        run_id = str(state.get("run_id") or "default")
        path = save_document(content, Path(settings.output_dir) / run_id)
        return {
            "product_document": content,
            "output_path": str(path),
            "document_status": "current",
            "document_snapshot": snapshot,
            "status": "done",
            "current_task": "document",
        }

    node.__name__ = "document_node"
    return node


def build_graph(
    settings: Settings,
    model: BaseChatModel | None = None,
    reviewer: Reviewer | None = None,
    checkpointer: Any | None = None,
    on_agent_call: Any | None = None,
) -> CompiledStateGraph:
    """Build the configured MVP or Full star graph with a deterministic Supervisor."""
    plan = get_plan(settings.agent_set)
    client = model or create_chat_model(settings)
    graph: StateGraph = StateGraph(AgentState)
    graph.add_node("supervisor", make_supervisor_node(settings, plan))

    routed_nodes: list[str] = ["reviewer", "document"]
    for stage in plan.stages:
        spec = AGENT_SPECS.get(stage.node)
        if spec is None:
            raise ValueError(f"stage {stage.stage_id!r} has no registered AgentSpec")
        graph.add_node(
            stage.node,
            make_agent_node(spec, client, settings, plan, on_agent_call),
        )
        routed_nodes.append(stage.node)
        if stage.gate_node:
            graph.add_node(
                stage.gate_node,
                make_gate_node(stage.stage_id, settings, plan, reviewer),
            )
            routed_nodes.append(stage.gate_node)

    graph.add_node("reviewer", make_reviewer_node(client, settings, plan, on_agent_call))
    graph.add_node("document", make_document_node(settings, plan))
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {**{node: node for node in routed_nodes}, "end": END},
    )
    for node_name in routed_nodes:
        if node_name != "document":
            graph.add_edge(node_name, "supervisor")
    graph.add_edge("document", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())
