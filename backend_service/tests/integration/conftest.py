"""集成测试夹具（B21~B25 / OQ-2）：需先 `docker compose up -d db`。

- DSN 默认指向 127.0.0.1:5432（compose 仅回环发布）；可用 INTEGRATION_* env 覆盖；
- db 不可达 → 全部集成用例 skip，不影响离线套件（TR-12.1 与 TR-12.2 分离）；
- session 级重建 dw 测试库表 + seed（DROP/CREATE/INSERT 幂等）；
- context 走真实装配：build_context（懒连接）→ startup_sequence（app_user 建表、chatbi_ro 抽 L0）。
"""
import os
import pathlib

import psycopg
import pytest

API_DIR = pathlib.Path(__file__).resolve().parents[2]
FIXTURE_SQL = API_DIR / "tests" / "fixtures" / "dw_test.sql"

ADMIN_DSN = os.environ.get("INTEGRATION_ADMIN_DSN", "postgresql://postgres:postgres@127.0.0.1:5432/chatbi")
APP_URL = os.environ.get("INTEGRATION_APP_DATABASE_URL", "postgresql://app_user:app_password@127.0.0.1:5432/chatbi")
RO_URL = os.environ.get("INTEGRATION_RO_DATABASE_URL", "postgresql://chatbi_ro:chatbi_ro_password@127.0.0.1:5432/chatbi")

INTEGRATION_ENV = {
    "APP_DATABASE_URL": APP_URL,
    "ANALYTICS_DATABASE_URL": RO_URL,
}


def _db_up() -> bool:
    try:
        with psycopg.connect(ADMIN_DSN, connect_timeout=3, autocommit=True):
            return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def dw_ready():
    """db 可达性检查 + dw 测试库表重建（session 级一次）。"""
    if not _db_up():
        pytest.skip("集成 db 不可达：先 `docker compose up -d db`（OQ-2）再跑 -m integration")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE SCHEMA IF NOT EXISTS app")
        conn.execute("CREATE SCHEMA IF NOT EXISTS dw")
        conn.execute(FIXTURE_SQL.read_text(encoding="utf-8"))
        conn.execute("GRANT USAGE ON SCHEMA dw TO chatbi_ro")
        conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA dw TO chatbi_ro")
    yield


@pytest.fixture(scope="session")
def context(dw_ready):
    """真实装配 context：startup_sequence = app 建表 + L0 抽取缓存。"""
    from backend_service.composition import build_context, dispose_context, startup_sequence

    ctx = build_context(env=dict(INTEGRATION_ENV))
    startup_sequence(ctx)
    yield ctx
    dispose_context(ctx)
