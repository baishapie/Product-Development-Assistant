"""工作流共享状态（LangGraph ``StateGraph`` 的 channel 定义）。

累加型字段用 ``Annotated`` 声明 reducer：LangGraph 只对顶层字段做合并，
嵌套 dict 默认整体覆盖，若不声明 reducer，节点返回 ``{"results": {...}}``
会把其它 Agent 的结果一并覆盖掉。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """合并字典型状态字段（results / retries / review_rounds / gate_status）。"""
    return {**left, **right}


def merge_last(left: Any, right: Any) -> Any:
    """并发写入时取最后一次（last-write-wins）。

    用于可能被**同一步并行节点**写入的标量通道（如 `current_task`），
    否则 LangGraph 会因"同一 step 只能收到一个值"报 `InvalidUpdateError`。
    串行场景下与默认覆盖语义一致。
    """
    return right


class AgentState(TypedDict):
    """工作流在各节点间传递的共享状态。"""

    # 输入
    run_id: str
    idea: str
    # 规划与路由（Supervisor）
    plan: list[str]
    next_action: str | None
    iteration_count: int
    completed: Annotated[list[str], operator.add]
    # 可能被并行节点（backend/frontend）同时写入，用 merge_last 容忍多写
    current_task: Annotated[str | None, merge_last]
    # 各 Agent 结果：task_id -> 结构化 dict（Pydantic model_dump 后）
    results: Annotated[dict[str, dict[str, Any]], merge_dict]
    # 产物
    product_document: str
    output_path: str
    # 控制（可能被并行节点写入，容忍多写）
    status: Annotated[str, merge_last]  # "running" | "awaiting_review" | "done" | "failed"
    error: Annotated[str | None, merge_last]
    retries: Annotated[dict[str, int], merge_dict]
    # 人工确认（HITL）与自动评审
    review_stage: str | None  # "product" | "architect" | None
    review_decision: Annotated[str | None, merge_last]  # approved/revise/skipped/None
    review_feedback: Annotated[str | None, merge_last]
    review_issues: Annotated[list[dict[str, Any]], merge_last]
    review_rounds: Annotated[dict[str, int], merge_dict]
    gate_status: Annotated[dict[str, str], merge_dict]  # stage -> approved/revise/skipped
    # 预留：Memory(Phase 3) / 对话历史
    messages: Annotated[list[dict[str, str]], operator.add]


def new_state(idea: str, run_id: str | None = None) -> AgentState:
    """构造工作流初始状态；所有 key 均有初值以符合 reducer 语义。"""
    return {
        "run_id": run_id or "",
        "idea": idea,
        "plan": [],
        "next_action": None,
        "iteration_count": 0,
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
        "review_issues": [],
        "review_rounds": {},
        "gate_status": {},
        "messages": [],
    }
