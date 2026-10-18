"""exemplar / meta_schema_cache 裸 SQL 建表语句（SDD-后端 §4.1 / FR-21）。

含 pgvector 的 vector 列与 hnsw 索引，不用 ORM 映射；由启动序列（EMB_* 齐全时）ensure。
维度写入 vector(N)，N 必须与 EMB_DIM 一致（AC-16 维度校验）。
"""
from __future__ import annotations

import re

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_schema_name(schema: str) -> str:
    if not _IDENT_RE.match(schema or ""):
        raise ValueError(f"非法 schema 名：{schema!r}")
    return schema


def exemplar_ddl(schema: str, dim: int) -> list[str]:
    """exemplar 表 + hnsw 余弦索引；幂等（IF NOT EXISTS）。"""
    schema = validate_schema_name(schema)
    if not isinstance(dim, int) or dim <= 0:
        raise ValueError(f"EMB_DIM 非法：{dim!r}")
    return [
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.exemplar (
            id uuid PRIMARY KEY,
            question text NOT NULL,
            sql text NOT NULL,
            chart_type text,
            tags text[] DEFAULT '{{}}' NOT NULL,
            embedding vector({dim}),
            source text DEFAULT 'seed',
            enabled boolean DEFAULT true,
            created_at timestamptz DEFAULT now()
        )
        """,
        f"""
        CREATE INDEX IF NOT EXISTS uq_hnsw_{schema}_exemplar_embedding
        ON {schema}.exemplar USING hnsw (embedding vector_cosine_ops)
        """,
    ]


def meta_schema_cache_ddl(schema: str) -> list[str]:
    """meta_schema_cache 单行缓存表；幂等。"""
    schema = validate_schema_name(schema)
    return [
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.meta_schema_cache (
            id integer PRIMARY KEY DEFAULT 1,
            blocks jsonb NOT NULL,
            updated_at timestamptz DEFAULT now()
        )
        """
    ]
