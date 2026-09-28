"""Product (PM) Agent：市场调研 + 产品定义（调研并入本节点）。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.agents.context import revision_context
from backend.agents.factory import AgentSpec, RevisionItem
from backend.tools.search import web_search


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
    revision_report: list[RevisionItem] = Field(default_factory=list)


SYSTEM_PROMPT = (
    "你是产品经理，依据用户想法输出可验收的产品定义与简明市场分析。"
    "优先完整保留必要 P0、隐私/数据/可靠性等硬约束，区分本期和后续功能；避免功能、需求与故事重复。"
    "定位用一两句；目标用户聚合为典型群体；需求用短句描述可验证行为（建议 5-10 条）；"
    "用户故事选 3-5 个不同场景；竞品选 2-3 个，SWOT 每维 1-2 条。"
    "功能按 P0/P1/P2 排序，建议 6-12 项，但不得因数量目标遗漏必要 P0。"
    "未有可核查来源时，市场规模只能标注估算/待验证，不要捏造精确数字或实时能力。"
    "修改时保留旧稿中未涉及的约束，仍返回完整结构化结果。"
    "字段：market_research(对象，含 market_size(字符串)、"
    "competitors(数组，元素含 name、summary)、"
    "swot(对象，含 strengths/weaknesses/opportunities/threats 四个字符串数组))；"
    "positioning(字符串，产品定位)；target_users(字符串数组，目标用户)；"
    "requirements(字符串数组，用户需求)；"
    "features(数组，元素含 name、priority[取值为 P0/P1/P2])；"
    "user_stories(字符串数组，用户故事)；"
    "revision_report(修订时逐项回应 issue_id、status、changed_sections、resolution；首轮为空)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """读取想法和当前 Product 修订意见。"""
    idea = str(state.get("idea") or "").strip()
    revisions = revision_context(state, "product")
    parts = ["基于上一版产品定义进行修订："] if revisions else [f"产品想法：{idea}"]
    parts.extend(revisions)
    parts.append(
        "请基于修改意见修订并输出完整产品定义。"
        if revisions
        else "请先完成市场调研，再输出产品定义。"
    )
    return "\n".join(parts)


SPEC = AgentSpec(
    task_id="product",
    system_prompt=SYSTEM_PROMPT,
    output_model=ProductSpec,
    build_input=build_input,
    tools=(web_search,),
)
