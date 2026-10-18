"""FastAPI 应用工厂（FR-1）：/api/v1 挂载、统一错误信封、开发态 CORS、lifespan（FR-17）。

uvicorn 入口：backend_service.main:app（模块级 app 实例，单 worker）。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import ApiConfig, load_config
from .errors import AppError

_BASE = "/api/v1"


def create_app(config: Optional[ApiConfig] = None, context=None) -> FastAPI:
    """应用工厂。context 为装配好的 AppContext（离线测试注入替身；缺省走 composition.build_context）。"""
    config = config or load_config()
    if context is None:
        from .composition import build_context

        context = build_context(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # FR-17：startup 钩子（build_context 注入 → create_all → L0 抽取 →（EMB 齐全）ensure exemplar+hnsw）；
        # 离线测试注入的替身 context 无 startup/shutdown 属性 → 跳过生命周期。
        startup = getattr(context, "startup", None)
        shutdown = getattr(context, "shutdown", None)
        if startup is not None:
            await asyncio.to_thread(startup)
        try:
            yield
        finally:
            if shutdown is not None:
                await asyncio.to_thread(shutdown)

    app = FastAPI(title="ChatBI API", version="0.2.0", lifespan=lifespan)
    app.state.ctx = context

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),  # 仅本地开发态（FR-1）
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    from .routes import chat, health, reports, sessions

    app.include_router(health.router, prefix=_BASE)
    app.include_router(chat.router, prefix=_BASE)
    app.include_router(sessions.router, prefix=_BASE)
    app.include_router(reports.router, prefix=_BASE)

    _install_error_handlers(app)
    return app


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.http_status, content=exc.envelope())

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "E_VALIDATION", "message": "请求参数不合法", "retryable": False}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "E_NOT_FOUND", "message": "资源不存在", "retryable": False}},
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "E_INTERNAL", "message": "请求处理失败", "retryable": False}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "E_INTERNAL", "message": "服务内部处理失败，请稍后重试", "retryable": False}},
        )


app = create_app()
