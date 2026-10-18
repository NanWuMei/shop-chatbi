"""B22 / AC-13：最小权限物理隔离——chatbi_ro 只读 dw、app_user 写 app 且摸不到 dw。"""
import psycopg
import pytest
from psycopg.rows import dict_row

from .conftest import APP_URL, RO_URL

pytestmark = pytest.mark.integration


@pytest.fixture()
def ro_conn(dw_ready):
    with psycopg.connect(RO_URL, autocommit=True, row_factory=dict_row) as conn:
        yield conn


@pytest.fixture()
def app_conn(dw_ready, context):  # context：确保 app 表已由 startup_sequence 建好
    with psycopg.connect(APP_URL, autocommit=True, row_factory=dict_row) as conn:
        yield conn


def test_chatbi_ro_can_read_dw(ro_conn):
    cur = ro_conn.execute("SELECT count(*) AS n FROM dw.dim_channel")
    assert cur.fetchone()["n"] == 4


def test_chatbi_ro_cannot_insert_dw(ro_conn):
    with pytest.raises(psycopg.errors.Error):
        ro_conn.execute("INSERT INTO dw.dim_channel VALUES ('CH_X', '渠道X', '测试')")


def test_chatbi_ro_cannot_update_delete_dw(ro_conn):
    with pytest.raises(psycopg.errors.Error):
        ro_conn.execute("UPDATE dw.dim_channel SET channel_name = '改' WHERE channel_id = 'CH_A'")
    with pytest.raises(psycopg.errors.Error):
        ro_conn.execute("DELETE FROM dw.dim_channel WHERE channel_id = 'CH_A'")


def test_app_user_can_write_app(app_conn):
    cur = app_conn.execute(
        "INSERT INTO app.sessions (title, owner_id, message_count) VALUES ('权限测试', 'default', 0) RETURNING id"
    )
    sid = cur.fetchone()["id"]
    app_conn.execute("DELETE FROM app.sessions WHERE id = %s", (sid,))


def test_app_user_cannot_read_dw(app_conn):
    with pytest.raises(psycopg.errors.Error):
        app_conn.execute("SELECT * FROM dw.dim_channel").fetchone()


def test_analytics_connection_guards(dw_ready):
    """AnalyticsEngine 连接级三道兜底：search_path / statement_timeout / read-only（§5.1）。"""
    from backend_service.data.engines import AnalyticsEngine

    engine = AnalyticsEngine(RO_URL, statement_timeout_ms=10000)
    with engine.connect() as conn:
        cur = conn.execute("SHOW search_path")
        assert cur.fetchone()["search_path"].startswith("dw")
        assert conn.execute("SHOW default_transaction_read_only").fetchone()["default_transaction_read_only"] == "on"
        assert conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"] in ("10s", "10000ms")
