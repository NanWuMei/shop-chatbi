"""PgRepository（FR-21 / AC-16）：算法 Repository 协议的 psycopg+pgvector 实现。

- 走 APP 引擎（SQLAlchemy 裸 SQL）：exemplar/meta_schema_cache 都在 app schema，
  写操作只可能走 APP 引擎（NFR-1）；向量以 '[a,b,c]'::vector 字面量传参，不引第三方 pgvector 包；
- 协议三方法：search_exemplars / upsert_exemplar / load_schema_cache；
  meta_schema_cache 的写入由后端启动序列经 save_schema_cache 落库（算法只读）；
- 维度校验：len(embedding) != EMB_DIM 时直接抛 ValueError，不落半截（AC-16）；
- EMB 未配置时后端不实例化本类，检索端由算法侧降级 lexical（FR-21）。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from algorithm.state import Exemplar, SchemaBlock

from ..storage.ddl import validate_schema_name

_IDENT = validate_schema_name  # schema 名静态校验（防注入，来自配置常量）


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class PgExemplarRepository:
    def __init__(self, engine: Engine, *, schema: str = "app", emb_dim: int = 1024) -> None:
        self._engine = engine
        self._schema = _IDENT(schema)
        self._emb_dim = emb_dim

    # ---- 协议：search_exemplars ----
    async def search_exemplars(
        self,
        *,
        embedding: Optional[list[float]] = None,
        keywords: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> list[Exemplar]:
        return await asyncio.to_thread(self._search_sync, embedding=embedding, keywords=keywords, top_k=top_k)

    def _search_sync(
        self,
        *,
        embedding: Optional[list[float]],
        keywords: Optional[list[str]],
        top_k: int,
    ) -> list[Exemplar]:
        table = f"{self._schema}.exemplar"
        with self._engine.connect() as conn:
            if embedding is not None:
                self._check_dim(embedding)
                rows = conn.execute(
                    text(
                        f"SELECT id, question, sql, chart_type, tags, "
                        f"1 - (embedding <=> CAST(:vec AS vector)) AS score "
                        f"FROM {table} WHERE enabled AND embedding IS NOT NULL "
                        f"ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :k"
                    ),
                    {"vec": _vec_literal(embedding), "k": max(1, top_k)},
                ).mappings().all()
            else:
                kws = [k for k in (keywords or []) if k]
                if kws:
                    rows = conn.execute(
                        text(
                            f"SELECT id, question, sql, chart_type, tags FROM {table} "
                            f"WHERE enabled AND ("
                            + " OR ".join(
                                [f"question ILIKE :kw{i}" for i in range(len(kws))]
                                + [
                                    f"EXISTS (SELECT 1 FROM unnest(tags) tg WHERE tg ILIKE :kw{i})"
                                    for i in range(len(kws))
                                ]
                            )
                            + f") LIMIT 200"
                        ),
                        {f"kw{i}": f"%{kw}%" for i, kw in enumerate(kws)},
                    ).mappings().all()
                    # 词命中数计分，与算法内存实现同语义
                    scored = []
                    for r in rows:
                        blob = f"{r['question']} {' '.join(r['tags'] or [])}"
                        s = float(sum(1 for k in kws if k in blob))
                        r = dict(r)
                        r["score"] = s
                        scored.append(r)
                    scored.sort(key=lambda r: r["score"], reverse=True)
                    rows = scored[: max(1, top_k)]
                else:
                    rows = [
                        dict(r)
                        for r in conn.execute(
                            text(f"SELECT id, question, sql, chart_type, tags, 0.0 AS score FROM {table} "
                                 f"WHERE enabled LIMIT :k"),
                            {"k": max(1, top_k)},
                        ).mappings().all()
                    ]
        return [
            Exemplar(
                id=str(r["id"]),
                question=r["question"],
                sql=r["sql"],
                chart_type=r.get("chart_type"),
                tags=list(r.get("tags") or []),
                score=float(r.get("score") or 0.0),
            )
            for r in rows
        ]

    # ---- 协议：upsert_exemplar ----
    async def upsert_exemplar(self, exemplar: Exemplar, embedding: Optional[list[float]] = None) -> None:
        await asyncio.to_thread(self._upsert_sync, exemplar, embedding)

    def _upsert_sync(self, exemplar: Exemplar, embedding: Optional[list[float]]) -> None:
        if embedding is not None:
            self._check_dim(embedding)  # 维度不符直接抛，不落半截（AC-16）
        table = f"{self._schema}.exemplar"
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {table} (id, question, sql, chart_type, tags, embedding, source) "
                    f"VALUES (:id, :question, :sql, :chart_type, :tags, CAST(:emb AS vector), :source) "
                    f"ON CONFLICT (id) DO UPDATE SET question = EXCLUDED.question, sql = EXCLUDED.sql, "
                    f"chart_type = EXCLUDED.chart_type, tags = EXCLUDED.tags, embedding = EXCLUDED.embedding, "
                    f"source = EXCLUDED.source"
                ),
                {
                    "id": str(exemplar.id or uuid.uuid4()),
                    "question": exemplar.question,
                    "sql": exemplar.sql,
                    "chart_type": exemplar.chart_type,
                    "tags": list(exemplar.tags or []),
                    "emb": _vec_literal(embedding) if embedding is not None else None,
                    "source": "seed",
                },
            )

    # ---- 协议：load_schema_cache ----
    async def load_schema_cache(self) -> Optional[list[SchemaBlock]]:
        return await asyncio.to_thread(self._load_cache_sync)

    def _load_cache_sync(self) -> Optional[list[SchemaBlock]]:
        table = f"{self._schema}.meta_schema_cache"
        with self._engine.connect() as conn:
            row = conn.execute(text(f"SELECT blocks FROM {table} WHERE id = 1")).mappings().first()
        if not row:
            return None
        return [SchemaBlock(**b) for b in row["blocks"]]

    def save_schema_cache(self, blocks: list[SchemaBlock]) -> None:
        """启动序列把 L0 抽取结果落 meta_schema_cache（协议只含 load，算法只读缓存，FR-21）。"""
        table = f"{self._schema}.meta_schema_cache"
        payload = [
            {
                "table": b.table,
                "comment": b.comment,
                "columns": [
                    {"name": c.name, "type": c.type, "comment": c.comment, "is_pk": c.is_pk, "fk": c.fk}
                    for c in b.columns
                ],
                "enum_samples": b.enum_samples,
            }
            for b in blocks
        ]
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {table} (id, blocks) VALUES (1, CAST(:blocks AS jsonb)) "
                    f"ON CONFLICT (id) DO UPDATE SET blocks = EXCLUDED.blocks, updated_at = now()"
                ),
                {"blocks": json.dumps(payload, ensure_ascii=False)},
            )

    def _check_dim(self, embedding: list[float]) -> None:
        if len(embedding) != self._emb_dim:
            raise ValueError(f"embedding 维度不符：期望 {self._emb_dim}，实际 {len(embedding)}")
