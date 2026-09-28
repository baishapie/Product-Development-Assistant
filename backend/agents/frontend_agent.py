"""Frontend Agent：页面结构/路由、组件拆分、状态管理、交互流程。

依赖 Product 与 Architect 的产物；输出结构化 ``FrontendDesign``。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from backend.agents.context import architecture_view, product_view, required_result, revision_context
from backend.agents.factory import AgentSpec, RevisionItem


class Page(BaseModel):
    name: str
    route: str
    description: str
    components: list[str] = []


class Component(BaseModel):
    name: str
    responsibility: str
    props: list[str] = []


class FrontendDesign(BaseModel):
    pages: list[Page]
    components: list[Component]
    state_management: str
    interactions: list[str]
    revision_report: list[RevisionItem] = Field(default_factory=list)


SYSTEM_PROMPT = (
    "你是前端工程师，依据目标用户、功能和可用 API 设计页面、组件、状态管理与关键交互。"
    "覆盖 P0 及相关已批准功能；说明加载、空态、失败与必要离线体验，"
    "不要把未确认的 API 或实时数据当成已具备能力。"
    "页面与组件各写一条主要职责，流程简明且不重复产品背景；修订后仍返回完整结构。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "pages(数组，元素含 name、route、description、components[字符串数组])；"
    "components(数组，元素含 name、responsibility、props[字符串数组])；"
    "state_management(字符串，状态管理方案)；"
    "interactions(字符串数组，关键用户交互流程)；"
    "revision_report(修订时逐项回应 issue_id、status、changed_sections、resolution；首轮为空)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """读取 Product 与 Architect 产物（+ 可选反馈/记忆）。"""
    product = required_result(state, "product")
    architect = required_result(state, "architect")
    revisions = revision_context(state, "frontend")
    parts = []
    if not revisions:
        parts.extend(
            [
                "产品定义（前端所需字段）：",
                json.dumps(product_view(product, "frontend"), ensure_ascii=False),
                "技术方案（前端所需字段）：",
                json.dumps(architecture_view(architect, "frontend"), ensure_ascii=False),
            ]
        )
    else:
        parts.append("基于上一版前端设计进行修订：")
    memory = state.get("memory_context")
    if memory and not revisions:
        parts.insert(0, f"可参考的长期记忆/历史上下文：\n{memory}")
    parts.extend(revisions)
    parts.append("请输出前端详细设计（页面、组件、状态管理、交互流程）。")
    return "\n".join(parts)


SPEC = AgentSpec(
    task_id="frontend",
    system_prompt=SYSTEM_PROMPT,
    output_model=FrontendDesign,
    build_input=build_input,
)
