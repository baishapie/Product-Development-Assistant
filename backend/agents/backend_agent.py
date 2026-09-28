"""Backend Agent：数据模型、后端接口详细定义、业务逻辑与异常边界。

依赖 Product 与 Architect 的产物；输出结构化 ``BackendDesign``。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from backend.agents.context import architecture_view, product_view, required_result, revision_context
from backend.agents.factory import AgentSpec, RevisionItem


class FieldDef(BaseModel):
    name: str
    type: str
    nullable: bool = False
    description: str = ""


class DataModel(BaseModel):
    name: str
    fields: list[FieldDef]
    relations: list[str] = []


class EndpointDetail(BaseModel):
    method: str
    path: str
    request_schema: str
    response_schema: str
    errors: list[str] = []


class BackendDesign(BaseModel):
    data_models: list[DataModel]
    api_details: list[EndpointDetail]
    business_logic: list[str]
    edge_cases: list[str]
    revision_report: list[RevisionItem] = Field(default_factory=list)


def _prompt_json(value: Any) -> str:
    """将嵌套结果压成适合 Prompt 的单行 JSON，避免大量 ``\\n``。"""
    cleaned = _prompt_value(value)
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))


def _prompt_value(value: Any) -> Any:
    if isinstance(value, str):
        text = re.sub(r"(?:\\r\\n|\\n|\r\n|\r|\n)\s*-\s*", "；", value)
        return re.sub(r"(?:\\r\\n|\\n|\r\n|\r|\n)", "；", text)
    if isinstance(value, list):
        return [_prompt_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _prompt_value(item) for key, item in value.items()}
    return value


SYSTEM_PROMPT = (
    "你是后端工程师，按已批准的架构 API 逐项细化请求、响应、错误、数据模型和业务逻辑。"
    "保持 method/path 与架构设计一致，覆盖所有已定义端点，不擅自扩展接口；"
    "说明权限、幂等、数据源不可用等相关边界，字段和逻辑以最小完备集为准，避免重复产品背景。"
    "修订后仍返回完整结构。"
    "只返回 JSON 对象，不要输出解释或代码围栏。字段："
    "data_models(数组，元素含 name、"
    "fields[数组，元素含 name/type/nullable/description]、relations[字符串数组])；"
    "api_details(数组，元素含 method、path、request_schema、response_schema、errors[字符串数组])；"
    "business_logic(字符串数组，核心业务逻辑说明)；"
    "edge_cases(字符串数组，异常与边界处理)。"
    "revision_report(修订时逐项回应 issue_id、status、changed_sections、resolution；首轮为空)。"
)


def build_input(state: Mapping[str, Any]) -> str:
    """读取 Product 与 Architect 产物（+ 可选反馈/记忆）。"""
    product = required_result(state, "product")
    architect = required_result(state, "architect")
    revisions = revision_context(state, "backend")
    parts = []
    if not revisions:
        parts.extend(
            [
                "产品定义（后端所需字段）：",
                _prompt_json(product_view(product, "backend")),
                "技术方案（后端所需字段）：",
                _prompt_json(architecture_view(architect, "backend")),
            ]
        )
    else:
        parts.append("基于上一版后端设计进行修订：")
    memory = state.get("memory_context")
    if memory and not revisions:
        parts.insert(0, f"可参考的长期记忆/历史上下文：\n{memory}")
    parts.extend(revisions)
    parts.append("请输出后端详细设计（数据模型、接口详细定义、业务逻辑、异常边界）。")
    return " ".join(_prompt_value(part) for part in parts)


SPEC = AgentSpec(
    task_id="backend",
    system_prompt=SYSTEM_PROMPT,
    output_model=BackendDesign,
    build_input=build_input,
)
