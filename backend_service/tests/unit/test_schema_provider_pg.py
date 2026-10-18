"""PgSchemaProvider.enum_candidates 离线单测（第3轮实测 bug 回归）。

不连库：直接注入进程内 _blocks 缓存。回归点：列注释命中不得把该列全部取值倒进候选
（实测「美妆」曾返回 14 个含服饰/家电），仅按枚举值命中。
"""
from __future__ import annotations

from algorithm.state import SchemaBlock, SchemaColumn

from backend_service.data.schema_provider_pg import PgSchemaProvider


def _provider() -> PgSchemaProvider:
    provider = PgSchemaProvider(analytics=None)  # type: ignore[arg-type]
    provider._blocks = [
        SchemaBlock(
            table="dim_category",
            columns=[
                SchemaColumn(name="level1_name", comment="一级类目（示例：美妆、服饰）"),
                SchemaColumn(name="level2_name", comment="二级类目"),
            ],
            enum_samples={
                "level1_name": ["服饰", "家电", "食品", "美妆个护"],
                "level2_name": ["女装", "护肤", "彩妆", "美妆工具"],
            },
        )
    ]
    return provider


def test_enum_candidates_value_only_ignores_comment() -> None:
    out = _provider().enum_candidates("美妆")
    values = {c["value"] for c in out}
    # 仅值命中：注释含「美妆」的 level1 列不再整列倒入服饰/家电/食品
    assert values == {"美妆个护", "美妆工具"}
    assert all(c["table"] == "dim_category" for c in out)


def test_enum_candidates_no_value_match_returns_empty() -> None:
    assert _provider().enum_candidates("宇宙飞船") == []
    assert _provider().enum_candidates("") == []
