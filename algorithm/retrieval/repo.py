"""Repository 协议的内存实现（SDD §7.3 切换预留：真实 psycopg+pgvector 实现归后端步）。"""
from __future__ import annotations

import math
from typing import Optional, Sequence

from ..state import Exemplar, SchemaBlock


class InMemoryRepository:
    """exemplars 增/查 + schema cache 读写；向量余弦排序在进程内完成。"""

    def __init__(self) -> None:
        self._exemplars: dict[str, tuple[Exemplar, Optional[list[float]]]] = {}
        self._schema_cache: Optional[list[SchemaBlock]] = None

    async def search_exemplars(
        self,
        *,
        embedding: Optional[list[float]] = None,
        keywords: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> list[Exemplar]:
        scored: list[Exemplar] = []
        if embedding is not None:
            for ex, vec in self._exemplars.values():
                score = _cosine(embedding, vec) if vec else 0.0
                scored.append(ex.model_copy(update={"score": score}))
        else:
            kws = [k for k in (keywords or []) if k]
            for ex, _ in self._exemplars.values():
                text = f"{ex.question} {' '.join(ex.tags)}"
                score = float(sum(1 for k in kws if k in text))
                if score > 0 or not kws:
                    scored.append(ex.model_copy(update={"score": score}))
        scored.sort(key=lambda e: e.score, reverse=True)
        return scored[: max(1, top_k)]

    async def upsert_exemplar(self, exemplar: Exemplar, embedding: Optional[list[float]] = None) -> None:
        self._exemplars[exemplar.id] = (exemplar, list(embedding) if embedding else None)

    async def load_schema_cache(self) -> Optional[list[SchemaBlock]]:
        return list(self._schema_cache) if self._schema_cache is not None else None

    async def save_schema_cache(self, blocks: Sequence[SchemaBlock]) -> None:
        self._schema_cache = list(blocks)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
