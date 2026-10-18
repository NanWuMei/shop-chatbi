"""B23 / AC-14：QueryRunner 真库三道兜底——守卫先行、statement_timeout、截断判定。"""
import pytest
from psycopg.rows import dict_row

from algorithm.protocols import QueryTimeoutError

from backend_service.data.engines import AnalyticsEngine
from backend_service.data.query_runner import PgQueryRunner, SqlGuardError

from .conftest import RO_URL

pytestmark = pytest.mark.integration


@pytest.fixture()
def ro_engine(dw_ready):
    return AnalyticsEngine(RO_URL, row_factory=dict_row)


async def test_statement_timeout_raises_query_timeout_error(dw_ready):
    """pg_sleep(3) 超过 800ms statement_timeout → QueryTimeoutError（B23）。"""
    engine = AnalyticsEngine(RO_URL, statement_timeout_ms=800)
    runner = PgQueryRunner(engine, row_limit_max=1000)
    with pytest.raises(QueryTimeoutError):
        await runner.run("SELECT pg_sleep(3)")


async def test_truncation_limit_plus_one(ro_engine):
    runner = PgQueryRunner(ro_engine, row_limit_max=3)
    result = await runner.run("SELECT channel_id, channel_name FROM dw.dim_channel ORDER BY channel_id")
    assert result.truncated is True
    assert result.row_count == 3
    assert result.columns == ["channel_id", "channel_name"]
    assert result.rows[0] == {"channel_id": "CH_A", "channel_name": "渠道A"}


async def test_no_truncation_under_limit(ro_engine):
    runner = PgQueryRunner(ro_engine, row_limit_max=1000)
    result = await runner.run("SELECT channel_id FROM dw.dim_channel ORDER BY channel_id")
    assert result.truncated is False
    assert result.row_count == 4


async def test_guard_rejects_write_before_connect(ro_engine):
    runner = PgQueryRunner(ro_engine, row_limit_max=10)
    with pytest.raises(SqlGuardError):
        await runner.run("DELETE FROM dw.dim_channel")
    assert ro_engine.connect_count == 0  # 守卫拒绝不触库


async def test_guard_allows_cte_select(ro_engine):
    runner = PgQueryRunner(ro_engine, row_limit_max=10)
    result = await runner.run("WITH t AS (SELECT channel_id FROM dw.dim_channel) SELECT * FROM t ORDER BY 1 LIMIT 2")
    assert result.row_count == 2
