"""Architect Agent：技术方案（技术选型、架构、API、数据库设计）。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from backend.agents.factory import AgentSpec, get_mapping


class ApiEndpoint(BaseModel):
    method: str
    path: str
    description: str


class TechDesign(BaseModel):
    tech_stack: list[str]
    architecture: str
    database_schema: str
    api_design: list[ApiEndpoint]


SYSTEM_PROMPT = (
    "你是一名资深技术架构师。基于产品定义输出技术方案。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "tech_stack(字符串数组，技术选型)；architecture(字符串，系统架构说明)；"
    "database_schema(字符串，数据库设计)；"
    "api_design(数组，元素含 method、path、description)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """只读取职责所需字段：Product 结果 +（可选）人工修改意见。"""
    product = get_mapping(get_mapping(state, "results"), "product")
    parts = ["产品定义（JSON）：", json.dumps(product, ensure_ascii=False)]
    feedback = state.get("review_feedback")
    if feedback:
        parts.append(f"人工修改意见（必须满足）：{feedback}")
    parts.append("请输出技术方案。")
    return "\n".join(parts)


SPEC = AgentSpec(
    task_id="architect",
    system_prompt=SYSTEM_PROMPT,
    output_model=TechDesign,
    build_input=build_input,
)
