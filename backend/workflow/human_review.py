"""人工确认闸门（HITL）：在 Product / Architect 之后暂停等待人工输入。

两个闸门由 ``make_human_review(stage)`` 生成，逻辑一致：
- 决策优先级：注入的 ``reviewer`` > ``AUTO_APPROVE`` 自动通过 > ``interrupt()`` 人工输入；
- ``revise`` 必须携带反馈，否则按通过处理；
- 超过 ``MAX_REVIEW_ROUNDS`` 跳过该闸门（写 ``gate_status=skipped``）。
闸门只写 ``review_*`` / ``gate_status``，由 Supervisor 决定后续路由。
"""

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
    """工作流编排 / 人工交互相关错误。"""


class ReviewDecision(BaseModel):
    """人工确认结果：通过，或修改（修改必须给出文字意见）。"""

    decision: Literal["approved", "revise"]
    feedback: str = ""


class Reviewer(Protocol):
    """可注入的自动评审（测试 / 无人值守）。"""

    def decide(self, stage: str, round: int, artifact: dict[str, Any]) -> ReviewDecision: ...


def _coerce_decision(value: Any) -> ReviewDecision:
    """把 ``interrupt`` 的恢复值转换为 ``ReviewDecision``。"""
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
    """按优先级获取决策：注入 reviewer > AUTO_APPROVE > interrupt。"""
    if reviewer is not None:
        return reviewer.decide(stage, round_no, dict(artifact))
    if settings.auto_approve:
        return ReviewDecision(decision="approved")

    # 延迟导入：仅在真正需要人工中断时引入图运行时依赖
    from langgraph.types import interrupt

    payload = {
        "stage": stage,
        "artifact": dict(artifact),
        "round": round_no,
        "max_rounds": settings.max_review_rounds,
        "prompt": "请确认：输入 approve 通过，或输入修改意见",
    }
    return _coerce_decision(interrupt(payload))


def make_human_review(
    stage: str,
    settings: Settings,
    reviewer: Reviewer | None = None,
) -> Callable[[AgentState], dict[str, Any]]:
    """构造指定阶段的确认节点；``stage`` 取值为 "product" 或 "architect"。"""

    def node(state: AgentState) -> dict[str, Any]:
        rounds = int((state.get("review_rounds") or {}).get(stage, 0))
        if rounds >= settings.max_review_rounds:
            logger.warning("review gate skipped (round limit)", extra={"stage": stage})
            return {
                "current_task": f"review_{stage}",
                "review_stage": stage,
                "review_decision": "skipped",
                "review_feedback": None,
                "gate_status": {stage: "skipped"},
            }

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
