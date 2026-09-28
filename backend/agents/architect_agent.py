"""Architect Agent：技术方案（技术选型、架构、API、数据库设计）。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from backend.agents.context import product_view, required_result, revision_context
from backend.agents.factory import AgentSpec, RevisionItem
from backend.tools.search import web_search


class ApiEndpoint(BaseModel):
    method: str
    path: str
    description: str


class TechDesign(BaseModel):
    tech_stack: list[str]
    architecture: str
    database_schema: str
    api_design: list[ApiEndpoint]
    revision_report: list[RevisionItem] = Field(default_factory=list)


SYSTEM_PROMPT = (
    "你是技术架构师，基于已确认的产品功能与需求约束给出最小可落地方案。"
    "覆盖全部必要 P0，说明模块和数据流、关键数据实体、外部数据依赖与失败降级；"
    "尚未确认的数据源或实时能力标为依赖/假设，不得声称已实现。"
    "技术栈只列关键组件；架构和数据库说明分点简写，避免重复需求全文；"
    "API method/path 保持稳定，每条 description 一句话并对应产品能力。"
    "修订时保持未受影响的 API 标识与设计一致，仍输出完整结构。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "tech_stack(字符串数组，技术选型)；architecture(字符串，系统架构说明)；"
    "database_schema(字符串，数据库设计)；"
    "api_design(数组，元素含 method、path、description)。"
    "revision_report(修订时逐项回应 issue_id、status、changed_sections、resolution；首轮为空)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """只读取职责所需字段：Product 结果 +（可选）人工修改意见。"""
    product = required_result(state, "product")
    revisions = revision_context(state, "architect")
    if revisions:
        # 修订轮次使用上一版方案 + Reviewer 反馈，避免重复发送不变的产品上下文。
        parts = ["基于上一版技术方案进行修订："]
        parts.extend(revisions)
    else:
        parts = [
            "产品定义（技术设计所需字段）：",
            json.dumps(product_view(product, "architect"), ensure_ascii=False),
        ]
    parts.append("请输出技术方案。")
    return "\n".join(parts)


SPEC = AgentSpec(
    task_id="architect",
    system_prompt=SYSTEM_PROMPT,
    output_model=TechDesign,
    build_input=build_input,
    tools=(web_search,),
)
