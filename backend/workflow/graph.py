"""MVP 工作流图：Supervisor 星型动态路由。

``START → supervisor``；``supervisor`` 条件边按 ``next_action`` 分发到各节点；
专家 / 闸门 / Reviewer 执行后统一回边到 ``supervisor``；``document → END``。
任一节点最终失败置 ``status=failed``；路由步数超 ``MAX_ROUTING_STEPS`` 强制收敛。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.agents import (
    ARCHITECT_SPEC,
    PRODUCT_SPEC,
    REVIEWER_SPEC,
    SUPERVISOR_SPEC,
    AgentSpec,
    build_agent,
    extract_structured,
)
from backend.agents.supervisor import PLAN_TASKS, resolve_plan
from backend.config import Settings
from backend.llm.chat_model import create_chat_model
from backend.tools.document_generator import render_document, save_document
from backend.workflow.human_review import Reviewer, make_human_review
from backend.workflow.state import AgentState

logger = logging.getLogger(__name__)

# Supervisor 可路由到的节点（``end`` 单独映射到 END）
ROUTABLE_NODES: tuple[str, ...] = (
    "product",
    "architect",
    "review_product",
    "review_architect",
    "reviewer",
    "document",
)

# 闸门阶段 -> 对应任务
STAGE_TASK: dict[str, str] = {"product": "product", "architect": "architect"}
# 已通过/跳过的闸门状态
_RESOLVED = ("approved", "skipped")


def allowed_next(state: AgentState) -> list[str]:
    """依据状态计算合法的下一节点候选（确定性，保证收敛）。"""
    if state.get("status") == "failed":
        return ["end"]
    if state.get("review_decision") == "revise":
        stage = state.get("review_stage")
        return [stage] if stage in STAGE_TASK else ["end"]

    plan = list(state.get("plan") or [])
    if not plan:
        # 首轮：尚未规划，允许在计划任务中选择
        return list(PLAN_TASKS)

    completed = set(state.get("completed") or [])
    gate_status = state.get("gate_status") or {}
    # 已执行但闸门未决的任务优先进入闸门
    for stage, task in STAGE_TASK.items():
        if task in completed and gate_status.get(stage) not in _RESOLVED:
            return [f"review_{stage}"]
    # 计划中尚未完成的任务（按计划顺序）
    pending = [task for task in plan if task not in completed]
    if pending:
        return pending
    # 全部任务与人工闸门完成 → 自动评审
    if gate_status.get("reviewer") not in _RESOLVED:
        return ["reviewer"]
    if not state.get("product_document"):
        return ["document"]
    return ["end"]


def _choose_next(requested: str, candidates: list[str]) -> str:
    """在候选集内选择；非法值回退确定性策略（取候选首项）。"""
    if requested in candidates:
        return requested
    logger.warning("illegal next=%r, fallback to %r", requested, candidates[0])
    return candidates[0]


def _invoke_with_retries(
    agent: Any,
    spec: AgentSpec,
    state: AgentState,
    settings: Settings,
) -> tuple[Any, int, Exception | None]:
    """调用 Agent 子图并解析结构化输出，失败按 ``AGENT_MAX_RETRIES`` 重试。"""
    attempts = settings.agent_max_retries + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        started = time.perf_counter()
        logger.info("agent start", extra={"agent": spec.task_id, "attempt": attempt + 1})
        try:
            out = agent.invoke({"messages": [{"role": "user", "content": spec.build_input(state)}]})
            result = extract_structured(out, spec.output_model)
            logger.info(
                "agent done",
                extra={
                    "agent": spec.task_id,
                    "attempt": attempt,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            return result, attempt, None
        except Exception as exc:  # noqa: BLE001 - 统一归一化失败并重试
            last_error = exc
            logger.warning(
                "agent attempt failed",
                extra={
                    "agent": spec.task_id,
                    "attempt": attempt + 1,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": str(exc),
                },
            )
    return None, attempts - 1, last_error


def make_agent_node(spec: AgentSpec, model: BaseChatModel, settings: Settings) -> Any:
    """把专家 Agent 包成图节点：重试、写 results/completed、重置确认字段。"""
    agent = build_agent(spec, model)

    def node(state: AgentState) -> dict[str, Any]:
        result, attempt, error = _invoke_with_retries(agent, spec, state, settings)
        if result is None:
            logger.error("agent failed after retries", extra={"agent": spec.task_id})
            return {
                "status": "failed",
                "error": f"{spec.task_id}: {error}",
                "retries": {spec.task_id: attempt},
                "current_task": spec.task_id,
            }
        update = spec.build_state_update(result.model_dump())
        update["retries"] = {spec.task_id: attempt}
        update["current_task"] = spec.task_id
        # 重置确认字段，使 revise 后重跑能再次进入闸门
        update["review_decision"] = None
        update["review_feedback"] = None
        return update

    node.__name__ = f"{spec.task_id}_node"
    return node


def make_supervisor_node(
    model: BaseChatModel,
    settings: Settings,
    spec: AgentSpec = SUPERVISOR_SPEC,
) -> Any:
    """Supervisor 节点：首轮规划；每轮在候选集内选择并写 ``next_action``。"""
    agent = build_agent(spec, model)

    def node(state: AgentState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {"next_action": "end", "current_task": "supervisor"}

        candidates = allowed_next(state)
        decision, attempt, error = _invoke_with_retries(agent, spec, state, settings)
        if decision is None:
            return {
                "status": "failed",
                "error": f"supervisor: {error}",
                "next_action": "end",
                "current_task": "supervisor",
            }

        iteration = int(state.get("iteration_count") or 0) + 1
        update = spec.build_state_update(decision.model_dump())
        if not state.get("plan"):
            # 首轮必须落地计划（模型未给出合法 tasks 时回退默认顺序）
            update["plan"] = resolve_plan(list(decision.tasks or []))
        update["next_action"] = _choose_next(decision.next, candidates)
        update["iteration_count"] = iteration
        update["current_task"] = "supervisor"
        update["retries"] = {"supervisor": attempt}

        if iteration > settings.max_routing_steps:
            # 强制收敛：可产出则走文档，否则失败结束
            if "document" in candidates:
                update["next_action"] = "document"
            else:
                logger.error("routing step limit exceeded", extra={"iteration": iteration})
                update["next_action"] = "end"
                update["status"] = "failed"
                update["error"] = "routing step limit exceeded"
        logger.info(
            "supervisor route",
            extra={"next": update["next_action"], "iteration": iteration},
        )
        return update

    node.__name__ = "supervisor_node"
    return node


def make_reviewer_node(spec: AgentSpec, model: BaseChatModel, settings: Settings) -> Any:
    """Reviewer 节点：自动评审并写确认字段（通过/回退目标）。"""
    agent = build_agent(spec, model)

    def node(state: AgentState) -> dict[str, Any]:
        result, attempt, error = _invoke_with_retries(agent, spec, state, settings)
        if result is None:
            return {
                "status": "failed",
                "error": f"{spec.task_id}: {error}",
                "next_action": "end",
                "current_task": spec.task_id,
            }

        update: dict[str, Any] = {
            "results": {spec.task_id: result.model_dump()},
            "current_task": spec.task_id,
            "retries": {spec.task_id: attempt},
        }
        rounds = int((state.get("review_rounds") or {}).get(spec.task_id, 0))
        if result.approved or rounds >= settings.max_review_rounds:
            update.update(
                {
                    "review_stage": spec.task_id,
                    "review_decision": "approved",
                    "review_feedback": None,
                    "gate_status": {spec.task_id: "approved"},
                }
            )
            logger.info("reviewer approved", extra={"agent": spec.task_id, "rounds": rounds})
            return update

        feedback = "；".join([*result.issues, *result.suggestions]) or "评审未通过"
        target = result.target or "architect"
        update.update(
            {
                "review_stage": target,
                "review_decision": "revise",
                "review_feedback": feedback,
                "review_rounds": {spec.task_id: rounds + 1},
                "gate_status": {spec.task_id: "revise"},
            }
        )
        logger.info(
            "reviewer revise",
            extra={"agent": spec.task_id, "target": target, "round": rounds + 1},
        )
        return update

    node.__name__ = f"{spec.task_id}_node"
    return node


def make_document_node(settings: Settings) -> Any:
    """文档节点：渲染固定模板并落盘，置 ``status=done``。"""

    def node(state: AgentState) -> dict[str, Any]:
        content = render_document(state)
        # 按任务分目录，避免多任务互相覆盖
        run_id = str(state.get("run_id") or "default")
        path = save_document(content, Path(settings.output_dir) / run_id)
        logger.info("document written", extra={"path": str(path)})
        return {
            "product_document": content,
            "output_path": str(path),
            "status": "done",
            "current_task": "document",
        }

    node.__name__ = "document_node"
    return node


def route_supervisor(state: AgentState) -> str:
    """Supervisor 条件边：按 ``next_action`` 分发；非法/缺失则结束。"""
    target = state.get("next_action")
    if target in ROUTABLE_NODES:
        return target
    return END


def build_graph(
    settings: Settings,
    model: BaseChatModel | None = None,
    reviewer: Reviewer | None = None,
    checkpointer: Any | None = None,
) -> CompiledStateGraph:
    """组装并编译 MVP 工作流图。

    ``checkpointer`` 缺省为内存 ``MemorySaver``（测试友好）；
    生产由 ``RunManager`` 注入 ``PostgresSaver`` 以支持断点续跑。
    """
    client = model or create_chat_model(settings)

    graph: StateGraph = StateGraph(AgentState)
    graph.add_node("supervisor", make_supervisor_node(client, settings))
    graph.add_node("product", make_agent_node(PRODUCT_SPEC, client, settings))
    graph.add_node("architect", make_agent_node(ARCHITECT_SPEC, client, settings))
    graph.add_node("reviewer", make_reviewer_node(REVIEWER_SPEC, client, settings))
    graph.add_node("review_product", make_human_review("product", settings, reviewer))
    graph.add_node("review_architect", make_human_review("architect", settings, reviewer))
    graph.add_node("document", make_document_node(settings))

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {**{node: node for node in ROUTABLE_NODES}, END: END},
    )
    for node in ("product", "architect", "reviewer", "review_product", "review_architect"):
        graph.add_edge(node, "supervisor")
    graph.add_edge("document", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
