"""调研 Agent：市场调研（市场规模、竞品、SWOT）。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from backend.agents.base import BaseAgent


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


class ResearchAgent(BaseAgent):
    """产出结构化的市场调研结果。"""

    task_id = "research"
    output_model = MarketResearch

    system_prompt = (
        "你是一名资深市场研究员。针对给定的产品想法完成市场调研。"
        "只返回 JSON 对象，不要输出解释或代码围栏。字段："
        "market_size(string，市场规模)；"
        "competitors(数组，元素含 name、summary)；"
        "swot(对象，含 strengths、weaknesses、opportunities、threats 四个字符串数组)。"
    )

    def build_user_prompt(self, state: Mapping[str, Any]) -> str:
        idea = str(state.get("idea") or "").strip()
        return f"产品想法：{idea}\n请输出市场调研结果。"
