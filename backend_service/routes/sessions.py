"""sessions 路由（FR-11 / AC-8 / B12 / B13）。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response

from ..errors import not_found, validation_error

router = APIRouter()


@router.get("/sessions")
async def list_sessions(request: Request, offset: int = 0, limit: int = 50):
    """按 last_question_at 倒序；分页默认 0/50、上限 200（OQ-5）。"""
    ctx = request.app.state.ctx
    if offset < 0 or limit < 1 or limit > ctx.config.page_max:
        raise validation_error(f"分页参数不合法：offset>=0，1<=limit<={ctx.config.page_max}")
    items = await asyncio.to_thread(ctx.session_repo.list, offset=offset, limit=limit)
    return {"items": items}


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, request: Request):
    """按 seq 完整还原子句（user/clarification 含最终 status/answer/rejection/note）。"""
    ctx = request.app.state.ctx
    session = await asyncio.to_thread(ctx.session_repo.get, session_id)
    if session is None:
        raise not_found("会话不存在")
    msgs = await asyncio.to_thread(ctx.message_repo.list_by_session, session_id)
    return {
        "session": {
            "id": session["id"],
            "title": session["title"],
            "message_count": session["message_count"],
            "last_question_at": session["last_question_at"],
            "created_at": session["created_at"],
        },
        "messages": [
            {"id": m["id"], "seq": m["seq"], "type": m["type"], "payload": m["payload"], "created_at": m["created_at"]}
            for m in msgs
        ],
    }


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request):
    """删除会话（级联删消息）→ 204；不存在 404。"""
    ctx = request.app.state.ctx
    ok = await asyncio.to_thread(ctx.session_repo.delete, session_id)
    if not ok:
        raise not_found("会话不存在")
    return Response(status_code=204)
