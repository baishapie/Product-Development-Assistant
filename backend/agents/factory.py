"""Agent 装配：把 ``AgentSpec`` 封装为 LangChain ``create_agent`` 子图。

每个 Agent 以声明式的 ``AgentSpec`` 描述（提示词 / 结构化输出模型 / 工具 /
输入构造），由 :func:`build_agent` 统一装配，保证契约一致、工具按角色隔离。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from pydantic import BaseModel


class AgentOutputError(Exception):
    """Agent 未返回合法结构化输出时抛出。"""


def get_mapping(source: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """仅当 ``source[key]`` 是映射时返回它，否则返回空映射。"""
    value = source.get(key)
    return value if isinstance(value, Mapping) else {}


def _default_state_update(task_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """默认把结构化结果写入 ``results`` 并标记 ``completed``。"""
    return {"results": {task_id: data}, "completed": [task_id]}


@dataclass(frozen=True)
class AgentSpec:
    """单个 Agent 的声明式契约。"""

    task_id: str
    system_prompt: str
    output_model: type[BaseModel]
    build_input: Callable[[Mapping[str, Any]], str]
    tools: tuple[BaseTool, ...] = ()
    # 覆写状态写入逻辑（如 Supervisor 写 plan 而非 completed）
    to_state_update: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def build_state_update(self, data: dict[str, Any]) -> dict[str, Any]:
        """由结构化结果构造局部状态更新。"""
        if self.to_state_update is not None:
            return self.to_state_update(data)
        return _default_state_update(self.task_id, data)


def build_agent(spec: AgentSpec, model: BaseChatModel) -> Any:
    """按 ``AgentSpec`` 装配 LangChain ``create_agent`` 子图。"""
    return create_agent(
        model,
        tools=list(spec.tools),
        system_prompt=spec.system_prompt,
        response_format=spec.output_model,
        name=f"{spec.task_id}_agent",
    )


def extract_structured(result: Mapping[str, Any], output_model: type[BaseModel]) -> BaseModel:
    """从子图输出中取出并校验结构化响应。"""
    value = result.get("structured_response")
    if value is None:
        raise AgentOutputError(f"{output_model.__name__}: no structured_response in agent output")
    if isinstance(value, output_model):
        return value
    return output_model.model_validate(value)
