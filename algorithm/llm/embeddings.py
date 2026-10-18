"""EmbeddingClient OpenAI 兼容实现（SDD §8.2）。

未配置即不可用（available=False），S3 据此降级 lexical；
embed 结果带进程内短缓存（同文本 5 分钟）。
"""
from __future__ import annotations

import time
from typing import Any, Sequence

from ..config import Settings
from ..protocols import EmbeddingUnavailableError

_CACHE_TTL_SECONDS = 300


class OpenAICompatibleEmbeddingClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: Any = None
        self._cache: dict[str, tuple[float, list[float]]] = {}

    @property
    def available(self) -> bool:
        return self._settings.emb_configured

    def _ensure_client(self) -> Any:
        if not self.available:
            raise EmbeddingUnavailableError("Embedding 未配置（缺少 EMB_BASE_URL/EMB_API_KEY/EMB_MODEL）")
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:  # pragma: no cover
                raise EmbeddingUnavailableError(f"openai SDK 不可用: {e}") from e
            self._client = AsyncOpenAI(
                base_url=self._settings.emb_base_url,
                api_key=self._settings.emb_api_key,
                timeout=self._settings.llm_timeout_seconds,
            )
        return self._client

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        now = time.monotonic()
        out: list[list[float] | None] = []
        missing: list[str] = []
        for t in texts:
            hit = self._cache.get(t)
            if hit and now - hit[0] < _CACHE_TTL_SECONDS:
                out.append(hit[1])
            else:
                out.append(None)
                missing.append(t)
        if missing:
            client = self._ensure_client()
            try:
                resp = await client.embeddings.create(model=self._settings.emb_model, input=missing)
            except Exception as e:
                raise EmbeddingUnavailableError(str(e)) from e
            vectors = [d.embedding for d in resp.data]
            if len(vectors) != len(missing):
                raise EmbeddingUnavailableError("embedding 返回数量与请求不一致")
            for t, v in zip(missing, vectors):
                self._cache[t] = (now, v)
            it = iter(vectors)
            out = [next(it) if v is None else v for v in out]
        return [v for v in out if v is not None]
