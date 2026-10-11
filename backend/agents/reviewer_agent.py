"""Generic Reviewer Agent for the final product-document workflow gate."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from backend.agents.context import (
    architecture_view,
    backend_index,
    frontend_index,
    product_view,
    qa_index,
    required_result,
)
from backend.agents.factory import AgentSpec, get_mapping


ReviewTarget = Literal["product", "architect", "backend", "frontend", "qa"]


class ReviewIssue(BaseModel):
    """One actionable issue and its responsible workflow stage."""

    issue_id: str = ""
    target: ReviewTarget
    severity: Literal["high", "medium", "low"] = "medium"
    category: str = "consistency"
    problem: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    verification_evidence: list[str] = Field(default_factory=list)
    suggestion: str = ""
    status: Literal["open", "revision_submitted", "verified", "unresolved", "closed"] = "open"


class ReviewResult(BaseModel):
    """The final review decision over the current artifact snapshot."""

    approved: bool
    target: ReviewTarget | None = None
    score: int = Field(default=0, ge=0, le=100)
    issues: list[ReviewIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    @field_validator("issues", mode="before")
    @classmethod
    def coerce_legacy_issues(cls, value: Any) -> Any:
        """Accept legacy string issues while upgrading them to structured issues."""
        if not isinstance(value, list):
            return value
        return [
            {
                "issue_id": f"REVIEW-{index:03d}",
                "target": "architect",
                "problem": item,
                "acceptance_criteria": [item],
                "suggestion": item,
            }
            if isinstance(item, str)
            else item
            for index, item in enumerate(value, 1)
        ]


SYSTEM_PROMPT = (
    "你是产品文档最终评审专家，必须基于当前版本化产物检查需求覆盖、技术一致性、"
    "可行性、风险与验收完整性。严格遵循输入中标记的发现模式或验证模式。"
    "每个阻塞问题必须有稳定 issue_id、负责阶段、problem、可验收的 acceptance_criteria，"
    "以及能定位到当前产物的 evidence；普通建议放入 suggestions，不得作为阻塞问题。"
    "验证模式必须逐项复用历史 issue_id：只有当前产物明确满足验收条件时才可标记 verified/closed，"
    "并提供 verification_evidence；否则标记 unresolved。不能因为历史问题未出现在本轮输出中就认为它已解决。"
    "发现新阻塞问题时必须给出当前产物证据和验收条件。已解决问题只有在负责阶段产物版本变化、"
    "且有新的回归证据时才能重开。若所有历史问题均已解决且无证据充分的新阻塞问题，必须批准。"
    "不通过时顶层 target 仅作提示，真正返修目标由未解决问题决定；通过时 target 为 null。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段：approved(布尔)；"
    "target(product/architect/backend/frontend/qa 或 null)；score(0-100)；"
    "issues(对象数组，含 evidence、verification_evidence)；suggestions(字符串数组)。"
)



def build_input(state: Mapping[str, Any]) -> str:
    """Build a compact, version-aware review input from the current workflow state."""
    results = get_mapping(state, "results")
    product = required_result(state, "product")
    architect = required_result(state, "architect")
    parts = [
        "当前启用阶段：" + ", ".join(str(stage) for stage in (state.get("plan") or [])),
        "当前产物版本索引：" + json.dumps(state.get("stages") or {}, ensure_ascii=False),
        "产品定义（评审所需字段）：",
        json.dumps(product_view(product, "reviewer"), ensure_ascii=False),
        "技术方案（评审所需字段）：",
        json.dumps(architecture_view(architect, "reviewer"), ensure_ascii=False),
    ]
    for key, label, projector in (
        ("backend", "后端接口/实体/边界索引", backend_index),
        ("frontend", "页面/交互索引", frontend_index),
        ("qa", "测试覆盖索引", qa_index),
    ):
        value = get_mapping(results, key)
        if value:
            parts += [f"{label}：", json.dumps(projector(value), ensure_ascii=False)]
    ledger = get_mapping(state, "review_issue_ledger")
    history = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in ledger.values()
        if isinstance(item, Mapping)
    ]
    mode = "发现模式（第一轮）：发现有明确证据的阻塞问题；建议放入 suggestions。" if not history else (
        "验证模式（后续轮次）：逐项验证下列历史问题；复用原 issue_id。未返回的问题仍视为未解决。"
    )
    parts.extend(["评审模式：" + mode, "历史评审问题台账：", json.dumps(history, ensure_ascii=False)])
    parts.append(
        "请给出当前评审结论。每个新阻塞问题必须提供 evidence 和 acceptance_criteria；"
        "每个标记 verified/closed 的问题必须提供 verification_evidence。"
    )
    parts.append(
        "Only these stages are enabled and may be selected as revision targets: "
        + ", ".join(str(stage) for stage in (state.get("plan") or []))
    )
    return "\n".join(parts)


REVIEWER_SPEC = AgentSpec(
    task_id="reviewer",
    system_prompt=SYSTEM_PROMPT,
    output_model=ReviewResult,
    build_input=build_input,
)

SPEC = REVIEWER_SPEC
