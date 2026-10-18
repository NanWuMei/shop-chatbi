"""B25 / AC-16：PgRepository 真库——向量 top1、关键词检索、维度守卫、schema 缓存 roundtrip。"""
import pytest

from sqlalchemy import text

from algorithm.state import Exemplar, SchemaBlock, SchemaColumn

from backend_service.data.engines import build_app_engine
from backend_service.data.pg_exemplar_repo import PgExemplarRepository
from backend_service.storage.ddl import exemplar_ddl, meta_schema_cache_ddl

from .conftest import APP_URL

pytestmark = pytest.mark.integration


@pytest.fixture()
def exemplar_ready(context):
    """建向量表与缓存表（正常由 startup_sequence 在 EMB 齐全时执行；此处显式建）。"""
    with context.app_engine.begin() as conn:
        for stmt in exemplar_ddl("app", 1024):
            conn.execute(text(stmt))
        for stmt in meta_schema_cache_ddl("app"):
            conn.execute(text(stmt))
    return context


@pytest.fixture()
def repo(exemplar_ready):
    return PgExemplarRepository(exemplar_ready.app_engine, schema="app", emb_dim=1024)


def _exemplar(eid: str) -> Exemplar:
    return Exemplar(
        id=eid,
        question=f"618大促期间各渠道GMV（{eid}）",
        sql="SELECT channel_id, SUM(gmv_amount) FROM dw.fact_order GROUP BY 1",
        chart_type="bar",
        tags=["GMV", "渠道"],
        score=0.0,
    )


async def test_upsert_and_vector_top1(repo):
    await repo.upsert_exemplar(_exemplar("it-vec-1"), [0.001] * 1024)
    await repo.upsert_exemplar(_exemplar("it-vec-2"), [0.999] * 1024)
    hits = await repo.search_exemplars(embedding=[0.001] * 1024, top_k=2)
    assert hits, "应命中向量候选"
    assert hits[0].id == "it-vec-1"
    assert hits[0].score > 0.99


async def test_dim_mismatch_rejected(repo):
    with pytest.raises(ValueError):
        await repo.upsert_exemplar(_exemplar("it-bad-dim"), [0.1, 0.2, 0.3])
    with pytest.raises(ValueError):
        await repo.search_exemplars(embedding=[0.1, 0.2, 0.3])


async def test_keyword_search(repo):
    await repo.upsert_exemplar(_exemplar("it-kw-1"), [0.5] * 1024)
    hits = await repo.search_exemplars(keywords=["GMV"], top_k=5)
    assert any("GMV" in h.question or "GMV" in h.tags for h in hits)


async def test_schema_cache_roundtrip(repo, context):
    blocks = context.schema_provider.all_blocks()
    repo.save_schema_cache(blocks)  # 同步写（启动序列直调）
    loaded = await repo.load_schema_cache()
    assert loaded is not None
    assert [b.table for b in loaded] == [b.table for b in blocks]
    first = loaded[0]
    assert isinstance(first, SchemaBlock)
    assert first.columns and isinstance(first.columns[0], SchemaColumn)


def test_app_engine_search_path(dw_ready):
    """APP 引擎连接落在 app schema（懒连接首次使用即验证）。"""
    engine = build_app_engine(APP_URL)
    with engine.connect() as conn:
        v = conn.execute(text("SHOW search_path")).scalar()
        assert "app" in str(v)
