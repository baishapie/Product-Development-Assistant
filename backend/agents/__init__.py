"""多 Agent 角色包。MVP 包含：supervisor、research、product、architect。"""

from backend.agents.architect_agent import ApiEndpoint, ArchitectAgent, TechDesign
from backend.agents.base import BaseAgent, OutputValidationError, get_mapping
from backend.agents.product_agent import Feature, ProductAgent, ProductSpec
from backend.agents.research_agent import SWOT, Competitor, MarketResearch, ResearchAgent
from backend.agents.supervisor import (
    ALLOWED_TASKS,
    DEFAULT_PLAN,
    Plan,
    SupervisorAgent,
    resolve_plan,
)

__all__ = [
    "ALLOWED_TASKS",
    "DEFAULT_PLAN",
    "ApiEndpoint",
    "ArchitectAgent",
    "BaseAgent",
    "Competitor",
    "Feature",
    "MarketResearch",
    "OutputValidationError",
    "Plan",
    "ProductAgent",
    "ProductSpec",
    "ResearchAgent",
    "SWOT",
    "SupervisorAgent",
    "TechDesign",
    "get_mapping",
    "resolve_plan",
]
