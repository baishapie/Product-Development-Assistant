"""一致性硬校验：读结构化 ``results``，做确定性检查（非 LLM）。

把"可用代码判定"的问题先定案：API 路径集合差集、P0 功能覆盖、数据模型字段/关系。
既封装为 LangChain 工具，也暴露纯函数，供工作流节点直接调用（确定性更强）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel

Severity = Literal["high", "medium", "low"]


class ConsistencyIssue(BaseModel):
    """单条一致性问题：code + 严重度 + 建议修改目标 + 说明。"""

    code: str
    severity: Severity
    target: str
    detail: str


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _norm(text: Any) -> str:
    """归一化文本：去空白/标点、转小写，用于覆盖匹配。"""
    return re.sub(r"[\s\W_]+", "", str(text).lower())


def _check_api(
    architect: Mapping[str, Any], backend: Mapping[str, Any]
) -> list[ConsistencyIssue]:
    """架构 API 草案 与 后端接口明细 做 (method, path) 集合差集。

    仅当两者产物都存在时比对；否则（如 MVP 无 backend）直接跳过，避免误报。
    """
    if not architect or not backend:
        return []
    declared = {
        (str(item.get("method", "")).upper(), str(item.get("path", "")))
        for item in _as_list(architect.get("api_design"))
        if isinstance(item, Mapping)
    }
    implemented = {
        (str(item.get("method", "")).upper(), str(item.get("path", "")))
        for item in _as_list(backend.get("api_details"))
        if isinstance(item, Mapping)
    }
    declared.discard(("", ""))
    implemented.discard(("", ""))
    issues: list[ConsistencyIssue] = []
    for method, path in sorted(declared - implemented):
        issues.append(
            ConsistencyIssue(
                code="api_missing_in_backend",
                severity="high",
                target="backend",
                detail=f"架构 API {method} {path} 未在后端接口中定义",
            )
        )
    for method, path in sorted(implemented - declared):
        issues.append(
            ConsistencyIssue(
                code="api_not_in_architect",
                severity="medium",
                target="architect",
                detail=f"后端接口 {method} {path} 未在架构草案中登记",
            )
        )
    return issues


def _frontend_text(frontend: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for page in _as_list(frontend.get("pages")):
        if isinstance(page, Mapping):
            parts += [page.get("name"), page.get("description"), *_as_list(page.get("components"))]
    for component in _as_list(frontend.get("components")):
        if isinstance(component, Mapping):
            parts += [component.get("name"), component.get("responsibility")]
    return _norm(" ".join(str(part) for part in parts if part))


def _qa_text(qa: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for case in _as_list(qa.get("test_cases")):
        if isinstance(case, Mapping):
            parts += [case.get("name"), *_as_list(case.get("steps"))]
    return _norm(" ".join(str(part) for part in parts if part))


def _check_p0_coverage(
    product: Mapping[str, Any], frontend: Mapping[str, Any], qa: Mapping[str, Any]
) -> list[ConsistencyIssue]:
    """P0 功能是否被前端页面/组件与 QA 用例覆盖（仅当对应产物存在时判定）。"""
    p0 = [
        str(feature.get("name"))
        for feature in _as_list(product.get("features"))
        if isinstance(feature, Mapping)
        and str(feature.get("priority", "")).upper() == "P0"
        and feature.get("name")
    ]
    if not p0:
        return []
    issues: list[ConsistencyIssue] = []
    fe_text = _frontend_text(frontend) if frontend else ""
    qa_text = _qa_text(qa) if qa else ""
    for name in p0:
        token = _norm(name)
        if frontend and token not in fe_text:
            issues.append(
                ConsistencyIssue(
                    code="p0_not_in_frontend",
                    severity="medium",
                    target="frontend",
                    detail=f"P0 功能「{name}」未见页面/组件覆盖",
                )
            )
        if qa and token not in qa_text:
            issues.append(
                ConsistencyIssue(
                    code="p0_not_tested",
                    severity="medium",
                    target="qa",
                    detail=f"P0 功能「{name}」未见测试用例覆盖",
                )
            )
    return issues


def _check_data_models(backend: Mapping[str, Any]) -> list[ConsistencyIssue]:
    """数据模型基本健全性：命名、字段、重复、关系引用。"""
    models = [m for m in _as_list(backend.get("data_models")) if isinstance(m, Mapping)]
    if not models:
        return []
    names = [str(model.get("name", "")).strip() for model in models]
    known = {name for name in names if name}
    issues: list[ConsistencyIssue] = []

    for name, model in zip(names, models, strict=False):
        fields = [f for f in _as_list(model.get("fields")) if isinstance(f, Mapping)]
        if not name:
            issues.append(
                ConsistencyIssue(
                    code="model_missing_name", severity="medium", target="backend",
                    detail="存在未命名的数据模型",
                )
            )
        if not fields:
            issues.append(
                ConsistencyIssue(
                    code="model_no_fields", severity="medium", target="backend",
                    detail=f"数据模型「{name or '?'}」没有字段定义",
                )
            )
        field_names = [str(f.get("name", "")).strip() for f in fields]
        duplicates = {n for n in field_names if n and field_names.count(n) > 1}
        for dup in sorted(duplicates):
            issues.append(
                ConsistencyIssue(
                    code="duplicate_field", severity="low", target="backend",
                    detail=f"表「{name}」字段「{dup}」重复定义",
                )
            )
        for relation in _as_list(model.get("relations")):
            tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(relation)))
            if tokens and not (tokens & known):
                issues.append(
                    ConsistencyIssue(
                        code="relation_unresolved", severity="low", target="backend",
                        detail=f"表「{name}」的关系「{relation}」未引用已知数据模型",
                    )
                )

    duplicate_models = {n for n in names if n and names.count(n) > 1}
    for dup in sorted(duplicate_models):
        issues.append(
            ConsistencyIssue(
                code="duplicate_model", severity="medium", target="backend",
                detail=f"数据模型「{dup}」重复定义",
            )
        )
    return issues


def check_consistency(results: Mapping[str, Any]) -> list[ConsistencyIssue]:
    """对 ``results`` 做一致性硬校验，返回问题列表（无问题则为空）。"""
    product = _as_dict(results.get("product"))
    architect = _as_dict(results.get("architect"))
    backend = _as_dict(results.get("backend"))
    frontend = _as_dict(results.get("frontend"))
    qa = _as_dict(results.get("qa"))
    return [
        *_check_api(architect, backend),
        *_check_p0_coverage(product, frontend, qa),
        *_check_data_models(backend),
    ]


def format_report(issues: list[ConsistencyIssue]) -> str:
    """把问题列表渲染为可读文本。"""
    if not issues:
        return "一致性检查通过：未发现硬性问题。"
    lines = [f"一致性检查发现 {len(issues)} 个问题："]
    lines += [
        f"- [{issue.severity}] {issue.target}: {issue.detail}（{issue.code}）"
        for issue in issues
    ]
    return "\n".join(lines)


@tool
def consistency_check(results: dict[str, Any]) -> str:
    """对产品/架构/后端/前端/QA 的结构化产物做一致性硬校验，返回 JSON 报告。"""
    issues = check_consistency(results)
    payload = {"ok": not issues, "issues": [issue.model_dump() for issue in issues]}
    return json.dumps(payload, ensure_ascii=False)
