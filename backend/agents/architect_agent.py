"""架构 Agent：技术方案（技术选型、架构、API、数据库设计）。

读取产品定义；当存在人工确认意见时一并读取，使 revise（修改）在重跑时生效。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from backend.agents.base import BaseAgent, get_mapping


class ApiEndpoint(BaseModel):
    method: str
    path: str
    description: str


class TechDesign(BaseModel):
    tech_stack: list[str]
    architecture: str
    database_schema: str
    api_design: list[ApiEndpoint]


class ArchitectAgent(BaseAgent):
    """产出结构化的技术方案。"""

    task_id = "architect"
    output_model = TechDesign

    system_prompt = (
        "你是一名资深技术架构师。基于产品定义输出技术方案。"
        "只返回 JSON 对象，不要输出解释或代码围栏。字段："
        "tech_stack(string 数组，技术选型)；architecture(string，系统架构说明)；"
        "database_schema(string，数据库设计)；"
        "api_design(数组，元素含 method、path、description)。"
    )

    def build_user_prompt(self, state: Mapping[str, Any]) -> str:
        product = get_mapping(get_mapping(state, "results"), "product")

        parts = [
            "产品定义（JSON）：",
            json.dumps(product, ensure_ascii=False),
        ]
        feedback = state.get("review_feedback")
        if feedback:
            parts.append(f"人工修改意见（必须满足）：{feedback}")
        parts.append("请输出技术方案。")
        return "\n".join(parts)
