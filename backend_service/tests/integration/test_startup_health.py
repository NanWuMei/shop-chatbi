"""B21 / AC-20：启动序列（真实装配）+ /health 端到端 + meta_schema_cache 持久化开关。"""
import pytest

from backend_service.config import load_config
from backend_service.composition import build_context, dispose_context, startup_sequence
from backend_service.main import create_app

from .conftest import INTEGRATION_ENV

pytestmark = pytest.mark.integration


def test_startup_probes(context):
    """启动后三探针：db=ok、llm/emb=unconfigured（不降级 embedding）。"""
    assert context.probes["db"]() == "ok"
    assert context.probes["llm"]() == "unconfigured"
    assert context.probes["embedding"]() == "unconfigured"


def test_app_tables_created_by_startup(context):
    from sqlalchemy import text

    with context.app_engine.connect() as conn:
        for t in ("sessions", "messages", "reports"):
            assert conn.execute(text(f"SELECT to_regclass('app.{t}')")).scalar() is not None


def test_l0_cache_refreshed(context):
    blocks = context.schema_provider.all_blocks()
    assert len(blocks) >= 6


def test_health_endpoint_real_context(context):
    """真实 context 注入 + lifespan：/health 三探针全亮。"""
    from fastapi.testclient import TestClient

    config = load_config(dict(INTEGRATION_ENV))
    with TestClient(create_app(config, context)) as client:  # lifespan 会再跑一次幂等启动序列
        r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["llm"] == "unconfigured"
    assert body["checks"]["embedding"] == "unconfigured"
    assert body["status"] == "degraded"  # LLM 未配置即降级（健康 ≠ 可问数）


async def test_meta_schema_cache_persisted_when_enabled(dw_ready):
    """§4.1：META_SCHEMA_CACHE_ENABLED=true 且 EMB 齐全 → 启动序列把 L0 快照落表。"""
    ctx = build_context(
        env={
            **INTEGRATION_ENV,
            "META_SCHEMA_CACHE_ENABLED": "true",
            "EMB_BASE_URL": "https://emb.example.invalid/v1",
            "EMB_API_KEY": "sk-test",
            "EMB_MODEL": "test-emb",
            "EMB_DIM": "1024",
        }
    )
    try:
        startup_sequence(ctx)  # 建表 + refresh + ensure exemplar/meta_cache（无真实外呼）
        loaded = await ctx.repository.load_schema_cache()
        assert loaded is not None
        assert {"dim_date", "fact_order_item"} <= {b.table for b in loaded}
    finally:
        dispose_context(ctx)
