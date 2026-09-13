"""工作流共享状态（LangGraph ``StateGraph`` 的 channel 定义）。

累加型字段用 ``Annotated`` 声明 reducer：因为 LangGraph 只对顶层字段做合并，
嵌套 dict 默认是整体覆盖，若不声明 reducer，节点返回
``{"results": {"product": ...}}`` 会把其它 Agent 的结果一并覆盖掉。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """合并字典型状态字段（results / retries / review_rounds）。"""
    return {**left, **right}


class AgentState(TypedDict):
    """工作流在各节点间传递的共享状态。"""

    # 输入
    idea: str
    # 规划（Supervisor 仅首轮写入）
    plan: list[str]
    completed: Annotated[list[str], operator.add]
    current_task: str | None
    # 各 Agent 结果：task_id -> 结构化 dict（Pydantic model_dump 后）
    results: Annotated[dict[str, dict[str, Any]], merge_dict]
    # 产物
    product_document: str
    output_path: str
    # 控制
    status: str  # "running" | "awaiting_review" | "done" | "failed"
    error: str | None
    retries: Annotated[dict[str, int], merge_dict]
    # 人工确认（HITL）：两个阶段闸门
    review_stage: str | None  # "product" | "architect" | None
    review_decision: str | None  # "approved" | "revise" | "skipped" | None
    review_feedback: str | None
    review_rounds: Annotated[dict[str, int], merge_dict]
    # 预留：Memory(Phase 3) / 对话历史
    messages: Annotated[list[dict[str, str]], operator.add]


def new_state(idea: str) -> AgentState:
    """构造工作流初始状态；所有 key 均有初值以符合 reducer 语义。"""
    return {
        "idea": idea,
        "plan": [],
        "completed": [],
        "current_task": None,
        "results": {},
        "product_document": "",
        "output_path": "",
        "status": "running",
        "error": None,
        "retries": {},
        "review_stage": None,
        "review_decision": None,
        "review_feedback": None,
        "review_rounds": {},
        "messages": [],
    }
