"""Domain Agent specifications and shared construction helpers."""

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
from backend.agents.reviewer_agent import REVIEWER_SPEC, ReviewIssue, ReviewResult

AGENT_SPECS: dict[str, AgentSpec] = {
    spec.task_id: spec
    for spec in (
        PRODUCT_SPEC,
        ARCHITECT_SPEC,
        BACKEND_SPEC,
        FRONTEND_SPEC,
        QA_SPEC,
        REVIEWER_SPEC,
    )
}

__all__ = [
    "AGENT_SPECS",
    "ARCHITECT_SPEC",
    "BACKEND_SPEC",
    "FRONTEND_SPEC",
    "PRODUCT_SPEC",
    "QA_SPEC",
    "REVIEWER_SPEC",
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
    "Page",
    "ProductSpec",
    "ReviewIssue",
    "ReviewResult",
    "RevisionItem",
    "RevisionReport",
    "SWOT",
    "TechDesign",
    "TestCase",
    "TestPlan",
    "build_agent",
    "extract_structured",
    "get_mapping",
]
