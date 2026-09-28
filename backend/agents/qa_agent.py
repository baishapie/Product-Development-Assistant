"""QA Agent：测试策略、测试用例、验收标准。

完整版依赖 Product / Architect / Backend / Frontend 产物；
输出结构化 ``TestPlan``。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.agents.context import (
    architecture_view,
    backend_index,
    frontend_index,
    product_view,
    required_result,
    revision_context,
)
from backend.agents.factory import AgentSpec, RevisionItem


class TestCase(BaseModel):
    id: str
    name: str
    type: Literal["functional", "boundary", "exception"] = "functional"
    steps: list[str]
    expected: str


class TestPlan(BaseModel):
    test_strategy: str
    test_cases: list[TestCase]
    acceptance_criteria: list[str]
    revision_report: list[RevisionItem] = Field(default_factory=list)


SYSTEM_PROMPT = (
    "你是测试工程师，依据已确认的产品功能、约束、接口与页面索引设计可执行的测试方案。"
    "逐项覆盖全部 P0，覆盖功能、边界和异常；每条用例写清操作与可验证预期，"
    "共通边界可以合并但不得遗漏关键需求。"
    "策略和验收标准简明，不重复上游设计全文；修订后仍返回完整结构。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "test_strategy(字符串，测试策略；覆盖功能/边界/异常)；"
    "test_cases(数组，元素含 id、name、type[functional/boundary/exception]、"
    "steps[字符串数组]、expected)；"
    "acceptance_criteria(字符串数组，验收标准)；"
    "revision_report(修订时逐项回应 issue_id、status、changed_sections、resolution；首轮为空)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """读取需求与设计产物（+ 可选反馈/记忆），生成测试方案。"""
    product = required_result(state, "product")
    architect = required_result(state, "architect")
    backend = required_result(state, "backend")
    frontend = required_result(state, "frontend")
    revisions = revision_context(state, "qa")
    parts = []
    if not revisions:
        parts.extend(
            [
                "产品定义（测试所需字段）：",
                json.dumps(product_view(product, "qa"), ensure_ascii=False),
                "技术方案（接口与约束）：",
                json.dumps(architecture_view(architect, "qa"), ensure_ascii=False),
                "后端接口及边界索引：",
                json.dumps(backend_index(backend), ensure_ascii=False),
                "前端页面及交互索引：",
                json.dumps(frontend_index(frontend), ensure_ascii=False),
            ]
        )
    else:
        parts.append("基于上一版测试方案进行修订：")

    memory = state.get("memory_context")
    if memory and not revisions:
        parts.insert(0, f"可参考的长期记忆/历史上下文：\n{memory}")
    parts.extend(revisions)
    parts.append("请输出测试方案（测试策略、测试用例、验收标准）。")
    return "\n".join(parts)


SPEC = AgentSpec(
    task_id="qa",
    system_prompt=SYSTEM_PROMPT,
    output_model=TestPlan,
    build_input=build_input,
)
