"""Document Generator tool: render structured agent results to Markdown.

Uses a fixed Chinese template so the MVP deliverable has a stable structure.
The generator is decoupled from the workflow: it reads a plain mapping with
``idea`` and ``results`` keys, so ``tools`` does not import ``workflow``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.tools.base import Tool

# 章节数据缺失时统一写入的占位说明
_PLACEHOLDER = "> （该章节将在后续迭代补充）"


def _as_dict(value: Any) -> dict[str, Any]:
    """把结果值统一成 dict；非 dict（含 None）返回空 dict，避免下游 KeyError。"""
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    """渲染单段文本；None 或空白串回退为占位。"""
    text = str(value).strip() if value is not None else ""
    return text or _PLACEHOLDER


def _bullets(items: Any) -> str:
    """把列表渲染成 Markdown 无序列表；非列表或空列表回退占位。"""
    # 注意：str/bytes 也属于 Sequence，不排除的话会被逐字符迭代，故显式剔除
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)) or not items:
        return _PLACEHOLDER
    return "\n".join(f"- {item}" for item in items)


def _render_competitors(competitors: Any) -> str:
    """渲染竞争分析；元素为 {name, summary} 时输出“**名称**：简介”。"""
    if (
        not isinstance(competitors, Sequence)
        or isinstance(competitors, (str, bytes))
        or not competitors
    ):
        return _PLACEHOLDER
    lines: list[str] = []
    for competitor in competitors:
        if isinstance(competitor, Mapping):
            name = str(competitor.get("name", "")).strip()
            summary = str(competitor.get("summary", "")).strip()
            # 有名称时加粗，否则退化为纯文本行
            lines.append(f"- **{name}**：{summary}" if name else f"- {summary}")
        else:
            lines.append(f"- {competitor}")
    return "\n".join(lines)


def _render_swot(swot: Any) -> str:
    """渲染 SWOT 四维度；每个维度各自渲染为列表，空维度内部也会回退占位。"""
    if not isinstance(swot, Mapping) or not swot:
        return _PLACEHOLDER
    # (数据字段, 中文标题)
    labels = [
        ("strengths", "优势"),
        ("weaknesses", "劣势"),
        ("opportunities", "机会"),
        ("threats", "威胁"),
    ]
    blocks: list[str] = []
    for key, label in labels:
        blocks.append(f"**{label}**\n{_bullets(swot.get(key))}")
    return "\n\n".join(blocks)


def _render_features(features: Any) -> str:
    """渲染功能列表；元素为 {name, priority} 时在名称后追加优先级。"""
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)) or not features:
        return _PLACEHOLDER
    lines: list[str] = []
    for feature in features:
        if isinstance(feature, Mapping):
            name = str(feature.get("name", "")).strip()
            priority = str(feature.get("priority", "")).strip()
            # 优先级为空时不输出括号后缀
            suffix = f"（优先级：{priority}）" if priority else ""
            lines.append(f"- {name}{suffix}")
        else:
            lines.append(f"- {feature}")
    return "\n".join(lines)


def _render_api(api_design: Any) -> str:
    """把 API 列表渲染成 Markdown 表格，元素为 {method, path, description}。"""
    if (
        not isinstance(api_design, Sequence)
        or isinstance(api_design, (str, bytes))
        or not api_design
    ):
        return _PLACEHOLDER
    # 表头 + 分隔行
    lines = ["| 方法 | 路径 | 说明 |", "| --- | --- | --- |"]
    for endpoint in api_design:
        if isinstance(endpoint, Mapping):
            method = endpoint.get("method", "")
            path = endpoint.get("path", "")
            description = endpoint.get("description", "")
            lines.append(f"| {method} | {path} | {description} |")
        else:
            lines.append(f"| | | {endpoint} |")
    return "\n".join(lines)


def _render_risks(research: Mapping[str, Any]) -> str:
    """风险分析取调研结果 SWOT 中的“威胁”；无数据则回退占位。"""
    swot = research.get("swot")
    threats = swot.get("threats") if isinstance(swot, Mapping) else None
    return _bullets(threats)


class DocumentGeneratorTool(Tool):
    """Render the workflow results as a fixed-template Markdown document."""

    name = "document_generator"
    filename = "product_document.md"

    def render(self, state: Mapping[str, Any]) -> str:
        """Return the Markdown document for a state mapping (``idea`` / ``results``)."""
        idea = str(state.get("idea") or "").strip()
        results = _as_dict(state.get("results"))
        research = _as_dict(results.get("research"))
        product = _as_dict(results.get("product"))
        architect = _as_dict(results.get("architect"))

        parts: list[str] = [
            "# 产品设计文档",
            "",
            f"> 产品想法：{idea or '（未提供）'}",
            "> 由 ProductMind AI 自动生成",
            "",
            "## 1. 产品定位",
            _text(product.get("positioning")),
            "",
            "## 2. 市场分析",
            "### 2.1 市场规模",
            _text(research.get("market_size")),
            "",
            "### 2.2 竞争分析",
            _render_competitors(research.get("competitors")),
            "",
            "### 2.3 SWOT 分析",
            _render_swot(research.get("swot")),
            "",
            "## 3. 用户画像与需求",
            "### 3.1 目标用户",
            _bullets(product.get("target_users")),
            "",
            "### 3.2 用户需求",
            _bullets(product.get("requirements")),
            "",
            "## 4. 核心功能",
            _render_features(product.get("features")),
            "",
            "## 5. 用户故事",
            _bullets(product.get("user_stories")),
            "",
            "## 6. 页面设计",
            _PLACEHOLDER,
            "",
            "## 7. API 设计",
            _render_api(architect.get("api_design")),
            "",
            "## 8. 技术架构",
            "### 8.1 技术选型",
            _bullets(architect.get("tech_stack")),
            "",
            "### 8.2 架构说明",
            _text(architect.get("architecture")),
            "",
            "## 9. 数据库设计",
            _text(architect.get("database_schema")),
            "",
            "## 10. 测试方案",
            _PLACEHOLDER,
            "",
            "## 11. 风险分析",
            _render_risks(research),
            "",
        ]
        return "\n".join(parts)

    def save(self, content: str, output_dir: Path) -> Path:
        """Write the document to ``output_dir/product_document.md`` and return the path."""
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self.filename
        path.write_text(content, encoding="utf-8")
        return path

    def run(self, state: Mapping[str, Any], output_dir: Path) -> Path:
        """Render then persist the document; returns the written path."""
        return self.save(self.render(state), output_dir)
