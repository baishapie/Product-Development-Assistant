"""MVP 工作流图：Supervisor 星型动态路由。

``START → supervisor``；``supervisor`` 条件边按 ``next_action`` 分发到各节点；
专家 / 闸门 / Reviewer 执行后统一回边到 ``supervisor``；``document → END``。
任一节点最终失败置 ``status=failed``；路由步数超 ``MAX_ROUTING_STEPS`` 强制收敛。
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.agents import (
    AGENT_SPECS,
    REVIEWER_SPEC,
    SUPERVISOR_SPEC,
    AgentOutputError,
    AgentSpec,
    build_agent,
    extract_structured,
)
from backend.agents.context import MissingRequiredResult
from backend.agents.registry import (
    CONTROL_NODES,
    GATED_TASKS,
    allowed_nodes,
    gate_nodes,
    parallel_groups,
    required_tasks,
)
from backend.agents.supervisor import POSSIBLE_NODES, resolve_plan
from backend.config import Settings
from backend.llm.chat_model import create_chat_model
from backend.tools.consistency import check_consistency
from backend.tools.document_generator import render_document, save_document
from backend.workflow.human_review import Reviewer, make_human_review
from backend.workflow.state import AgentState

logger = logging.getLogger(__name__)

# Agent 输入/输出日志的单条长度上限（超出截断并标注总长度）
_IO_LIMIT = 8000


def _short_json(value: Any, limit: int = _IO_LIMIT) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else f"{text[:limit]}...(共 {len(text)} 字符)"


def _short_text(value: str, limit: int = _IO_LIMIT) -> str:
    """按普通文本截断，避免日志层再次转义引号和换行。"""
    return value if len(value) <= limit else f"{value[:limit]}...(共 {len(value)} 字符)"


def _extract_usage(output: Any) -> dict[str, int | None]:
    """从 Agent 子图输出中汇总 token 用量（LangChain ``usage_metadata``）。

    工具循环可能产生多条 AI 消息，逐条累加；无用量信息时返回全 None。
    """
    messages = output.get("messages") if isinstance(output, dict) else None
    prompt = completion = total = 0
    found = False
    for message in messages or []:
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            continue
        found = True
        prompt += int(usage.get("input_tokens") or 0)
        completion += int(usage.get("output_tokens") or 0)
        total += int(usage.get("total_tokens") or 0)
    if not found:
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


# Supervisor 可路由到的节点（所有集合的超集 + 并行控制节点；实际映射在 build_graph 中按配置收敛）
ROUTABLE_NODES: tuple[str, ...] = tuple(
    dict.fromkeys([*(node for node in POSSIBLE_NODES if node != "end"), *CONTROL_NODES])
)

# 闸门阶段 -> 对应任务（仅对配置了闸门的任务生效）
STAGE_TASK: dict[str, str] = {task: task for task in GATED_TASKS}
# 已通过/跳过的闸门状态
_RESOLVED = ("approved", "skipped")


def allowed_next(state: AgentState, settings: Settings) -> list[str]:
    """依据状态计算合法的下一节点候选（确定性，保证收敛）。"""
    if state.get("status") == "failed":
        return ["end"]
    if state.get("review_decision") == "revise":
        stage = state.get("review_stage")
        # 可回退到任一专家（人工闸门阶段 + 全部计划任务，含 backend/frontend/qa）
        revisable = set(STAGE_TASK) | set(required_tasks(settings))
        return [stage] if stage in revisable else ["end"]

    plan = list(state.get("plan") or [])
    if not plan:
        # 首轮：尚未规划，允许在本集合的计划任务中选择
        return list(required_tasks(settings))

    completed = set(state.get("completed") or [])
    gate_status = state.get("gate_status") or {}
    # 已执行但闸门未决的任务优先进入闸门
    for stage, task in STAGE_TASK.items():
        if task in completed and gate_status.get(stage) not in _RESOLVED:
            return [f"review_{stage}"]
    # 计划中尚未完成的任务（按计划顺序）
    pending = [task for task in plan if task not in completed]
    # 并行组全部待执行 → 交给 fanout 同时分发（同一步并发）
    pending_set = set(pending)
    for group in parallel_groups(settings):
        if set(group) <= pending_set:
            return ["fanout"]
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


def _finalize_supervisor(
    update: dict[str, Any],
    candidates: list[str],
    iteration: int,
    settings: Settings,
    strategy: str,
) -> dict[str, Any]:
    """应用路由步数护栏并记录日志（快路径与 LLM 路径共用）。"""
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
        extra={"next": update["next_action"], "iteration": iteration, "strategy": strategy},
    )
    return update


# 不可重试的 HTTP 状态（配置/鉴权/请求错误，重试无益）
_NON_RETRIABLE_STATUS = {400, 401, 403, 404, 422}


def _status_code(exc: Exception) -> int | None:
    """从异常中提取 HTTP 状态码（openai/LangChain 通常挂在 status_code 上）。"""
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return int(status) if isinstance(status, int) else None


def _is_retriable(exc: Exception) -> bool:
    """判断异常是否值得重试：429/5xx 及无状态码（网络/超时/结构缺失）可重试。"""
    if isinstance(exc, MissingRequiredResult):
        return False
    status = _status_code(exc)
    if status is None:
        return True
    return status >= 500 or status == 429


def _backoff_seconds(attempt: int, settings: Settings) -> float:
    """指数退避 + 抖动（上限 ``RETRY_BACKOFF_MAX_SECONDS``）。"""
    base = getattr(settings, "retry_backoff_base_seconds", 2.0)
    cap = getattr(settings, "retry_backoff_max_seconds", 20.0)
    delay = min(base * (2 ** attempt), cap)
    return delay * (0.5 + random.random() * 0.5)


def _record_agent_call(
    callback: Any | None,
    state: AgentState,
    agent: str,
    attempt: int,
    status: str,
    latency_ms: float,
    input_text: str,
    output_text: str | None,
    error: str | None,
    model: str | None = None,
    usage: dict[str, int | None] | None = None,
) -> None:
    """把一次 Agent 调用（含 token 用量）写入回调（如 agent_calls 表）。"""
    if callback is None:
        return
    usage = usage or {}
    try:
        callback(
            {
                "run_id": state.get("run_id"),
                "agent": agent,
                "attempt": attempt + 1,
                "status": status,
                "latency_ms": latency_ms,
                "input": input_text,
                "output": output_text,
                "error": error,
                "model": model,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        )
    except Exception:  # noqa: BLE001 - 记录失败不影响主流程
        logger.warning("record agent call failed", exc_info=True)


def _make_structured_fallback(model: Any, output_model: Any) -> Any | None:
    """构建"结构化输出兜底"Runnable；不支持时返回 None。"""
    try:
        return model.with_structured_output(output_model)
    except Exception:  # noqa: BLE001 - 兜底不可用不影响主流程
        logger.warning("structured fallback unavailable", extra={"schema": output_model.__name__})
        return None


def _run_structured_fallback(
    structured_fallback: Any | None, out: Any, prompt: str, spec: AgentSpec
) -> Any:
    """主调用缺少 structured_response 时的兜底：用 with_structured_output 再取一次。"""
    if structured_fallback is None:
        raise AgentOutputError(f"{spec.output_model.__name__}: no structured_response")
    logger.info("agent structured fallback", extra={"agent": spec.task_id})
    pieces = [prompt]
    messages = out.get("messages") if isinstance(out, dict) else None
    for message in messages or []:
        if getattr(message, "type", None) == "ai":
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                pieces.append(f"你此前的回答（请据此整理为结构化结果）：\n{content}")
    pieces.append("请仅返回符合要求的结构化 JSON，不要输出解释或代码围栏。")
    return structured_fallback.invoke([{"role": "user", "content": "\n\n".join(pieces)}])


def _structured_result(
    out: Any, spec: AgentSpec, prompt: str, structured_fallback: Any | None
) -> Any:
    """先按子图结构化结果取值；缺失则走兜底。"""
    try:
        return extract_structured(out, spec.output_model)
    except AgentOutputError:
        return _run_structured_fallback(structured_fallback, out, prompt, spec)


def _invoke_with_retries(
    agent: Any,
    spec: AgentSpec,
    state: AgentState,
    settings: Settings,
    on_agent_call: Any | None = None,
    structured_fallback: Any | None = None,
) -> tuple[Any, int, Exception | None]:
    """调用 Agent 子图并解析结构化输出，按 ``AGENT_MAX_RETRIES`` 分层重试。

    分层策略：结构化缺失先走兜底（``structured_fallback``）；异常按可重试性分类，
    不可重试（4xx 配置/鉴权）立即失败；可重试则指数退避 + 抖动，并受节点 deadline 约束。
    """
    attempts = settings.agent_max_retries + 1
    deadline = time.perf_counter() + getattr(settings, "agent_deadline_seconds", 180)
    last_error: Exception | None = None
    for attempt in range(attempts):
        if attempt > 0 and time.perf_counter() >= deadline:
            logger.warning("agent deadline exceeded", extra={"agent": spec.task_id})
            break
        started = time.perf_counter()
        prompt = ""
        try:
            prompt = spec.build_input(state)
            logger.info(
                "agent input",
                extra={"agent": spec.task_id, "attempt": attempt + 1, "input": _short_text(prompt)},
            )
            out = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
            result = _structured_result(out, spec, prompt, structured_fallback)
            latency = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                "agent done",
                extra={
                    "agent": spec.task_id,
                    "attempt": attempt,
                    "latency_ms": latency,
                    "output": _short_json(result.model_dump()),
                },
            )
            _record_agent_call(
                on_agent_call, state, spec.task_id, attempt, "ok", latency,
                _short_text(prompt), _short_json(result.model_dump()), None,
                model=settings.provider_config().model, usage=_extract_usage(out),
            )
            return result, attempt, None
        except Exception as exc:  # noqa: BLE001 - 统一归一化失败并重试
            last_error = exc
            latency = round((time.perf_counter() - started) * 1000, 1)
            logger.warning(
                "agent attempt failed",
                extra={
                    "agent": spec.task_id,
                    "attempt": attempt + 1,
                    "latency_ms": latency,
                    "error": str(exc),
                },
            )
            _record_agent_call(
                on_agent_call, state, spec.task_id, attempt, "failed", latency,
                _short_text(prompt), None, str(exc),
            )
            if not _is_retriable(exc):
                logger.error(
                    "agent error not retriable",
                    extra={"agent": spec.task_id, "error": str(exc)[:200]},
                )
                break
            if attempt + 1 < attempts:
                delay = _backoff_seconds(attempt, settings)
                logger.info(
                    "agent retry backoff",
                    extra={"agent": spec.task_id, "delay_s": round(delay, 2)},
                )
                time.sleep(delay)
    return None, attempts - 1, last_error


def make_agent_node(
    spec: AgentSpec,
    model: BaseChatModel,
    settings: Settings,
    on_agent_call: Any | None = None,
) -> Any:
    """把专家 Agent 包成图节点：重试、写 results/completed、重置确认字段。"""
    agent = build_agent(spec, model, settings)
    structured_fallback = _make_structured_fallback(model, spec.output_model)

    def node(state: AgentState) -> dict[str, Any]:
        result, attempt, error = _invoke_with_retries(
            agent, spec, state, settings, on_agent_call, structured_fallback
        )
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
    on_agent_call: Any | None = None,
) -> Any:
    """Supervisor 节点：首轮规划；每轮在候选集内选择并写 ``next_action``。"""
    agent = build_agent(spec, model, settings)
    structured_fallback = _make_structured_fallback(model, spec.output_model)

    def node(state: AgentState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {"next_action": "end", "current_task": "supervisor"}

        candidates = allowed_next(state, settings)
        iteration = int(state.get("iteration_count") or 0) + 1

        # 快路径：候选唯一且计划已生成 → 路由已确定，无需调用 LLM。
        # 只返回流程控制字段，plan/results/review_* 等由状态合并原样保留（保证 Agent 间状态传递）。
        if len(candidates) == 1 and state.get("plan"):
            update: dict[str, Any] = {
                "next_action": candidates[0],
                "iteration_count": iteration,
                "current_task": "supervisor",
            }
            return _finalize_supervisor(update, candidates, iteration, settings, "deterministic")

        # 首轮规划 / 多候选：调用 LLM 决策（仅此处会产生一次 LLM 调用）
        prompt_state = {
            **state,
            "_required_tasks": required_tasks(settings),
            "_allowed_next": candidates,
        }
        decision, attempt, error = _invoke_with_retries(
            agent, spec, prompt_state, settings, on_agent_call, structured_fallback
        )
        if decision is None:
            return {
                "status": "failed",
                "error": f"supervisor: {error}",
                "next_action": "end",
                "current_task": "supervisor",
            }
        update = spec.build_state_update(decision.model_dump())
        if not state.get("plan"):
            # 首轮必须落地计划（模型未给出合法 tasks 时回退默认顺序）
            update["plan"] = resolve_plan(list(decision.tasks or []), required_tasks(settings))
        update["next_action"] = _choose_next(decision.next, candidates)
        update["iteration_count"] = iteration
        update["current_task"] = "supervisor"
        update["retries"] = {"supervisor": attempt}
        return _finalize_supervisor(update, candidates, iteration, settings, "llm")

    node.__name__ = "supervisor_node"
    return node


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _pick_target(issues: list[Any]) -> str:
    """按严重度选择最该回退的目标（high > medium > low，同级取先出现者）。"""
    valid = [issue for issue in issues if getattr(issue, "target", None)]
    if not valid:
        return "architect"
    best = min(valid, key=lambda issue: _SEVERITY_ORDER.get(issue.severity, 3))
    return best.target


def _issue_payload(issue: Any, index: int) -> dict[str, Any]:
    """把确定性或旧版问题统一成 ReviewIssue 兼容的字典。"""
    if hasattr(issue, "model_dump"):
        payload = issue.model_dump()
    elif isinstance(issue, dict):
        payload = dict(issue)
    else:
        payload = {"problem": str(issue)}
    payload.setdefault("issue_id", f"CONSISTENCY-{index:03d}")
    payload.setdefault("target", "architect")
    payload.setdefault("severity", "medium")
    payload.setdefault("category", "consistency")
    payload.setdefault("acceptance_criteria", [payload.get("problem", "请修复该问题")])
    payload.setdefault("suggestion", payload.get("problem", "请修复该问题"))
    payload.setdefault("status", "open")
    return payload


def make_reviewer_node(
    spec: AgentSpec,
    model: BaseChatModel,
    settings: Settings,
    on_agent_call: Any | None = None,
) -> Any:
    """Reviewer 节点：先做规则化一致性硬校验，再（无硬问题时）调用 LLM 语义评审。"""
    agent = build_agent(spec, model, settings)
    structured_fallback = _make_structured_fallback(model, spec.output_model)

    def node(state: AgentState) -> dict[str, Any]:
        rounds = int((state.get("review_rounds") or {}).get(spec.task_id, 0))

        # 规则化硬校验：有确定性问题 → 直接回退到对应 Agent（不调用 LLM）
        issues = check_consistency(state.get("results") or {})
        if issues and rounds < settings.max_review_rounds:
            target = _pick_target(issues)
            structured_issues = [_issue_payload(issue, index) for index, issue in enumerate(issues, 1)]
            details = [str(issue.get("problem") or issue.get("detail")) for issue in structured_issues]
            logger.info(
                "reviewer consistency gate",
                extra={"target": target, "count": len(details)},
            )
            return {
                "results": {
                    spec.task_id: {
                        "approved": False,
                        "target": target,
                        "score": 0,
                        "issues": structured_issues,
                        "suggestions": [f"请修正：{detail}" for detail in details],
                    }
                },
                "current_task": spec.task_id,
                "retries": {spec.task_id: 0},
                "review_stage": target,
                "review_decision": "revise",
                "review_feedback": "；".join(details),
                "review_issues": structured_issues,
                "review_rounds": {spec.task_id: rounds + 1},
                "gate_status": {spec.task_id: "revise"},
            }

        result, attempt, error = _invoke_with_retries(
            agent, spec, state, settings, on_agent_call, structured_fallback
        )
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
        issue_payloads = [issue.model_dump() for issue in result.issues]
        if result.approved or rounds >= settings.max_review_rounds:
            update.update(
                {
                    "review_stage": spec.task_id,
                    "review_decision": "approved",
                    "review_feedback": None,
                    "review_issues": issue_payloads,
                    "gate_status": {spec.task_id: "approved"},
                }
            )
            logger.info("reviewer approved", extra={"agent": spec.task_id, "rounds": rounds})
            return update

        feedback = "；".join(
            [
                *[issue.problem for issue in result.issues],
                *result.suggestions,
            ]
        ) or "评审未通过"
        target = result.target or (result.issues[0].target if result.issues else "architect")
        update.update(
            {
                "review_stage": target,
                "review_decision": "revise",
                "review_feedback": feedback,
                "review_issues": issue_payloads,
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


def make_fanout_node(settings: Settings) -> Any:
    """并行分发节点：透传；其出边触发同组多个成员（同一 super-step 并发）。"""

    def node(state: AgentState) -> dict[str, Any]:
        logger.info("fanout dispatch")
        return {"current_task": "fanout"}

    node.__name__ = "fanout_node"
    return node


def make_join_node(settings: Settings) -> Any:
    """并行汇合节点：等同组所有成员完成后回 Supervisor。"""

    def node(state: AgentState) -> dict[str, Any]:
        logger.info("fanout join")
        return {"current_task": "join"}

    node.__name__ = "join_node"
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
    on_agent_call: Any | None = None,
) -> CompiledStateGraph:
    """按 ``settings.agent_set`` 组装并编译工作流图。

    节点集合由 `backend/agents/registry.py` 决定（mvp/full），
    与 ``allowed_next``/``resolve_plan`` 同源。
    ``checkpointer`` 缺省为内存 ``MemorySaver``（测试友好）；
    生产由 ``RunManager`` 注入 ``PostgresSaver`` 以支持断点续跑。
    """
    client = model or create_chat_model(settings)

    # 按 AGENT_SET 决定要跑哪些专家与闸门（与 allowed_next / resolve_plan 同源）
    tasks = required_tasks(settings)
    gates = gate_nodes(settings)
    groups = parallel_groups(settings)
    parallel_members = {member for group in groups for member in group}
    routable = tuple(node for node in allowed_nodes(settings) if node != "end")

    graph: StateGraph = StateGraph(AgentState)
    graph.add_node(
        "supervisor",
        make_supervisor_node(client, settings, on_agent_call=on_agent_call),
    )
    for task in tasks:
        spec = AGENT_SPECS.get(task)
        if spec is None:
            raise ValueError(
                f"agent {task!r} required by AGENT_SET={settings.agent_set!r} has no AgentSpec"
            )
        graph.add_node(task, make_agent_node(spec, client, settings, on_agent_call))
    graph.add_node(
        "reviewer",
        make_reviewer_node(REVIEWER_SPEC, client, settings, on_agent_call),
    )
    for task, gate in GATED_TASKS.items():
        if gate in gates:
            graph.add_node(gate, make_human_review(task, settings, reviewer))
    graph.add_node("document", make_document_node(settings))

    if groups:
        # 并行：supervisor → fanout →（成员并发）→ join → supervisor
        graph.add_node("fanout", make_fanout_node(settings))
        graph.add_node("join", make_join_node(settings))
        for group in groups:
            for member in group:
                graph.add_edge("fanout", member)
            graph.add_edge(list(group), "join")
        graph.add_edge("join", "supervisor")

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {**{node: node for node in routable}, END: END},
    )
    for node in (*tasks, *gates, "reviewer"):
        if node in parallel_members:
            continue
        graph.add_edge(node, "supervisor")
    graph.add_edge("document", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
