"""Reviewer Agent：对产品定义与技术方案做自动评审并给出回退目标。"""

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


class ReviewIssue(BaseModel):
    issue_id: str
    target: Literal["product", "architect", "backend", "frontend", "qa"]
    severity: Literal["high", "medium", "low"] = "medium"
    category: str = "consistency"
    problem: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    suggestion: str = ""
    status: Literal["open", "unresolved", "closed"] = "open"


class ReviewResult(BaseModel):
    approved: bool
    # 不通过时的回退目标：可指向任一专家（含 backend/frontend/qa）
    target: Literal["product", "architect", "backend", "frontend", "qa"] | None = None
    score: int = Field(default=0, ge=0, le=100)
    issues: list[ReviewIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    @field_validator("issues", mode="before")
    @classmethod
    def coerce_legacy_issues(cls, value: Any) -> Any:
        """兼容第一阶段的字符串 issues，逐条升级为结构化问题。"""
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
    "你是严格的评审专家，基于提供的最新产物索引检查功能覆盖、一致性、可行性与风险。"
    "只报告有证据且可执行的问题；不要凭摘要缺少的细节臆造缺陷。"
    "优先列 1-5 个重要问题；每个问题必须有稳定 issue_id、target、severity、problem、"
    "可验收的 acceptance_criteria 和 suggestion；不通过时指定一个最该修正的已有专家目标，"
    "通过时 target 为 null。给出 0-100 分并保持结论和问题一致。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "approved(布尔，是否通过)；target(字符串，不通过时的回退目标，"
    "取 product/architect/backend/frontend/qa，通过时可为 null)；"
    "score(整数 0-100，质量评分)；issues(对象数组，字段为 issue_id/target/severity/category/"
    "problem/acceptance_criteria/suggestion/status)；"
    "suggestions(字符串数组，修改建议)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """读取各专家产物，供评审（含 backend/frontend/qa，若存在）。"""
    results = get_mapping(state, "results")
    product = required_result(state, "product")
    architect = required_result(state, "architect")
    parts = [
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
    parts.append(
        "请给出评审结论；如不通过，为每个问题指定责任专家和验收条件，"
        "并将顶层 target 设为最高严重度问题的责任专家。"
    )
    return "\n".join(parts)


SPEC = AgentSpec(
    task_id="reviewer",
    system_prompt=SYSTEM_PROMPT,
    output_model=ReviewResult,
    build_input=build_input,
)
