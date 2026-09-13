"""产品 Agent：产品定义（定位、目标用户、功能、用户故事）。

读取调研结果；当存在人工确认意见时一并读取，使 revise（修改）在重跑时生效。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

from backend.agents.base import BaseAgent, get_mapping


class Feature(BaseModel):
    name: str
    priority: Literal["P0", "P1", "P2"]


class ProductSpec(BaseModel):
    positioning: str
    target_users: list[str]
    requirements: list[str]
    features: list[Feature]
    user_stories: list[str]


class ProductAgent(BaseAgent):
    """产出结构化的产品定义。"""

    task_id = "product"
    output_model = ProductSpec

    system_prompt = (
        "你是一名资深产品经理。基于产品想法与市场调研输出产品定义。"
        "只返回 JSON 对象，不要输出解释或代码围栏。字段："
        "positioning(string，产品定位)；target_users(string 数组，目标用户)；"
        "requirements(string 数组，用户需求)；"
        "features(数组，元素含 name、priority[取值为 P0/P1/P2])；"
        "user_stories(string 数组，用户故事)。"
    )

    def build_user_prompt(self, state: Mapping[str, Any]) -> str:
        idea = str(state.get("idea") or "").strip()
        research = get_mapping(get_mapping(state, "results"), "research")

        parts = [
            f"产品想法：{idea}",
            "市场调研结果（JSON）：",
            json.dumps(research, ensure_ascii=False),
        ]
        feedback = state.get("review_feedback")
        if feedback:
            parts.append(f"人工修改意见（必须满足）：{feedback}")
        parts.append("请输出产品定义。")
        return "\n".join(parts)
