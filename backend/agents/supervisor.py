"""Supervisor Agent：任务规划 + 每轮动态路由决策。

白名单/默认计划来自 `backend/agents/registry.py`（按 ``AGENT_SET`` 切换）；
真正的合法性约束（``allowed_next``）由图节点在执行期校验。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

from backend.agents.factory import AgentSpec
from backend.agents.registry import BASE_NODES, GATED_TASKS, available_tasks

# 提示词里可列出的候选节点（运行时真正候选由 allowed_next 决定）
POSSIBLE_NODES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            *available_tasks(),
            *GATED_TASKS.values(),
            *BASE_NODES,
        ]
    )
)

# 合法路由目标（覆盖所有集合；运行时再按 AGENT_SET 收敛候选）
RouteTarget = Literal[
    "product",
    "architect",
    "backend",
    "frontend",
    "qa",
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


def resolve_plan(tasks: list[str], required: tuple[str, ...]) -> list[str]:
    """过滤到 ``required`` 白名单并去重；不完整则回退 ``required`` 顺序。"""
    filtered: list[str] = []
    for task in tasks:
        name = str(task).strip()
        if name in required and name not in filtered:
            filtered.append(name)
    return filtered if set(filtered) == set(required) else list(required)


def supervisor_state_update(data: dict[str, Any]) -> dict[str, Any]:
    """写 ``results["supervisor"]``；不写 completed。

    ``plan`` 由工作流节点按 ``settings.agent_set`` 解析后写入（这里拿不到 settings）。
    """
    return {"results": {"supervisor": data}}


SYSTEM_PROMPT = (
    "你是多智能体团队的调度者，只做任务规划和下一节点路由，不生成产品或技术方案。"
    "首轮 tasks 必须包含当轮所有必需任务，顺序遵守上游依赖，后续 tasks 留空；"
    "next 只能从本轮合法候选中选择。理由一句话即可。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "next(string，下一步要执行的节点)；"
    "tasks(string 数组，仅首轮填写，取值为可用任务，按执行顺序且不重复)；"
    "rationale(string，决策理由)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """给 Supervisor 的输入：想法、计划、进度、闸门状态与可选节点。"""
    idea = str(state.get("idea") or "").strip()
    plan = state.get("plan") or []
    completed = list(dict.fromkeys(state.get("completed") or []))
    results = state.get("results") or {}
    gates = state.get("gate_status") or {}
    required = state.get("_required_tasks") or available_tasks()
    candidates = state.get("_allowed_next") or POSSIBLE_NODES
    return "\n".join(
        [
            f"产品想法：{idea}",
            f"本轮必需任务（按默认依赖顺序）：{list(required)}",
            f"当前计划(plan)：{plan}",
            f"已完成(completed)：{completed}",
            f"已产出结果键：{sorted(results.keys())}",
            f"闸门/评审状态(gate_status)：{gates}",
            f"本轮修改决策/目标：{state.get('review_decision')} / {state.get('review_stage')}",
            f"本轮合法下一节点：{list(candidates)}",
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
