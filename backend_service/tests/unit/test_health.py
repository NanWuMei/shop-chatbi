"""TR-10.1：/health 探针聚合表驱动 + 端点行为（失败不拖死请求）。"""
import pytest

from backend_service.routes.health import aggregate_status

from ..conftest import make_app_ctx, make_client, make_services


@pytest.mark.parametrize(
    ("checks", "expected"),
    [
        ({"db": "ok", "llm": "ok", "embedding": "ok"}, "ok"),
        ({"db": "error", "llm": "ok", "embedding": "ok"}, "degraded"),
        ({"db": "ok", "llm": "unconfigured", "embedding": "ok"}, "degraded"),
        ({"db": "ok", "llm": "error", "embedding": "ok"}, "degraded"),
        ({"db": "ok", "llm": "ok", "embedding": "error"}, "degraded"),
        # embedding unconfigured 不降级（可选增强）
        ({"db": "ok", "llm": "ok", "embedding": "unconfigured"}, "ok"),
    ],
)
def test_aggregate_status_table(checks, expected):
    assert aggregate_status(checks) == expected


def test_health_endpoint_default_probes():
    """默认离线探针：db ok、llm/emb unconfigured → degraded。"""
    svc = make_services()
    with make_client(svc) as c:
        r = c.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
    assert body == {"status": "degraded", "checks": {"db": "ok", "llm": "unconfigured", "embedding": "unconfigured"}}


def test_health_endpoint_all_ok():
    svc = make_services()
    ctx = make_app_ctx(svc, probes={"db": lambda: "ok", "llm": lambda: "ok", "embedding": lambda: "unconfigured"})
    from backend_service.config import load_config
    from backend_service.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(load_config({}), ctx)) as c:
        r = c.get("/api/v1/health")
    assert r.json()["status"] == "ok"


def test_health_endpoint_probe_exception_isolated():
    """探针抛异常 → 该项 error，不拖死请求（504→500 不出现）。"""
    def boom():
        raise RuntimeError("db down")

    svc = make_services()
    ctx = make_app_ctx(svc, probes={"db": boom, "llm": lambda: "ok", "embedding": lambda: "ok"})
    from backend_service.config import load_config
    from backend_service.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(load_config({}), ctx)) as c:
        r = c.get("/api/v1/health")
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["db"] == "error"
    assert body["checks"]["llm"] == "ok"


def test_unknown_route_envelope_404():
    """TR-1.1：未知路径 → 统一信封 404 E_NOT_FOUND（§8）。"""
    svc = make_services()
    with make_client(svc) as c:
        r = c.get("/api/v1/definitely-not-a-route")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "E_NOT_FOUND"
