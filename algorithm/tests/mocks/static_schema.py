"""StaticSchemaProvider：基于 L0 静态快照的 SchemaProvider 实现（本步默认实现）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...retrieval.schema_extractor import StaticSnapshot, load_static_snapshot
from ...state import SchemaBlock

_FIXTURE_L0 = Path(__file__).resolve().parent.parent / "fixtures" / "l0" / "l0_schema.json"


class StaticSchemaProvider:
    """all_blocks 返回快照六表；enum_candidates 按词命中枚举/层级候选。"""

    def __init__(self, snapshot: StaticSnapshot | None = None):
        self._snapshot = snapshot or load_static_snapshot(_FIXTURE_L0)

    @property
    def meta(self) -> dict[str, Any]:
        """覆盖区间 / 档期日历（S4 数据覆盖判断与档期归一用）。"""
        return self._snapshot.meta

    def all_blocks(self) -> list[SchemaBlock]:
        return list(self._snapshot.blocks)

    def block(self, table: str) -> SchemaBlock | None:
        for b in self._snapshot.blocks:
            if b.table == table:
                return b
        return None

    def enum_candidates(self, term: str) -> list[dict[str, str]]:
        """按词命中枚举值；命中 level1 父级时带出同表 level2 子级（如「美妆」多候选）。"""
        term = (term or "").strip()
        if not term:
            return []
        out: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        def add(table: str, column: str, value: str) -> None:
            key = (table, column, value)
            if key not in seen:
                seen.add(key)
                out.append({"value": value, "label": value, "table": table, "column": column})

        for block in self._snapshot.blocks:
            samples = block.enum_samples
            for column, values in samples.items():
                for v in values:
                    if term in v or v in term:
                        add(block.table, column, v)
            # 层级展开：term 命中 level1 值 → 同表 level2 全部值作为子级候选
            for parent_col, child_col in _level_pairs(samples):
                parents = [v for v in samples.get(parent_col, []) if term in v or v in term]
                if parents:
                    for v in samples.get(child_col, []):
                        add(block.table, child_col, v)
        return out


def _level_pairs(samples: dict[str, list[str]]) -> list[tuple[str, str]]:
    """识别枚举采样中的层级列对（level1_name → level2_name）。"""
    pairs = []
    cols = list(samples.keys())
    for c in cols:
        if "level1" in c:
            for c2 in cols:
                if "level2" in c2:
                    pairs.append((c, c2))
    return pairs
