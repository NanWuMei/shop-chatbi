"""TR-1.1~1.3 / AC-1：config 默认值与 env 覆盖、错误信封与 §8 映射表。"""
import pytest

from backend_service.config import ApiConfig, load_config
from backend_service.errors import (
    CODE_HTTP,
    AppError,
    clarify_expired,
    internal_error,
    name_conflict,
    not_found,
    report_not_saveable,
    turn_not_found,
    validation_error,
)


# ---- TR-1.3：全 env 缺失默认值不抛错 ----
def test_load_config_defaults_without_env():
    c = load_config({})
    assert c.app_database_url == ApiConfig.app_database_url
    assert c.analytics_database_url == ApiConfig.analytics_database_url
    assert c.query_timeout_seconds == 10
    assert c.row_limit_default == 500
    assert c.row_limit_max == 1000
    # OQ-5 业务常数
    assert c.question_max_length == 500
    assert c.page_default == 50
    assert c.page_max == 200
    assert c.summary_rounds == 5
    assert c.sse_buffer_minutes == 10
    assert c.sse_buffer_seconds == 600
    assert c.app_schema == "app"
    assert c.dw_schema == "dw"
    assert c.meta_schema_cache_enabled is False


# ---- env 覆盖与非法值回退 ----
def test_load_config_overrides_and_invalid_int_fallback():
    c = load_config(
        {
            "APP_DATABASE_URL": "postgresql://u:p@h:5432/db1",
            "ANALYTICS_DATABASE_URL": "postgresql://u:p@h:5432/db2",
            "QUERY_TIMEOUT_SECONDS": "abc",  # 非法 → 默认
            "ROW_LIMIT_MAX": "77",
            "PAGE_MAX": "100",
            "SSE_BUFFER_MINUTES": "3",
            "META_SCHEMA_CACHE_ENABLED": "true",
            "CORS_ORIGINS": " http://a , http://b ,",
            "APP_SCHEMA": "app_test",
            "DW_SCHEMA": "dw_test",
        }
    )
    assert c.app_database_url == "postgresql://u:p@h:5432/db1"
    assert c.analytics_database_url == "postgresql://u:p@h:5432/db2"
    assert c.query_timeout_seconds == 10  # 回退默认
    assert c.row_limit_max == 77
    assert c.page_max == 100
    assert c.sse_buffer_minutes == 3
    assert c.meta_schema_cache_enabled is True
    assert c.cors_origins == ("http://a", "http://b")
    assert c.app_schema == "app_test"
    assert c.dw_schema == "dw_test"


# ---- TR-1.2 / AC-1：§8 错误码 → HTTP 映射表驱动全覆盖 ----
@pytest.mark.parametrize(
    ("code", "http"),
    [
        ("E_VALIDATION", 400),
        ("E_TURN_NOT_FOUND", 404),
        ("E_NOT_FOUND", 404),
        ("E_NAME_CONFLICT", 409),
        ("E_CLARIFY_EXPIRED", 409),
        ("E_REPORT_NOT_SAVEABLE", 409),
        ("E_LLM_UNAVAILABLE", 502),
        ("E_INTERNAL", 500),
    ],
)
def test_code_http_mapping(code, http):
    assert CODE_HTTP[code] == http
    err = AppError(code, "消息")
    assert err.http_status == http


def test_app_error_envelope_with_extra_and_retryable():
    err = name_conflict({"id": "r-1", "title": "同名报表"})
    assert err.envelope() == {
        "error": {"code": "E_NAME_CONFLICT", "message": "已有同名报表", "retryable": False, "existing": {"id": "r-1", "title": "同名报表"}}
    }
    assert AppError("E_LLM_UNAVAILABLE", "x", retryable=True).envelope()["error"]["retryable"] is True


def test_error_helpers_codes():
    assert validation_error("x").code == "E_VALIDATION"
    assert not_found().code == "E_NOT_FOUND"
    assert turn_not_found().code == "E_TURN_NOT_FOUND"
    assert clarify_expired().code == "E_CLARIFY_EXPIRED"
    assert report_not_saveable().code == "E_REPORT_NOT_SAVEABLE"
    assert internal_error().code == "E_INTERNAL"
