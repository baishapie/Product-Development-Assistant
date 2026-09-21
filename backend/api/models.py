"""API 请求 / 响应模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """创建一次工作流运行。"""

    idea: str = Field(min_length=1, description="产品想法")


class RunCreated(BaseModel):
    run_id: str


class ReviewRequest(BaseModel):
    """提交人工确认结果。"""

    decision: Literal["approved", "revise"]
    feedback: str = ""


class ReviewView(BaseModel):
    """待人工确认的内容。"""

    stage: str
    round: int
    max_rounds: int
    artifact: dict[str, Any]


class RunStatus(BaseModel):
    """运行状态快照。"""

    run_id: str
    idea: str | None = None
    status: str  # running | awaiting_review | done | failed
    current_task: str | None = None
    completed: list[str] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    error: str | None = None
    review: ReviewView | None = None


class RunSummary(BaseModel):
    """历史任务列表项。"""

    run_id: str
    idea: str
    status: str
    created_at: str
    updated_at: str
    error: str | None = None


class RunList(BaseModel):
    """历史任务分页结果。"""

    total: int
    items: list[RunSummary]
