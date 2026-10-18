"""L0 库结构抽取解析器（SDD §5/§7.1）。

本步只交付纯解析函数与静态快照加载：
- parse_schema_rows：information_schema/pg_catalog 查询结果行 → SchemaBlock（为后端步真抽取预留）；
- load_static_snapshot：读取 tests/fixtures/l0/l0_schema.json 静态快照。
本模块不写任何真实数据库连接代码。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from ..state import SchemaBlock, SchemaColumn


def parse_schema_rows(
    rows: Iterable[dict[str, Any]],
    *,
    enum_samples: Optional[dict[str, dict[str, list[str]]]] = None,
) -> list[SchemaBlock]:
    """把 information_schema 风格的结果行聚合成 SchemaBlock 列表。

    每行字段约定：table_name / column_name / data_type / column_comment /
    is_pk(bool) / fk(str|None) / table_comment。enum_samples 形如
    {table: {column: [采样值...]}}，由独立的枚举采样查询提供。
    """
    tables: dict[str, SchemaBlock] = {}
    order: list[str] = []
    for r in rows:
        tname = str(r.get("table_name") or r.get("table") or "")
        if not tname:
            continue
        if tname not in tables:
            tables[tname] = SchemaBlock(table=tname, comment=str(r.get("table_comment") or ""))
            order.append(tname)
        block = tables[tname]
        cname = r.get("column_name") or r.get("column")
        if not cname:
            continue
        block.columns.append(
            SchemaColumn(
                name=str(cname),
                type=str(r.get("data_type") or r.get("type") or "text"),
                comment=str(r.get("column_comment") or r.get("comment") or ""),
                is_pk=bool(r.get("is_pk", False)),
                fk=r.get("fk") or None,
            )
        )
    enum_samples = enum_samples or {}
    for tname, block in tables.items():
        block.enum_samples = {k: list(v) for k, v in enum_samples.get(tname, {}).items()}
    return [tables[t] for t in order]


@dataclass
class StaticSnapshot:
    """静态快照加载结果：六表 SchemaBlock + meta（覆盖区间/档期日历）。"""

    blocks: list[SchemaBlock] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def load_static_snapshot(path: str | Path) -> StaticSnapshot:
    """读取 L0 静态快照 JSON（表结构 + meta.coverage / meta.promo_calendar）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    blocks = [
        SchemaBlock(
            table=t["table"],
            comment=t.get("comment", ""),
            columns=[
                SchemaColumn(
                    name=c["name"],
                    type=c.get("type", "text"),
                    comment=c.get("comment", ""),
                    is_pk=bool(c.get("is_pk", False)),
                    fk=c.get("fk") or None,
                )
                for c in t.get("columns", [])
            ],
            enum_samples={k: list(v) for k, v in t.get("enum_samples", {}).items()},
        )
        for t in data.get("tables", [])
    ]
    return StaticSnapshot(blocks=blocks, meta=dict(data.get("meta", {})))
