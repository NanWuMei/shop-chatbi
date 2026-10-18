"""api 配置（SDD-后端 §7.3）：全部 env 缺失时给默认值、不抛错（FR-2）。

业务常数默认（OQ-5 已拍板）：问题 500 字 / 分页默认 50 上限 200 / SSE 缓冲 10min / 口径摘要 N=5。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ApiConfig:
    # 双数据库连接串（§7.3）
    app_database_url: str = "postgresql://app_user:app_password@localhost:5432/chatbi"
    analytics_database_url: str = "postgresql://chatbi_ro:chatbi_ro_password@localhost:5432/chatbi"
    # 执行层兜底（§7.3 / FR-19）
    query_timeout_seconds: int = 10
    row_limit_default: int = 500
    row_limit_max: int = 1000
    # 业务常数（OQ-5）
    question_max_length: int = 500
    page_default: int = 50
    page_max: int = 200
    summary_rounds: int = 5
    sse_buffer_minutes: int = 10
    # schema 名（集成测试可用独立 schema；模型不写死前缀，靠连接 search_path）
    app_schema: str = "app"
    dw_schema: str = "dw"
    # meta_schema_cache 落表开关（§4.1：默认进程内缓存即可，建表受开关控制）
    meta_schema_cache_enabled: bool = False
    # 仅本地开发态开 CORS（FR-1；同源经 nginx 是正式形态）
    cors_origins: tuple[str, ...] = ("http://localhost:8080", "http://localhost:5173")

    @property
    def sse_buffer_seconds(self) -> int:
        return self.sse_buffer_minutes * 60


def _get(env: dict, name: str, default: Optional[str] = None) -> Optional[str]:
    v = env.get(name)
    return v if v not in (None, "") else default


def _get_int(env: dict, name: str, default: int) -> int:
    v = env.get(name)
    if v in (None, ""):
        return default
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def load_config(env: Optional[dict] = None) -> ApiConfig:
    """读 §7.3 全部 env；缺失值给默认（TR-1.3）。env=None 时读 os.environ。"""
    env = dict(os.environ if env is None else env)
    cors = env.get("CORS_ORIGINS")
    origins = [o.strip() for o in cors.split(",")] if cors else []
    return ApiConfig(
        app_database_url=_get(env, "APP_DATABASE_URL", ApiConfig.app_database_url),  # type: ignore[arg-type]
        analytics_database_url=_get(env, "ANALYTICS_DATABASE_URL", ApiConfig.analytics_database_url),  # type: ignore[arg-type]
        query_timeout_seconds=_get_int(env, "QUERY_TIMEOUT_SECONDS", 10),
        row_limit_default=_get_int(env, "ROW_LIMIT_DEFAULT", 500),
        row_limit_max=_get_int(env, "ROW_LIMIT_MAX", 1000),
        question_max_length=_get_int(env, "QUESTION_MAX_LENGTH", 500),
        page_default=_get_int(env, "PAGE_DEFAULT", 50),
        page_max=_get_int(env, "PAGE_MAX", 200),
        summary_rounds=_get_int(env, "SUMMARY_ROUNDS", 5),
        sse_buffer_minutes=_get_int(env, "SSE_BUFFER_MINUTES", 10),
        app_schema=_get(env, "APP_SCHEMA", "app"),  # type: ignore[arg-type]
        dw_schema=_get(env, "DW_SCHEMA", "dw"),  # type: ignore[arg-type]
        meta_schema_cache_enabled=_get(env, "META_SCHEMA_CACHE_ENABLED", "false").lower() in ("1", "true", "yes"),  # type: ignore[union-attr]
        cors_origins=tuple(o for o in origins if o) or ApiConfig.cors_origins,  # type: ignore[arg-type]
    )
