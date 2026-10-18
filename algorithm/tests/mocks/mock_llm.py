"""Mock LLM：按 agent 名脚本化返回 canned 结构化输出，可连续抛错；记录调用次数/档位。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ...protocols import LLMUnavailableError


class MockLLMClient:
    """scripts: {agent: [item, ...]}；item 为 dict（喂给 schema）或 Exception 实例。"""

    def __init__(self, scripts: dict[str, list[Any]] | None = None):
        self._scripts: dict[str, list[Any]] = {k: list(v) for k, v in (scripts or {}).items()}
        self.calls: list[dict[str, Any]] = []

    def set_script(self, agent: str, items: list[Any]) -> None:
        self._scripts[agent] = list(items)

    async def complete(
        self,
        *,
        agent: str,
        tier: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel:
        self.calls.append({"agent": agent, "tier": tier})
        queue = self._scripts.get(agent) or []
        if not queue:
            raise LLMUnavailableError(f"mock 无 {agent} 脚本")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        try:
            return schema.model_validate(item)
        except Exception as e:
            raise ValueError(f"mock 输出不合 schema: {e}") from e

    def calls_of(self, agent: str) -> int:
        return sum(1 for c in self.calls if c["agent"] == agent)
