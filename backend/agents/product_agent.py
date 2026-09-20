"""Product (PM) Agent：市场调研 + 产品定义（调研并入本节点）。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

from backend.agents.factory import AgentSpec


class Competitor(BaseModel):
    name: str
    summary: str


class SWOT(BaseModel):
    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[str]
    threats: list[str]


class MarketResearch(BaseModel):
    market_size: str
    competitors: list[Competitor]
    swot: SWOT


class Feature(BaseModel):
    name: str
    priority: Literal["P0", "P1", "P2"]


class ProductSpec(BaseModel):
    market_research: MarketResearch
    positioning: str
    target_users: list[str]
    requirements: list[str]
    features: list[Feature]
    user_stories: list[str]


SYSTEM_PROMPT = (
    "你是一名资深产品经理，负责市场调研与产品定义。只返回 JSON 对象，不要输出解释或代码围栏。"
    "字段：market_research(对象，含 market_size(字符串)、"
    "competitors(数组，元素含 name、summary)、"
    "swot(对象，含 strengths/weaknesses/opportunities/threats 四个字符串数组))；"
    "positioning(字符串，产品定位)；target_users(字符串数组，目标用户)；"
    "requirements(字符串数组，用户需求)；"
    "features(数组，元素含 name、priority[取值为 P0/P1/P2])；"
    "user_stories(字符串数组，用户故事)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """只读取职责所需字段：想法 +（可选）人工修改意见。"""
    idea = str(state.get("idea") or "").strip()
    parts = [f"产品想法：{idea}"]
    feedback = state.get("review_feedback")
    if feedback:
        parts.append(f"人工修改意见（必须满足）：{feedback}")
    parts.append("请先完成市场调研，再输出产品定义。")
    return "\n".join(parts)


SPEC = AgentSpec(
    task_id="product",
    system_prompt=SYSTEM_PROMPT,
    output_model=ProductSpec,
    build_input=build_input,
)
