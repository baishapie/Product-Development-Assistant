"""MVP 工作流图组装。

固定串联：supervisor → research → product → 确认① → architect → 确认② → document。
任一节点失败则跳到 END；确认闸门按 review_decision 分支（revise 回到对应 Agent）。
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.agents.architect_agent import ArchitectAgent
from backend.agents.base import BaseAgent
from backend.agents.product_agent import ProductAgent
from backend.agents.research_agent import ResearchAgent
from backend.agents.supervisor import SupervisorAgent
from backend.config import Settings
from backend.llm.base import LLMClient
from backend.llm.factory import create_llm
from backend.tools.document_generator import DocumentGeneratorTool
from backend.workflow.human_review import Reviewer, make_human_review
from backend.workflow.state import AgentState

logger = logging.getLogger(__name__)


def make_agent_node(agent: BaseAgent, settings: Settings) -> Any:
    """把 Agent 包成图节点；失败时按 ``AGENT_MAX_RETRIES`` 重试。"""

    def node(state: AgentState) -> dict[str, Any]:
        attempts = settings.agent_max_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                update = agent.run(state)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "agent attempt failed",
                    extra={"agent": agent.task_id, "attempt": attempt + 1, "error": str(exc)},
                )
                continue
            # 记录本轮实际重试次数（0 表示一次成功）
            update["retries"] = {agent.task_id: attempt}
            return update
        logger.error("agent failed after retries", extra={"agent": agent.task_id})
        return {
            "status": "failed",
            "error": f"{agent.task_id}: {last_error}",
            "retries": {agent.task_id: attempts - 1},
        }

    node.__name__ = f"{agent.task_id}_node"
    return node


def make_document_node(settings: Settings) -> Any:
    """文档生成节点：渲染中文模板并落盘。"""

    def node(state: AgentState) -> dict[str, Any]:
        tool = DocumentGeneratorTool()
        content = tool.render(state)
        path = tool.save(content, settings.output_dir)
        logger.info("document written", extra={"path": str(path)})
        return {"product_document": content, "output_path": str(path), "status": "done"}

    return node


def _route_after(next_node: str) -> Any:
    """通用路由：失败则结束，否则进入下一节点。"""

    def route(state: AgentState) -> str:
        if state.get("status") == "failed":
            return END
        return next_node

    return route


def _route_review(approve_node: str, revise_node: str) -> Any:
    """确认闸门路由：revise 回对应 Agent，否则进入下一阶段。"""

    def route(state: AgentState) -> str:
        if state.get("status") == "failed":
            return END
        if state.get("review_decision") == "revise":
            return revise_node
        return approve_node

    return route


def build_graph(
    settings: Settings,
    llm: LLMClient | None = None,
    reviewer: Reviewer | None = None,
) -> CompiledStateGraph:
    """组装并编译 MVP 工作流图（带内存 Checkpointer）。"""
    client = llm or create_llm(settings)

    graph = StateGraph(AgentState)
    graph.add_node("supervisor", make_agent_node(SupervisorAgent(client), settings))
    graph.add_node("research", make_agent_node(ResearchAgent(client), settings))
    graph.add_node("product", make_agent_node(ProductAgent(client), settings))
    graph.add_node("architect", make_agent_node(ArchitectAgent(client), settings))
    graph.add_node("review_product", make_human_review("product", settings, reviewer))
    graph.add_node("review_architect", make_human_review("architect", settings, reviewer))
    graph.add_node("document", make_document_node(settings))

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", _route_after("research"), {"research": "research", END: END}
    )
    graph.add_conditional_edges(
        "research", _route_after("product"), {"product": "product", END: END}
    )
    graph.add_conditional_edges(
        "product", _route_after("review_product"), {"review_product": "review_product", END: END}
    )
    graph.add_conditional_edges(
        "review_product",
        _route_review(approve_node="architect", revise_node="product"),
        {"architect": "architect", "product": "product", END: END},
    )
    graph.add_conditional_edges(
        "architect",
        _route_after("review_architect"),
        {"review_architect": "review_architect", END: END},
    )
    graph.add_conditional_edges(
        "review_architect",
        _route_review(approve_node="document", revise_node="architect"),
        {"document": "document", "architect": "architect", END: END},
    )
    graph.add_edge("document", END)

    return graph.compile(checkpointer=MemorySaver())
