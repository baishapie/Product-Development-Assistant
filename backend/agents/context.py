"""按角色构造 Agent 输入视图；完整产物始终保留在 results 中。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class MissingRequiredResult(ValueError):
    """上游产物缺失，重试模型调用无法修复。"""


def required_result(state: Mapping[str, Any], task: str) -> Mapping[str, Any]:
    """必需的上游结果缺失时显式失败，不向模型发送空 JSON。"""
    result = _mapping(_mapping(state.get("results")).get(task))
    if not result:
        raise MissingRequiredResult(f"missing required result: {task}")
    return result


def product_view(product: Mapping[str, Any], role: str) -> dict[str, Any]:
    """剔除市场长文，保留所有功能及需求约束；不凭关键词猜测功能归属。"""
    view: dict[str, Any] = {
        "features": [
            {"name": item.get("name"), "priority": item.get("priority")}
            for item in _items(product.get("features"))
            if isinstance(item, Mapping)
        ],
        "requirements": _items(product.get("requirements")),
    }
    if role in ("architect", "frontend", "reviewer"):
        view["positioning"] = product.get("positioning", "")
        view["target_users"] = _items(product.get("target_users"))
    if role in ("frontend", "qa"):
        # 故事可帮助设计流程/用例；内容由 Product 提示词控制长度。
        view["user_stories"] = _items(product.get("user_stories"))
    return view


def architecture_view(architect: Mapping[str, Any], role: str) -> dict[str, Any]:
    """保留全部 API 标识和必要的架构约束，不把数据库正文传给前端。"""
    view: dict[str, Any] = {
        "api_design": [
            {
                "method": item.get("method"),
                "path": item.get("path"),
                "description": item.get("description"),
            }
            for item in _items(architect.get("api_design"))
            if isinstance(item, Mapping)
        ],
    }
    if role in ("backend", "frontend", "reviewer"):
        view["architecture"] = architect.get("architecture", "")
        view["tech_stack"] = _items(architect.get("tech_stack"))
    if role in ("backend", "reviewer"):
        view["database_schema"] = architect.get("database_schema", "")
    return view


def backend_index(backend: Mapping[str, Any]) -> dict[str, Any]:
    """供 QA/Reviewer 使用的接口、实体与异常索引。"""
    return {
        "api_details": [
            {
                "method": item.get("method"),
                "path": item.get("path"),
                "errors": _items(item.get("errors")),
            }
            for item in _items(backend.get("api_details"))
            if isinstance(item, Mapping)
        ],
        "data_models": [
            item.get("name")
            for item in _items(backend.get("data_models"))
            if isinstance(item, Mapping)
        ],
        "edge_cases": _items(backend.get("edge_cases")),
    }


def frontend_index(frontend: Mapping[str, Any]) -> dict[str, Any]:
    """供 QA/Reviewer 使用的页面、组件与交互索引。"""
    return {
        "pages": [
            {
                "name": item.get("name"),
                "route": item.get("route"),
                "components": _items(item.get("components")),
            }
            for item in _items(frontend.get("pages"))
            if isinstance(item, Mapping)
        ],
        "components": [
            item.get("name")
            for item in _items(frontend.get("components"))
            if isinstance(item, Mapping)
        ],
        "interactions": _items(frontend.get("interactions")),
    }


def qa_index(qa: Mapping[str, Any]) -> dict[str, Any]:
    """给 Reviewer 保留用例覆盖线索而不重复发送完整测试步骤。"""
    return {
        "test_cases": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "expected": item.get("expected"),
            }
            for item in _items(qa.get("test_cases"))
            if isinstance(item, Mapping)
        ],
        "acceptance_criteria": _items(qa.get("acceptance_criteria")),
    }


_ARTIFACT_SECTIONS: dict[str, tuple[str, ...]] = {
    "product": ("market_research", "positioning", "target_users", "requirements", "features", "user_stories"),
    "architect": ("tech_stack", "architecture", "database_schema", "api_design"),
    "backend": ("data_models", "api_details", "business_logic", "edge_cases"),
    "frontend": ("pages", "components", "state_management", "interactions"),
    "qa": ("test_strategy", "test_cases", "acceptance_criteria"),
}

_SECTION_HINTS: dict[str, tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = {
    "product": (
        (("market", "competitor", "swot", "市场", "竞品"), ("market_research",)),
        (("position", "定位"), ("positioning",)),
        (("user", "用户"), ("target_users", "user_stories")),
        (("requirement", "需求", "acceptance", "验收", "privacy", "隐私"), ("requirements",)),
        (("feature", "功能", "priority", "p0", "p1", "p2", "scope", "范围"), ("features",)),
        (("story", "故事"), ("user_stories",)),
    ),
    "architect": (
        (("stack", "technology", "tech", "技术栈"), ("tech_stack",)),
        (("architecture", "sync", "backup", "auth", "permission", "encryption", "offline", "架构", "同步", "备份", "认证", "权限", "加密", "离线", "时区", "search", "索引"), ("architecture",)),
        (("schema", "database", "table", "field", "budget", "transaction", "fts", "数据库", "字段", "表", "预算", "索引", "备注"), ("database_schema",)),
        (("api", "endpoint", "route", "接口", "路径", "授权", "导出", "恢复", "认证", "身份", "会话", "越权", "所有权", "resource ownership"), ("api_design",)),
        (("authentication", "authorization", "identity", "session", "ownership", "security", "认证", "身份", "会话", "授权", "权限", "越权", "所有权", "密钥"), ("database_schema",)),
    ),
    "backend": (
        (("model", "schema", "database", "entity", "数据模型", "数据库", "字段", "表"), ("data_models",)),
        (("api", "endpoint", "request", "response", "接口", "请求", "响应", "路径"), ("api_details",)),
        (("business", "logic", "业务", "流程", "幂等"), ("business_logic",)),
        (("error", "exception", "boundary", "permission", "auth", "错误", "异常", "边界", "权限", "认证"), ("edge_cases",)),
    ),
    "frontend": (
        (("page", "route", "screen", "页面", "路由", "屏幕"), ("pages",)),
        (("component", "组件"), ("components",)),
        (("state", "状态管理"), ("state_management",)),
        (("interaction", "flow", "loading", "error", "offline", "交互", "流程", "加载", "错误", "离线"), ("interactions",)),
    ),
    "qa": (
        (("strategy", "策略"), ("test_strategy",)),
        (("case", "test", "coverage", "用例", "测试", "覆盖"), ("test_cases",)),
        (("acceptance", "requirement", "验收", "需求"), ("acceptance_criteria",)),
    ),
}


def _relevant_sections(task: str, issues: list[Mapping[str, Any]]) -> tuple[str, ...]:
    sections = _ARTIFACT_SECTIONS.get(task, ())
    hints = _SECTION_HINTS.get(task, ())
    text = " ".join(
        str(issue.get(key, ""))
        for issue in issues
        for key in ("problem", "suggestion", "category", "acceptance_criteria")
    ).lower()
    selected = {
        section
        for keywords, mapped_sections in hints
        if any(keyword in text for keyword in keywords)
        for section in mapped_sections
    }
    return tuple(section for section in sections if section in selected) or sections


def revision_context(state: Mapping[str, Any], task: str) -> list[str]:
    """生成三段式修订输入：问题与验收条件、相关旧稿章节、统一修订指令。"""
    if state.get("review_decision") != "revise" or state.get("review_stage") != task:
        return []
    parts: list[str] = []
    issues = state.get("review_issues") or []
    relevant = [
        issue for issue in issues
        if isinstance(issue, Mapping) and issue.get("target") == task
    ]
    if relevant:
        issue_view = [
            {
                "issue_id": issue.get("issue_id"),
                "acceptance_criteria": issue.get("acceptance_criteria") or [],
            }
            for issue in relevant
        ]
        parts.append(
            "1. 本轮必须处理的问题（仅列 issue_id 和验收条件）：\n"
            + json.dumps(issue_view, ensure_ascii=False, separators=(",", ":"))
        )
    previous = _mapping(_mapping(state.get("results")).get(task))
    if previous:
        sections = _relevant_sections(task, relevant)
        old_view = {section: previous[section] for section in sections if section in previous}
        if old_view:
            parts.append(
                "2. 上一版需要修改的章节：\n"
                + json.dumps(old_view, ensure_ascii=False, separators=(",", ":"))
            )
    # 仅在没有结构化 issue 时使用旧版文本反馈，兼容历史 checkpoint。
    if not relevant and state.get("review_feedback"):
        parts.append(f"1. 本轮必须处理的问题（旧版文本反馈）：{state['review_feedback']}")
    parts.append(
        "3. 修订指令：必须逐项回应 issue_id，并在 revision_report 中说明 status、"
        "changed_sections 和 resolution；未涉及部分保持不变，最终仍输出完整结构。"
    )
    return parts
