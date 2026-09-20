"""多 Agent 角色包：AgentSpec 装配 + Supervisor/Product/Architect/Reviewer。"""

from backend.agents.architect_agent import SPEC as ARCHITECT_SPEC
from backend.agents.architect_agent import ApiEndpoint, TechDesign
from backend.agents.factory import (
    AgentOutputError,
    AgentSpec,
    build_agent,
    extract_structured,
    get_mapping,
)
from backend.agents.product_agent import SPEC as PRODUCT_SPEC
from backend.agents.product_agent import SWOT, Competitor, Feature, MarketResearch, ProductSpec
from backend.agents.reviewer_agent import SPEC as REVIEWER_SPEC
from backend.agents.reviewer_agent import ReviewResult
from backend.agents.supervisor import (
    ALLOWED_NODES,
    ALLOWED_TASKS,
    DEFAULT_PLAN,
    SupervisorDecision,
    resolve_plan,
)
from backend.agents.supervisor import SPEC as SUPERVISOR_SPEC

# 供工作流按 task_id 取用
AGENT_SPECS: dict[str, AgentSpec] = {
    SUPERVISOR_SPEC.task_id: SUPERVISOR_SPEC,
    PRODUCT_SPEC.task_id: PRODUCT_SPEC,
    ARCHITECT_SPEC.task_id: ARCHITECT_SPEC,
    REVIEWER_SPEC.task_id: REVIEWER_SPEC,
}

__all__ = [
    "AGENT_SPECS",
    "ALLOWED_NODES",
    "ALLOWED_TASKS",
    "ARCHITECT_SPEC",
    "AgentOutputError",
    "AgentSpec",
    "ApiEndpoint",
    "Competitor",
    "DEFAULT_PLAN",
    "Feature",
    "MarketResearch",
    "PRODUCT_SPEC",
    "ProductSpec",
    "REVIEWER_SPEC",
    "ReviewResult",
    "SUPERVISOR_SPEC",
    "SWOT",
    "SupervisorDecision",
    "TechDesign",
    "build_agent",
    "extract_structured",
    "get_mapping",
    "resolve_plan",
]
