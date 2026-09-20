"""Reviewer Agent：对产品定义与技术方案做自动评审并给出回退目标。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.agents.factory import AgentSpec, get_mapping


class ReviewResult(BaseModel):
    approved: bool
    target: Literal["product", "architect"] | None = None
    score: int = Field(default=0, ge=0, le=100)
    issues: list[str] = []
    suggestions: list[str] = []


SYSTEM_PROMPT = (
    "你是一名严格的评审专家，负责检查产品定义与技术方案的一致性、完整性、可行性与逻辑。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "approved(布尔，是否通过)；target(字符串，不通过时的回退目标，"
    "取 product 或 architect，通过时可为 null)；"
    "score(整数 0-100，质量评分)；issues(字符串数组，问题列表)；"
    "suggestions(字符串数组，修改建议)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """读取 Product 与 Architect 结果，供评审。"""
    results = get_mapping(state, "results")
    product = get_mapping(results, "product")
    architect = get_mapping(results, "architect")
    return "\n".join(
        [
            "产品定义（JSON）：",
            json.dumps(product, ensure_ascii=False),
            "技术方案（JSON）：",
            json.dumps(architect, ensure_ascii=False),
            "请给出评审结论；如不通过，请将 target 设为 product 或 architect。",
        ]
    )


SPEC = AgentSpec(
    task_id="reviewer",
    system_prompt=SYSTEM_PROMPT,
    output_model=ReviewResult,
    build_input=build_input,
)
