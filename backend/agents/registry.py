"""Agent 集合注册表：统一"要跑哪些 Agent、默认顺序、合法路由目标"。

通过 ``settings.agent_set``（mvp/full）切换，保证三处一致：
- `resolve_plan` 的计划白名单（`required_tasks`）
- `allowed_next` 的候选集（计划任务 + 闸门）
- `build_graph` 实际挂载的节点（`allowed_nodes`）

新增 Agent/节点时只在此登记，避免散落的静态常量导致"规划到不存在的节点"。
"""

from __future__ import annotations

from backend.config import Settings

# 各集合要执行的 Agent（按默认执行顺序）
AGENT_SETS: dict[str, tuple[str, ...]] = {
    "mvp": ("product", "architect"),
    "full": ("product", "architect", "backend", "frontend", "qa"),
}

# 需要人工闸门的任务 -> 闸门节点名
GATED_TASKS: dict[str, str] = {
    "product": "review_product",
    "architect": "review_architect",
}

# 始终存在的非专家节点
BASE_NODES: tuple[str, ...] = ("reviewer", "document", "end")

# 并行执行组（同组节点由 fanout 同时分发、join 汇合后再回 Supervisor）
PARALLEL_GROUPS: tuple[tuple[str, ...], ...] = (("backend", "frontend"),)

# 并行控制节点
CONTROL_NODES: tuple[str, ...] = ("fanout", "join")


def parallel_groups(settings: Settings) -> tuple[tuple[str, ...], ...]:
    """启用并行且组内成员都在当前集合中时，返回生效的并行组。"""
    if not settings.parallel_agents:
        return ()
    required = set(required_tasks(settings))
    return tuple(group for group in PARALLEL_GROUPS if set(group) <= required)


def required_tasks(settings: Settings) -> tuple[str, ...]:
    """本轮要执行的专家任务（白名单）。"""
    return AGENT_SETS.get(settings.agent_set, AGENT_SETS["mvp"])


def default_plan(settings: Settings) -> list[str]:
    """默认执行顺序（规划失败时的保底计划）。"""
    return list(required_tasks(settings))


def gate_nodes(settings: Settings) -> tuple[str, ...]:
    """本轮需要的闸门节点名。"""
    return tuple(GATED_TASKS[task] for task in required_tasks(settings) if task in GATED_TASKS)


def allowed_nodes(settings: Settings) -> tuple[str, ...]:
    """Supervisor 可路由到的全部节点（含闸门、Reviewer、文档、结束、并行控制节点）。"""
    nodes = [*required_tasks(settings), *gate_nodes(settings), *BASE_NODES]
    if parallel_groups(settings):
        nodes.extend(CONTROL_NODES)
    return tuple(dict.fromkeys(nodes))


def available_tasks() -> tuple[str, ...]:
    """所有集合出现过的任务（用于提示词展示）。"""
    return tuple(dict.fromkeys(task for tasks in AGENT_SETS.values() for task in tasks))
