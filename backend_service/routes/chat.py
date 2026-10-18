"""chat 路由（FR-1~FR-8 / AC-2 / AC-3）：三态建 turn、SSE 事件流、取消。

SSE 部署注意（供前端轮次 nginx 配置参考，正式形态同源经 /api/v1 反代）：
- proxy_buffering off;（关缓冲，否则帧被攒住）
- proxy_read_timeout >= 300s;（流式长响应）
- 本响应 content-type=text/event-stream，sse-starlette 每 15s 发注释行心跳。
"""
from __future__ import annotations

import json
from typing import Literal, Optional, Union

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..errors import AppError

router = APIRouter()


class ClarifySelectionModel(BaseModel):
    type: Literal["option", "time_preset", "custom"]
    value: Union[str, dict[str, str]]


class ClarifyConfirmModel(BaseModel):
    clarify_id: str
    selection: ClarifySelectionModel


class RecalibrateModel(BaseModel):
    source_turn_id: str


class CreateTurnRequest(BaseModel):
    session_id: Optional[str] = None
    question: Optional[str] = None
    clarify: Optional[ClarifyConfirmModel] = None
    recalibrate: Optional[RecalibrateModel] = None


@router.post("/chat/turns", status_code=202)
async def create_turn(body: CreateTurnRequest, request: Request):
    """三入参互斥（恰好一种，FR-4）；成功 202 {turn_id, session_id, status:running}。"""
    svc = request.app.state.ctx.conversation
    turn = await svc.create_turn(
        session_id=body.session_id,
        question=body.question,
        clarify=body.clarify.model_dump() if body.clarify is not None else None,
        recalibrate=body.recalibrate.model_dump() if body.recalibrate is not None else None,
    )
    return {"turn_id": turn.turn_id, "session_id": turn.session_id, "status": "running"}


@router.get("/chat/turns/{turn_id}/events")
async def turn_events(turn_id: str, request: Request):
    """SSE 流：零或多个 stage → 恰一终态帧 → done（FR-5）；Last-Event-ID 尽力补帧（B7）。"""
    svc = request.app.state.ctx.conversation
    turn = svc.get_turn(turn_id)
    if turn is None:
        raise AppError("E_TURN_NOT_FOUND", "本轮问数不存在或已过期")
    try:
        last_id = int(request.headers.get("last-event-id", "0") or 0)
    except ValueError:
        last_id = 0

    async def gen():
        cursor = last_id
        while True:
            for f in turn.buffer.after(cursor):
                cursor = f.id
                yield {"id": str(f.id), "event": f.event, "data": json.dumps(f.data, ensure_ascii=False)}
            if turn.buffer.closed or turn.buffer.expired():
                break
            await turn.buffer.wait(timeout=1.0)

    return EventSourceResponse(gen(), ping=15)


@router.post("/chat/turns/{turn_id}/cancel", status_code=202)
async def cancel_turn(turn_id: str, request: Request):
    """取消：202 cancelling → cancelled 帧 + note 消息；重复取消幂等不 500（FR-8/B6）。"""
    svc = request.app.state.ctx.conversation
    svc.cancel(turn_id)  # 不存在 → E_TURN_NOT_FOUND；已终态 → 幂等返回
    return {"turn_id": turn_id, "status": "cancelling"}
