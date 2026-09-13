"""Supervisor Agent：仅在入口运行一次，产出任务计划 ``plan``。

Supervisor 不参与执行期路由（执行期由固定边串联），只负责首轮规划。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from backend.agents.base import BaseAgent

# 允许被规划的任务白名单（后续新增 Agent 时在此登记）
ALLOWED_TASKS: tuple[str, ...] = ("research", "product", "architect")
# LLM 规划失败或计划不完整时的保底顺序
DEFAULT_PLAN: list[str] = ["research", "product", "architect"]


class Plan(BaseModel):
    tasks: list[str]
    rationale: str = ""


def resolve_plan(tasks: list[str]) -> list[str]:
    """过滤到白名单并去重；若不是完整计划则回退默认顺序。"""
    filtered: list[str] = []
    for task in tasks:
        name = str(task).strip()
        if name in ALLOWED_TASKS and name not in filtered:
            filtered.append(name)
    # MVP 需要三个 Agent 全部执行，缺失任一则回退保底计划
    return filtered if set(filtered) == set(ALLOWED_TASKS) else list(DEFAULT_PLAN)


class SupervisorAgent(BaseAgent):
    """产出任务计划（仅首轮）。"""

    task_id = "supervisor"
    output_model = Plan

    system_prompt = (
        "你是一名多智能体团队的主管，负责为产品研发任务做规划。"
        "只返回 JSON 对象，不要输出解释或代码围栏。字段："
        "tasks(字符串数组，取值仅限 research、product、architect，按执行顺序排列且不重复)；"
        "rationale(string，规划理由)。"
    )

    def build_user_prompt(self, state: Mapping[str, Any]) -> str:
        idea = str(state.get("idea") or "").strip()
        return (
            f"产品想法：{idea}\n"
            "可用任务：research（市场调研）、product（产品定义）、architect（技术方案）。\n"
            "请给出任务计划。"
        )

    def build_state_update(self, data: dict[str, Any]) -> dict[str, Any]:
        """额外写入 ``plan``；不加入 ``completed``（completed 仅记录计划内任务）。"""
        plan = resolve_plan(list(data.get("tasks") or []))
        return {"results": {self.task_id: data}, "plan": plan}
