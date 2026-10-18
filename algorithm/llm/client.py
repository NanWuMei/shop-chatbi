"""LLMClient OpenAI 兼容实现（SDD §8.1）。

chat completions + 结构化输出（JSON schema 约束提示 + pydantic 校验）；
节点内失败重试 1 次；客户端工厂延迟构建——无 key 时 import/build 不报错，
仅问数时抛 LLMUnavailableError（映射 E_LLM_UNAVAILABLE）。
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..protocols import LLMUnavailableError
from . import registry

_SCHEMA_HINT = (
    "\n只输出一个 JSON 对象，不要输出任何其他文字。JSON 必须符合此 JSON Schema：\n"
)


class OpenAICompatibleLLMClient:
    """OpenAI 兼容 chat completions 客户端（依赖 openai SDK，随 langchain-openai 安装）。"""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: Any = None  # 延迟构建

    def _ensure_client(self) -> Any:
        if self._client is None:
            if not self._settings.llm_configured:
                raise LLMUnavailableError("LLM 未配置（缺少 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）")
            try:
                from openai import AsyncOpenAI
            except ImportError as e:  # pragma: no cover
                raise LLMUnavailableError(f"openai SDK 不可用: {e}") from e
            self._client = AsyncOpenAI(
                base_url=self._settings.llm_base_url,
                api_key=self._settings.llm_api_key,
                timeout=self._settings.llm_timeout_seconds,
            )
        return self._client

    async def complete(
        self,
        *,
        agent: str,
        tier: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel:
        """单次调用；重试策略在节点内（SDD §8.1 节点内失败重试 1 次）。

        - LLM 未配置/网络/超时 → LLMUnavailableError；
        - 结构化输出不合 schema → ValueError（节点视同失败重试）。
        """
        try:
            return await self._call(agent=agent, tier=tier, messages=messages, schema=schema)
        except LLMUnavailableError:
            raise
        except ValueError:
            raise
        except Exception as e:  # 网络/超时等
            raise LLMUnavailableError(str(e)) from e

    async def _call(
        self,
        *,
        agent: str,
        tier: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel:
        client = self._ensure_client()
        model = registry.resolve_model(self._settings, agent)
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        msgs = list(messages)
        if msgs and msgs[0].get("role") == "system":
            msgs[0] = {"role": "system", "content": msgs[0]["content"] + _SCHEMA_HINT + schema_json}
        else:
            msgs.insert(0, {"role": "system", "content": _SCHEMA_HINT + schema_json})
        resp = await client.chat.completions.create(
            model=model,
            messages=msgs,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        try:
            data = json.loads(content)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"结构化输出不合 schema: {e}") from e


def build_llm_client(settings: Settings) -> OpenAICompatibleLLMClient:
    """客户端工厂：延迟构建，无 key 不报错。"""
    return OpenAICompatibleLLMClient(settings)
