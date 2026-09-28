"""多 Agent 角色包：AgentSpec 装配 + Supervisor/Product/Architect/Backend/Frontend/Reviewer。"""

from backend.agents.architect_agent import SPEC as ARCHITECT_SPEC
from backend.agents.architect_agent import ApiEndpoint, TechDesign
from backend.agents.backend_agent import SPEC as BACKEND_SPEC
from backend.agents.backend_agent import BackendDesign, DataModel, EndpointDetail, FieldDef
from backend.agents.factory import (
    AgentOutputError,
    AgentSpec,
    RevisionItem,
    RevisionReport,
    build_agent,
    extract_structured,
    get_mapping,
)
from backend.agents.frontend_agent import SPEC as FRONTEND_SPEC
from backend.agents.frontend_agent import Component, FrontendDesign, Page
from backend.agents.product_agent import SPEC as PRODUCT_SPEC
from backend.agents.product_agent import SWOT, Competitor, Feature, MarketResearch, ProductSpec
from backend.agents.qa_agent import SPEC as QA_SPEC
from backend.agents.qa_agent import TestCase, TestPlan
from backend.agents.registry import (
    AGENT_SETS,
    BASE_NODES,
    GATED_TASKS,
    allowed_nodes,
    available_tasks,
    default_plan,
    gate_nodes,
    required_tasks,
)
from backend.agents.reviewer_agent import SPEC as REVIEWER_SPEC
from backend.agents.reviewer_agent import ReviewIssue, ReviewResult
from backend.agents.supervisor import SPEC as SUPERVISOR_SPEC
from backend.agents.supervisor import SupervisorDecision, resolve_plan

# 供工作流按 task_id 取用
AGENT_SPECS: dict[str, AgentSpec] = {
    SUPERVISOR_SPEC.task_id: SUPERVISOR_SPEC,
    PRODUCT_SPEC.task_id: PRODUCT_SPEC,
    ARCHITECT_SPEC.task_id: ARCHITECT_SPEC,
    BACKEND_SPEC.task_id: BACKEND_SPEC,
    FRONTEND_SPEC.task_id: FRONTEND_SPEC,
    QA_SPEC.task_id: QA_SPEC,
    REVIEWER_SPEC.task_id: REVIEWER_SPEC,
}

__all__ = [
    "AGENT_SETS",
    "AGENT_SPECS",
    "ARCHITECT_SPEC",
    "BACKEND_SPEC",
    "BASE_NODES",
    "FRONTEND_SPEC",
    "GATED_TASKS",
    "AgentOutputError",
    "AgentSpec",
    "ApiEndpoint",
    "BackendDesign",
    "Competitor",
    "Component",
    "DataModel",
    "EndpointDetail",
    "Feature",
    "FieldDef",
    "FrontendDesign",
    "MarketResearch",
    "PRODUCT_SPEC",
    "Page",
    "ProductSpec",
    "QA_SPEC",
    "REVIEWER_SPEC",
    "ReviewResult",
    "ReviewIssue",
    "RevisionItem",
    "RevisionReport",
    "SUPERVISOR_SPEC",
    "SWOT",
    "SupervisorDecision",
    "TechDesign",
    "TestCase",
    "TestPlan",
    "allowed_nodes",
    "available_tasks",
    "build_agent",
    "default_plan",
    "extract_structured",
    "gate_nodes",
    "get_mapping",
    "required_tasks",
    "resolve_plan",
]
