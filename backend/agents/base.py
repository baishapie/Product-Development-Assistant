"""Agent 基类：组装提示词 -> 调用 LLM -> 校验结构化输出 -> 写入状态。

Agent 只依赖 ``LLMClient`` 协议与普通的状态映射，不直接依赖 ``workflow``。
真正的 ``AgentState`` 定义在 ``workflow/state.py``（Step 6），这样保持了
``workflow -> agents -> (llm, tools, config)`` 的依赖方向。
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from backend.llm.base import LLMClient

logger = logging.getLogger(__name__)

# 校验失败时追加的修复提示，要求模型只返回合法 JSON
_REPAIR_PROMPT = (
    "你上一次的输出无法通过校验：{error}\n"
    "请只返回一个合法的 JSON 对象，不要包含解释或 Markdown 代码围栏。"
)


class OutputValidationError(Exception):
    """Agent 输出无法解析为目标 Pydantic 模型时抛出。"""


def get_mapping(source: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """仅当 ``source[key]`` 是映射时返回它，否则返回空映射。"""
    value = source.get(key)
    return value if isinstance(value, Mapping) else {}


def parse_json_object(text: str) -> Any:
    """从模型原始文本中解析 JSON 对象，容忍代码围栏与前后夹带的文字。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉 ```/```json 围栏
        cleaned = cleaned[3:]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 兜底：截取第一个 { 到最后一个 } 之间的内容
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


class BaseAgent(ABC):
    """所有结构化输出 Agent 的公共行为。"""

    task_id: ClassVar[str]
    system_prompt: ClassVar[str]
    output_model: ClassVar[type[BaseModel]]

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @abstractmethod
    def build_user_prompt(self, state: Mapping[str, Any]) -> str:
        """根据当前工作流状态构造用户提示词。"""

    def run(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """执行一次 Agent，并返回局部状态更新。"""
        started = time.perf_counter()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.build_user_prompt(state)},
        ]
        raw = self._llm.chat(messages, response_format={"type": "json_object"})
        result = self._parse_with_repair(raw, messages)
        logger.info(
            "agent completed",
            extra={
                "agent": self.task_id,
                "task": self.task_id,
                "status": "ok",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        update = self.build_state_update(result.model_dump())
        # 重置确认相关字段，使重跑（收到 revise 后）能再次进入确认闸门
        update["current_task"] = self.task_id
        update["review_decision"] = None
        update["review_feedback"] = None
        return update

    def build_state_update(self, data: dict[str, Any]) -> dict[str, Any]:
        """由子类扩展：默认把结构化结果写入 ``results`` 并标记 ``completed``。

        Supervisor 会覆盖此方法以额外写入 ``plan``。
        """
        return {
            "results": {self.task_id: data},
            "completed": [self.task_id],
        }

    def _parse_with_repair(self, raw: str, messages: list[dict[str, str]]) -> BaseModel:
        """先校验一次；失败则请模型修复后再校验一次。"""
        try:
            return self._validate(raw)
        except OutputValidationError as error:
            logger.warning(
                "agent output invalid, attempting repair",
                extra={"agent": self.task_id, "error": str(error)},
            )
            repair_messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _REPAIR_PROMPT.format(error=error)},
            ]
            repaired = self._llm.chat(repair_messages, response_format={"type": "json_object"})
            return self._validate(repaired)

    def _validate(self, raw: str) -> BaseModel:
        """解析 JSON 并用输出模型校验，任何问题统一抛 ``OutputValidationError``。"""
        try:
            payload = parse_json_object(raw)
        except json.JSONDecodeError as exc:
            raise OutputValidationError(f"invalid JSON: {exc}") from exc
        try:
            return self.output_model.model_validate(payload)
        except ValidationError as exc:
            raise OutputValidationError(str(exc)) from exc
