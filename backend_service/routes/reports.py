"""reports 路由（FR-12 ~ FR-15 / AC-9 ~ AC-12）。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..errors import not_found, validation_error

router = APIRouter()


class CreateReportRequest(BaseModel):
    turn_id: str
    title: str
    overwrite: bool = False


class RenameReportRequest(BaseModel):
    title: str


@router.post("/reports")
async def create_report(body: CreateReportRequest, request: Request):
    """保存报表：服务端按 turn_id 反查已落库 answer（FR-12）；新建 201 / 覆盖更新 200（id 不变）。"""
    svc = request.app.state.ctx.reports
    rep, created = await svc.save(turn_id=body.turn_id, title=body.title, overwrite=body.overwrite)
    if not created:
        return JSONResponse(status_code=200, content={"id": rep["id"], "title": rep["title"], "updated_at": rep.get("updated_at")})
    return JSONResponse(status_code=201, content={"id": rep["id"], "title": rep["title"], "created_at": rep.get("created_at")})


@router.get("/reports")
async def list_reports(request: Request, q: str = "", offset: int = 0, limit: int = 50):
    """名称包含匹配、按创建时间倒序（FR-13）。"""
    ctx = request.app.state.ctx
    if offset < 0 or limit < 1 or limit > ctx.config.page_max:
        raise validation_error(f"分页参数不合法：offset>=0，1<=limit<={ctx.config.page_max}")
    items = await ctx.reports.list(q=q, offset=offset, limit=limit)
    return {"items": items}


@router.get("/reports/{report_id}")
async def get_report(report_id: str, request: Request):
    """直读快照：不调 run_chain、不连 analytics、不出 LLM（FR-13/AC-10）。"""
    return await request.app.state.ctx.reports.get(report_id)


@router.put("/reports/{report_id}")
async def rename_report(report_id: str, body: RenameReportRequest, request: Request):
    """改名：空名 400、同名 409（FR-13）。"""
    return await request.app.state.ctx.reports.rename(report_id, body.title)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(report_id: str, request: Request):
    ok = await request.app.state.ctx.reports.delete(report_id)
    if not ok:
        raise not_found("报表不存在")
    return Response(status_code=204)


@router.post("/reports/{report_id}/refresh")
async def refresh_report(report_id: str, request: Request):
    """刷新：取存的 query_spec 调算法 S5 刷新入口，同步返终态同构体；不落消息、不改快照（FR-14）。"""
    return await request.app.state.ctx.reports.refresh(report_id)


@router.post("/reports/{report_id}/continue-session", status_code=201)
async def continue_session(report_id: str, request: Request):
    """新建会话继承报表口径：inherited_spec=query_spec、title=报表原问题、不插假消息（FR-15）。"""
    return await request.app.state.ctx.reports.continue_session(report_id)
