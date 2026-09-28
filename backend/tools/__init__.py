"""工具层：LangChain Tools。"""

from typing import Any

from backend.tools.consistency import (
    ConsistencyIssue,
    check_consistency,
    consistency_check,
    format_report,
)
from backend.tools.document_generator import (
    document_generator,
    render_and_save,
    render_document,
    save_document,
)
from backend.tools.search import web_search

def is_tool_enabled(name: str, settings: Any) -> bool:
    """按配置判断某个工具是否启用（决定是否绑定给 Agent）。"""
    if name == "web_search":
        return bool(getattr(settings, "tavily_enabled", False))
    return True


def filter_tools(tools: Any, settings: Any) -> list[Any]:
    """过滤掉当前配置未启用的工具（工具隔离 + 按需绑定）。"""
    return [tool for tool in tools if is_tool_enabled(tool.name, settings)]


__all__ = [
    "ConsistencyIssue",
    "check_consistency",
    "consistency_check",
    "document_generator",
    "filter_tools",
    "format_report",
    "is_tool_enabled",
    "render_and_save",
    "render_document",
    "save_document",
    "web_search",
]
