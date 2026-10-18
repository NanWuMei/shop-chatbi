"""B24 / AC-15：L0 真实抽取——pg_catalog 六表、中文注释、主键/外键、枚举采样与候选检索。"""
import pytest

pytestmark = pytest.mark.integration


def test_blocks_cover_six_tables(context):
    blocks = {b.table: b for b in context.schema_provider.all_blocks()}
    assert {"dim_date", "dim_channel", "dim_category", "fact_order", "fact_order_item", "fact_traffic_daily"} <= set(blocks)


def test_comments_pk_fk(context):
    blocks = {b.table: b for b in context.schema_provider.all_blocks()}
    ch = blocks["dim_channel"]
    assert ch.comment != ""  # 中文表注释
    assert any(c.comment for c in ch.columns)  # 中文列注释
    by_name = {c.name: c for c in ch.columns}
    assert by_name["channel_id"].is_pk is True
    assert by_name["channel_name"].comment != ""
    order = {c.name: c for c in blocks["fact_order"].columns}
    assert order["channel_id"].fk == "dim_channel"
    assert order["order_date"].fk == "dim_date"
    item = {c.name: c for c in blocks["fact_order_item"].columns}
    assert item["order_id"].is_pk is True and item["item_id"].is_pk is True
    assert item["category_id"].fk == "dim_category"


def test_enum_samples_from_text_columns(context):
    blocks = {b.table: b for b in context.schema_provider.all_blocks()}
    assert set(blocks["dim_date"].enum_samples["promo_phase"]) == {"预热", "正式", "返场", "日常"}
    assert {"彩妆", "护肤", "美妆工具"} <= set(blocks["dim_category"].enum_samples["level2_name"])
    assert {"渠道A", "渠道B", "渠道C", "渠道D"} <= set(blocks["dim_channel"].enum_samples["channel_name"])
    assert {"已支付", "已退款"} <= set(blocks["fact_order"].enum_samples["pay_status"])


def test_enum_candidates_meizhuang(context):
    """§3.1：检索「美妆」→ 美妆个护 + 美妆工具等候选（值或列注释命中）。"""
    cands = context.schema_provider.enum_candidates("美妆")
    assert cands, "「美妆」应命中枚举候选"
    values = {c["value"] for c in cands}
    assert "美妆个护" in values and "美妆工具" in values
    assert all(c["table"] == "dim_category" for c in cands)
    # 空词 / 无命中 → 空
    assert context.schema_provider.enum_candidates("") == []
    assert context.schema_provider.enum_candidates("不存在的词xyz") == []
