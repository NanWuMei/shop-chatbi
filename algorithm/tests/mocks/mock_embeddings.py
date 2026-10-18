"""Mock Embedding：确定性伪向量，可切换抛错/不可用；记录调用。"""
from __future__ import annotations

import hashlib
from typing import Sequence

from ...protocols import EmbeddingUnavailableError


class MockEmbeddingClient:
    def __init__(self, *, available: bool = True, fail: bool = False, dim: int = 8):
        self._available = available
        self._fail = fail
        self._dim = dim
        self.calls: list[list[str]] = []

    @property
    def available(self) -> bool:
        return self._available

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if not self._available:
            raise EmbeddingUnavailableError("mock embedding 未配置")
        if self._fail:
            raise EmbeddingUnavailableError("mock embedding 调用失败")
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self._dim)]
