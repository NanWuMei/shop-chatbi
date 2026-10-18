"""真实 L0 SchemaProvider（FR-20 / AC-15）。

经 analytics 只读连接查 pg_catalog，产出算法 retrieval 定义的 SchemaBlock 形状
（表/列/类型/主外键/中文注释/枚举采样），复用算法 parse_schema_rows 解析，不重复实现。

枚举采样（§4.1）：对 dw 内 text 类列做 SELECT DISTINCT ... LIMIT 21，≤20 个取值才收录。
进程内缓存：启动序列 refresh() 一次，S3 all_blocks()/enum_candidates() 全走缓存。
"""
from __future__ import annotations

import threading
from typing import Optional

from psycopg import sql as pgsql

from algorithm.retrieval.schema_extractor import parse_schema_rows
from algorithm.state import SchemaBlock

# 每表/列的目录查询：表注释、列名/类型/注释、主键、外键目标表（parse_schema_rows 兼容形状）
_CATALOG_SQL = """
SELECT
    tbl.relname                              AS table_name,
    obj_description(tbl.oid, 'pg_class')     AS table_comment,
    col.attname                              AS column_name,
    format_type(col.atttypid, col.atttypmod) AS data_type,
    col_description(col.attrelid, col.attnum) AS column_comment,
    EXISTS (
        SELECT 1 FROM pg_constraint con
        WHERE con.conrelid = tbl.oid AND con.contype = 'p' AND col.attnum = ANY (con.conkey)
    )                                        AS is_pk,
    fk.relname                               AS fk
FROM pg_class tbl
JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
JOIN pg_attribute col ON col.attrelid = tbl.oid AND col.attnum > 0 AND NOT col.attisdropped
LEFT JOIN pg_constraint con_f ON con_f.conrelid = tbl.oid AND con_f.contype = 'f' AND col.attnum = ANY (con_f.conkey)
LEFT JOIN pg_class fk ON fk.oid = con_f.confrelid
WHERE ns.nspname = %s AND tbl.relkind = 'r'
ORDER BY tbl.relname, col.attnum
"""

_TEXT_COLUMN_SQL = """
SELECT c.relname AS table_name, a.attname AS column_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
JOIN pg_type t ON t.oid = a.atttypid
WHERE n.nspname = %s AND c.relkind = 'r' AND t.typname IN ('varchar', 'text', 'bpchar')
ORDER BY c.relname, a.attnum
"""


class PgSchemaProvider:
    """实现算法 SchemaProvider 协议：all_blocks() / enum_candidates(term)。"""

    def __init__(self, analytics, *, schema: str = "dw", max_enum_cardinality: int = 20) -> None:
        self._analytics = analytics
        self._schema = schema
        self._max_enum_cardinality = max_enum_cardinality
        self._lock = threading.Lock()
        self._blocks: Optional[list[SchemaBlock]] = None

    def refresh(self) -> list[SchemaBlock]:
        """抽取全量 L0 并写入进程内缓存（启动序列调用，FR-17）。"""
        rows = self._fetch_catalog_rows()
        enum_samples = self._sample_enums()
        blocks = parse_schema_rows(rows, enum_samples=enum_samples)
        with self._lock:
            self._blocks = list(blocks)
        return list(self._blocks or [])

    def all_blocks(self) -> list[SchemaBlock]:
        if self._blocks is None:
            self.refresh()
        return list(self._blocks or [])

    def enum_candidates(self, term: str) -> list[dict[str, str]]:
        """按词命中枚举/层级候选（如「美妆」多候选）：仅按枚举值命中，不看列注释。

        列注释命中会把该列全部取值倒进候选（实测「美妆」返回 14 个含服饰/家电），故禁止。
        """
        t = (term or "").strip().lower()
        if not t:
            return []
        out: list[dict[str, str]] = []
        for b in self.all_blocks():
            for col in b.columns:
                for v in b.enum_samples.get(col.name, []):
                    if t in str(v).lower():
                        out.append({"value": str(v), "label": str(v), "table": b.table, "column": col.name})
        return out

    # ---- 内部 ----
    def _fetch_catalog_rows(self) -> list[dict]:
        with self._analytics.connect() as conn, conn.cursor() as cur:
            cur.execute(_CATALOG_SQL, (self._schema,))
            return list(cur.fetchall())

    def _sample_enums(self) -> dict[str, dict[str, list[str]]]:
        """逐 text 列采样 distinct 值；≤max_enum_cardinality 收录（量小才当枚举）。"""
        with self._analytics.connect() as conn, conn.cursor() as cur:
            cur.execute(_TEXT_COLUMN_SQL, (self._schema,))
            pairs = [(r["table_name"], r["column_name"]) for r in cur.fetchall()]
        samples: dict[str, dict[str, list[str]]] = {}
        for table, column in pairs:
            query = pgsql.SQL("SELECT DISTINCT {} FROM {}.{} WHERE {} IS NOT NULL LIMIT %s").format(
                pgsql.Identifier(column),
                pgsql.Identifier(self._schema),
                pgsql.Identifier(table),
                pgsql.Identifier(column),
            )
            with self._analytics.connect() as conn, conn.cursor() as cur:
                cur.execute(query, (self._max_enum_cardinality + 1,))
                values = [r[column] for r in cur.fetchall()]
            if 0 < len(values) <= self._max_enum_cardinality:
                samples.setdefault(table, {})[column] = [str(v) for v in values]
        return samples
