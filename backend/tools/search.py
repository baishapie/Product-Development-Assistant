"""联网搜索工具（Tavily）。

- 仅当配置 ``TAVILY_API_KEY`` 时可用；未配置或出错时返回**可读提示**而不抛异常，
  让 Agent 能继续（工具失败不阻断流程）。
- ``tavily`` SDK 延迟导入，未安装/未启用不影响启动。
- 不记录查询全文与密钥，只记录长度/耗时/失败原因。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.tools import tool

from backend.config import get_settings

logger = logging.getLogger(__name__)


def _api_key() -> str:
    return get_settings().tavily_api_key


def _make_client() -> Any:
    """构建 Tavily 客户端（延迟导入，便于测试替换）。"""
    from tavily import TavilyClient

    return TavilyClient(api_key=_api_key())


def _format(results: Any) -> str:
    """把 Tavily 返回整理为稳定 JSON：answer + results[title,url,content]。"""
    data = results if isinstance(results, dict) else {}
    items = data.get("results") or []
    formatted = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        }
        for item in items
        if isinstance(item, dict)
    ]
    answer = str(data.get("answer") or "").strip()
    return json.dumps({"answer": answer, "results": formatted}, ensure_ascii=False)


@tool
def web_search(query: str) -> str:
    """联网搜索（Tavily）：输入查询，返回最相关网页的标题/链接/内容摘要。"""
    if not _api_key():
        return "搜索不可用：未配置 TAVILY_API_KEY。"

    started = time.perf_counter()
    logger.info("web_search start", extra={"query_len": len(query)})
    try:
        client = _make_client()
        results = client.search(
            query=query,
            max_results=get_settings().tavily_max_results,
            include_answer=True,
        )
    except Exception as exc:  # noqa: BLE001 - 搜索失败不阻断流程
        logger.warning("web_search failed", extra={"error": str(exc)})
        return f"搜索失败：{exc}"

    logger.info(
        "web_search done",
        extra={"latency_ms": round((time.perf_counter() - started) * 1000, 1)},
    )
    return _format(results)
