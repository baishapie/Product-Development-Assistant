"""文档生成工具：把结构化 Agent 结果渲染为固定模板 Markdown 并落盘。

既实现为 LangChain Tool（``document_generator``），也暴露可直接调用的纯函数
（``render_document`` / ``save_document`` / ``render_and_save``），供工作流文档
节点确定性地使用，不经过 LLM。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

# 章节数据缺失时统一写入的占位说明
_PLACEHOLDER = "> （该章节将在后续迭代补充）"
DEFAULT_FILENAME = "product_document.md"

# 块级 Markdown 行前缀（标题 / 无序列表 / 有序列表 / 引用 / 表格）
_BLOCK_PREFIX = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\|)")


def _unescape_newlines(text: str) -> str:
    """还原被双重转义的换行/制表符（模型常返回字面 ``\\n``）。"""
    return text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


def _format_blocks(text: str) -> str:
    """在块级元素前补空行，保证 Markdown 正确分行（连续列表项不拆开）。"""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        is_block = bool(_BLOCK_PREFIX.match(line))
        prev = out[-1] if out else ""
        prev_is_block = bool(_BLOCK_PREFIX.match(prev))
        if is_block and prev.strip() and not prev_is_block:
            out.append("")
        out.append(line)
    return "\n".join(out)


def _as_dict(value: Any) -> dict[str, Any]:
    """把结果值统一成 dict；非 dict（含 None）返回空 dict，避免下游 KeyError。"""
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    """渲染可能含多行/Markdown 的文本；None 或空白串回退为占位。

    模型可能把换行转义成字面 ``\\n``，这里统一还原，并在块级元素前补空行，
    使架构说明、数据库设计等长文本正确分行。
    """
    raw = "" if value is None else str(value)
    text = _unescape_newlines(raw).strip()
    return _format_blocks(text) if text else _PLACEHOLDER


def _bullet_list(items: Any) -> str:
    """把列表渲染成 Markdown 无序列表；非列表或空列表回退占位。"""
    # 注意：str/bytes 也属于 Sequence，不排除会被逐字符迭代
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
            lines.append(f"- **{name}**：{summary}" if name else f"- {summary}")
        else:
            lines.append(f"- {competitor}")
    return "\n".join(lines)


def _render_swot(swot: Any) -> str:
    """渲染 SWOT 四维度；空维度内部也会回退占位。"""
    if not isinstance(swot, Mapping) or not swot:
        return _PLACEHOLDER
    labels = [
        ("strengths", "优势"),
        ("weaknesses", "劣势"),
        ("opportunities", "机会"),
        ("threats", "威胁"),
    ]
    blocks = [f"**{label}**\n{_bullet_list(swot.get(key))}" for key, label in labels]
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
    return _bullet_list(threats)


def _render_data_models(models: Any) -> str:
    """渲染后端数据模型：每个模型一个小节（字段表 + 关系）。"""
    if not isinstance(models, Sequence) or isinstance(models, (str, bytes)) or not models:
        return _PLACEHOLDER
    blocks: list[str] = []
    for model in models:
        if not isinstance(model, Mapping):
            blocks.append(f"- {model}")
            continue
        name = str(model.get("name", "")).strip() or "（未命名表）"
        lines = [f"**{name}**", "", "| 字段 | 类型 | 可空 | 说明 |", "| --- | --- | --- | --- |"]
        fields = model.get("fields")
        has_field = False
        if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
            for field in fields:
                has_field = True
                if isinstance(field, Mapping):
                    nullable = "是" if field.get("nullable") else "否"
                    lines.append(
                        f"| {field.get('name', '')} | {field.get('type', '')} | "
                        f"{nullable} | {field.get('description', '')} |"
                    )
                else:
                    lines.append(f"| {field} | | | |")
        if not has_field:
            lines.append("| | | | |")
        relations = model.get("relations")
        if (
            isinstance(relations, Sequence)
            and not isinstance(relations, (str, bytes))
            and relations
        ):
            lines += ["", "关系：", _bullet_list(relations)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_api_details(details: Any) -> str:
    """渲染后端接口详细定义（请求/响应/错误）。"""
    if not isinstance(details, Sequence) or isinstance(details, (str, bytes)) or not details:
        return _PLACEHOLDER
    lines = ["| 方法 | 路径 | 请求 | 响应 | 错误 |", "| --- | --- | --- | --- | --- |"]
    for item in details:
        if isinstance(item, Mapping):
            errors = item.get("errors")
            errors_text = ""
            if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes)) and errors:
                errors_text = "；".join(str(e) for e in errors)
            lines.append(
                f"| {item.get('method', '')} | {item.get('path', '')} | "
                f"{item.get('request_schema', '')} | {item.get('response_schema', '')} | "
                f"{errors_text} |"
            )
        else:
            lines.append(f"| | | | | {item} |")
    return "\n".join(lines)


def _render_pages(pages: Any) -> str:
    """渲染前端页面清单：**名称**（路由）：说明；组件：…"""
    if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)) or not pages:
        return _PLACEHOLDER
    lines: list[str] = []
    for page in pages:
        if isinstance(page, Mapping):
            name = str(page.get("name", "")).strip()
            route = str(page.get("route", "")).strip()
            description = str(page.get("description", "")).strip()
            components = page.get("components")
            suffix = ""
            if (
                isinstance(components, Sequence)
                and not isinstance(components, (str, bytes))
                and components
            ):
                suffix = "；组件：" + "、".join(str(c) for c in components)
            lines.append(
                f"- **{name}**（`{route}`）：{description}{suffix}" if name else f"- {description}"
            )
        else:
            lines.append(f"- {page}")
    return "\n".join(lines)


def _render_components(components: Any) -> str:
    """渲染前端组件清单：**名称**：职责（props：…）"""
    if (
        not isinstance(components, Sequence)
        or isinstance(components, (str, bytes))
        or not components
    ):
        return _PLACEHOLDER
    lines: list[str] = []
    for component in components:
        if isinstance(component, Mapping):
            name = str(component.get("name", "")).strip()
            responsibility = str(component.get("responsibility", "")).strip()
            props = component.get("props")
            suffix = ""
            if isinstance(props, Sequence) and not isinstance(props, (str, bytes)) and props:
                suffix = "（props：" + "、".join(str(p) for p in props) + "）"
            lines.append(
                f"- **{name}**：{responsibility}{suffix}" if name else f"- {responsibility}"
            )
        else:
            lines.append(f"- {component}")
    return "\n".join(lines)


def _render_test_cases(cases: Any) -> str:
    """渲染测试用例表格。"""
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)) or not cases:
        return _PLACEHOLDER
    lines = ["| 用例 | 名称 | 类型 | 步骤 | 预期 |", "| --- | --- | --- | --- | --- |"]
    for case in cases:
        if isinstance(case, Mapping):
            steps = case.get("steps")
            steps_text = ""
            if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)) and steps:
                steps_text = "；".join(str(step) for step in steps)
            lines.append(
                f"| {case.get('id', '')} | {case.get('name', '')} | {case.get('type', '')} | "
                f"{steps_text} | {case.get('expected', '')} |"
            )
        else:
            lines.append(f"| | | | | {case} |")
    return "\n".join(lines)


def render_document(state: Mapping[str, Any]) -> str:
    """把状态映射（``idea`` / ``results``）渲染为 Markdown 文档。"""
    idea = str(state.get("idea") or "").strip()
    results = _as_dict(state.get("results"))
    product = _as_dict(results.get("product"))
    architect = _as_dict(results.get("architect"))
    backend = _as_dict(results.get("backend"))
    frontend = _as_dict(results.get("frontend"))
    qa = _as_dict(results.get("qa"))
    market = _as_dict(product.get("market_research"))
    # 数据模型优先用后端产物；否则回退架构师给的文本
    database_section = (
        _render_data_models(backend.get("data_models"))
        if backend.get("data_models")
        else _text(architect.get("database_schema"))
    )

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
        _text(market.get("market_size")),
        "",
        "### 2.2 竞争分析",
        _render_competitors(market.get("competitors")),
        "",
        "### 2.3 SWOT 分析",
        _render_swot(market.get("swot")),
        "",
        "## 3. 用户画像与需求",
        "### 3.1 目标用户",
        _bullet_list(product.get("target_users")),
        "",
        "### 3.2 用户需求",
        _bullet_list(product.get("requirements")),
        "",
        "## 4. 核心功能",
        _render_features(product.get("features")),
        "",
        "## 5. 用户故事",
        _bullet_list(product.get("user_stories")),
        "",
        "## 6. 页面设计",
        _render_pages(frontend.get("pages")),
        "",
        "### 6.1 组件结构",
        _render_components(frontend.get("components")),
        "",
        "### 6.2 交互流程",
        _bullet_list(frontend.get("interactions")),
        "",
        "### 6.3 状态管理",
        _text(frontend.get("state_management")),
        "",
        "## 7. API 设计",
        _render_api(architect.get("api_design")),
        "",
        "## 8. 技术架构",
        "### 8.1 技术选型",
        _bullet_list(architect.get("tech_stack")),
        "",
        "### 8.2 架构说明",
        _text(architect.get("architecture")),
        "",
        "## 9. 数据库设计",
        database_section,
        "",
        "## 10. 测试方案",
        "### 10.1 测试策略",
        _text(qa.get("test_strategy")),
        "",
        "### 10.2 测试用例",
        _render_test_cases(qa.get("test_cases")),
        "",
        "### 10.3 验收标准",
        _bullet_list(qa.get("acceptance_criteria")),
        "",
        "## 11. 风险分析",
        _render_risks(market),
        "",
        "## 12. 后端接口详细定义",
        _render_api_details(backend.get("api_details")),
        "",
        "## 13. 业务逻辑",
        _bullet_list(backend.get("business_logic")),
        "",
        "## 14. 异常与边界",
        _bullet_list(backend.get("edge_cases")),
        "",
    ]
    return "\n".join(parts)


def save_document(content: str, output_dir: str | Path) -> Path:
    """把文档写入 ``output_dir/product_document.md`` 并返回路径。"""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / DEFAULT_FILENAME
    path.write_text(content, encoding="utf-8")
    return path


def render_and_save(state: Mapping[str, Any], output_dir: str | Path) -> Path:
    """渲染并落盘，返回写入路径。"""
    return save_document(render_document(state), output_dir)


@tool
def document_generator(idea: str, results: dict[str, Any], output_dir: str = "./output") -> str:
    """按固定模板渲染产品设计文档并落盘，返回 Markdown 文件路径。"""
    return str(render_and_save({"idea": idea, "results": results}, output_dir))
