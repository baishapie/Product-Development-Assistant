"""Supervisor Agent：任务规划 + 每轮动态路由决策。

首轮产出任务计划 ``plan``；此后每轮在合法候选集中选择一个下一节点。
真正的合法性约束（``allowed_next``）由图节点在执行期校验。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

from backend.agents.factory import AgentSpec

# 允许被规划的任务白名单（后续新增 Agent 时在此登记）
PLAN_TASKS: tuple[str, ...] = ("product", "architect")
ALLOWED_TASKS = PLAN_TASKS
# LLM 规划失败或计划不完整时的保底顺序
DEFAULT_PLAN: list[str] = ["product", "architect"]
# 合法路由目标（含闸门 / 评审 / 文档 / 结束）
ALLOWED_NODES: tuple[str, ...] = (
    "product",
    "architect",
    "review_product",
    "review_architect",
    "reviewer",
    "document",
    "end",
)

RouteTarget = Literal[
    "product",
    "architect",
    "review_product",
    "review_architect",
    "reviewer",
    "document",
    "end",
]


class SupervisorDecision(BaseModel):
    """Supervisor 每轮的决策：下一节点 +（首轮）计划 + 理由。"""

    next: RouteTarget
    tasks: list[str] = []
    rationale: str = ""


def resolve_plan(tasks: list[str]) -> list[str]:
    """过滤到白名单并去重；若不是完整计划则回退默认顺序。"""
    filtered: list[str] = []
    for task in tasks:
        name = str(task).strip()
        if name in ALLOWED_TASKS and name not in filtered:
            filtered.append(name)
    return filtered if set(filtered) == set(ALLOWED_TASKS) else list(DEFAULT_PLAN)


def supervisor_state_update(data: dict[str, Any]) -> dict[str, Any]:
    """写 ``results["supervisor"]``；首轮（有 tasks）额外写 ``plan``，不写 completed。"""
    update: dict[str, Any] = {"results": {"supervisor": data}}
    tasks = list(data.get("tasks") or [])
    if tasks:
        update["plan"] = resolve_plan(tasks)
    return update


SYSTEM_PROMPT = (
    "你是一名多智能体团队的主管，负责为产品研发任务做规划与调度。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "next(string，下一步要执行的节点，取值范围：product/architect/review_product/review_architect/reviewer/document/end)；"
    "tasks(string 数组，仅首轮填写，取值仅限 product、architect，按执行顺序且不重复)；"
    "rationale(string，决策理由)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """给 Supervisor 的输入：想法、计划、进度、闸门状态与可选节点。"""
    idea = str(state.get("idea") or "").strip()
    plan = state.get("plan") or list(DEFAULT_PLAN)
    completed = list(state.get("completed") or [])
    results = state.get("results") or {}
    gates = state.get("gate_status") or {}
    return "\n".join(
        [
            f"产品想法：{idea}",
            f"当前计划(plan)：{plan}",
            f"已完成(completed)：{completed}",
            f"已产出结果键：{sorted(results.keys())}",
            f"闸门/评审状态(gate_status)：{gates}",
            f"可选下一节点：{list(ALLOWED_NODES)}",
            "请选择下一个要执行的节点；若尚无计划，请同时给出任务计划。",
        ]
    )


SPEC = AgentSpec(
    task_id="supervisor",
    system_prompt=SYSTEM_PROMPT,
    output_model=SupervisorDecision,
    build_input=build_input,
    to_state_update=supervisor_state_update,
)
