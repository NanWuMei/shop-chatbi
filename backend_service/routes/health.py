"""health 路由（FR-16 / AC-17 / B20）。

db=ok/error；llm=ok/unconfigured/error；embedding 同。
聚合：llm unconfigured|error 或任一 error → degraded；embedding unconfigured 不降级。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

router = APIRouter()


def aggregate_status(checks: dict[str, str]) -> str:
    """FR-16 聚合规则（纯函数，表驱动测试用）。"""
    if checks.get("db") == "error":
        return "degraded"
    if checks.get("llm") in ("error", "unconfigured"):
        return "degraded"
    if checks.get("embedding") == "error":
        return "degraded"
    return "ok"


@router.get("/health")
async def health(request: Request):
    probes = request.app.state.ctx.probes
    checks: dict[str, str] = {}
    for name in ("db", "llm", "embedding"):
        try:
            checks[name] = await asyncio.wait_for(asyncio.to_thread(probes[name]), timeout=5.0)
        except Exception:  # noqa: BLE001 探针失败不拖死请求
            checks[name] = "error"
    return {"status": aggregate_status(checks), "checks": checks}
