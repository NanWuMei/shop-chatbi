"""conversation_service（FR-3 ~ FR-10 / AC-2 ~ AC-7）：唯一调 run_chain 的编排层。

- 建 turn：三入参互斥校验；clarify 票据校验与 selection 拼接；recalibrate 取源 turn 的
  internal.query_spec 走算法 S4 recalibrate 入口；
- 调 run_chain：Deps 注入、conversation_summary（最近 N 轮 answer 口径 + 继承口径）、
  thread_id/checkpointer（进程内内存）、on_event → stage 帧映射（同段去重）；
- 终态处理：ChainResult → 终态帧与持久化消息（payload 切片 + internal 三键）；
- 取消协作：task.cancel + Runner 执行前 cancel 标志兜底（statement_timeout 承接在途查询）。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from algorithm.state import ChainResult, Meta, Trace

from ..config import ApiConfig
from ..errors import AppError, clarify_expired, not_found, turn_not_found, validation_error
from . import mappers
from .event_buffer import EventBuffer

logger = logging.getLogger("backend_service.conversation")


@dataclass
class ClarifyTicket:
    """澄清票据：进程内注册（NFR-4 单进程假设），状态 pending/confirmed/cancelled。"""

    clarify_id: str
    thread_id: str
    session_id: str
    payload: dict  # 澄清卡镜像
    question: str  # 发起本轮的用户原问题（拼接 clarified_question 用）
    status: str = "pending"


@dataclass
class Turn:
    turn_id: str
    session_id: str
    question: str
    thread_id: str
    status: str = "running"  # running | cancelling | done | cancelled
    buffer: EventBuffer = field(default=None)  # type: ignore[assignment]
    task: Optional[asyncio.Task] = None
    cancel_requested: bool = False  # cancel() 先置标志；任务未启动时靠它自行收尾
    started: bool = False


class TicketRegistry:
    def __init__(self) -> None:
        self._tickets: dict[str, ClarifyTicket] = {}

    def add(self, ticket: ClarifyTicket) -> None:
        self._tickets[ticket.clarify_id] = ticket

    def get(self, clarify_id: str) -> Optional[ClarifyTicket]:
        return self._tickets.get(clarify_id)

    def set_status(self, clarify_id: str, status: str) -> None:
        t = self._tickets.get(clarify_id)
        if t is not None:
            t.status = status

    def pending_in_session(self, session_id: str) -> list[ClarifyTicket]:
        return [t for t in self._tickets.values() if t.session_id == session_id and t.status == "pending"]


class ConversationService:
    def __init__(
        self,
        *,
        config: ApiConfig,
        chain_runner: Callable[..., Any],
        deps: Any,
        checkpointer: Any,
        session_repo: Any,
        message_repo: Any,
        clock: Optional[Callable[[], float]] = None,
        ticket_registry: Optional[TicketRegistry] = None,
    ) -> None:
        self._config = config
        self._chain_runner = chain_runner
        self._deps = deps
        self._checkpointer = checkpointer
        self._session_repo = session_repo
        self._message_repo = message_repo
        self._clock = clock or time.monotonic
        self._tickets = ticket_registry or TicketRegistry()
        self._turns: dict[str, Turn] = {}

    # ---------- 建 turn（FR-3/FR-4） ----------
    async def create_turn(
        self,
        *,
        session_id: Optional[str] = None,
        question: Optional[str] = None,
        clarify: Optional[dict] = None,
        recalibrate: Optional[dict] = None,
    ) -> Turn:
        modes = [question is not None, clarify is not None, recalibrate is not None]
        if sum(modes) != 1:
            raise validation_error("question / clarify / recalibrate 三种入参必须恰好传一种")
        self._prune_expired_turns()

        # --- 会话解析 ---
        if clarify is not None or recalibrate is not None:
            if not session_id:
                raise validation_error("澄清确认与重新澄清必须携带 session_id")
            session = await asyncio.to_thread(self._session_repo.get, session_id)
            if session is None:
                raise not_found("会话不存在")
        elif session_id:
            session = await asyncio.to_thread(self._session_repo.get, session_id)
            if session is None:
                raise not_found("会话不存在")
        else:
            session = None

        # --- ① 新问 ---
        if question is not None:
            q = question.strip() if isinstance(question, str) else ""
            if not q:
                raise validation_error("问题不能为空")
            if len(q) > self._config.question_max_length:
                raise validation_error(f"问题长度超过上限 {self._config.question_max_length} 字")
            if session is None:
                session = await asyncio.to_thread(self._session_repo.create, title=q)
            await self._expire_pending_tickets(session["id"])
            summary = await self._conversation_summary(session)
            turn = self._new_turn(session_id=session["id"], question=q)
            user_payload = {"question": q}
            kwargs: dict[str, Any] = {"question": q, "thread_id": turn.turn_id}
            await self._start(turn, kwargs, user_payload, summary)
            return turn

        # --- ② 澄清确认 ---
        if clarify is not None:
            clarify_id = clarify.get("clarify_id") or ""
            ticket = self._tickets.get(clarify_id)
            if ticket is None or ticket.status != "pending":
                raise clarify_expired()
            if ticket.session_id != session_id:
                raise validation_error("澄清票据不属于该会话")
            selection = clarify.get("selection") or {}
            try:
                clarified_q = mappers.compose_clarified_question(ticket.question, ticket.payload, selection)
            except ValueError as e:
                raise validation_error(str(e)) from e
            # 票据终态化（内存 + 落库），重复确认 409（AC-6）
            self._tickets.set_status(clarify_id, "confirmed")
            await asyncio.to_thread(self._message_repo.update_clarification_status, clarify_id, "confirmed")
            session = await asyncio.to_thread(self._session_repo.get, ticket.session_id)
            summary = await self._conversation_summary(session)
            turn = self._new_turn(session_id=ticket.session_id, question=clarified_q)
            user_payload = {"question": clarified_q}
            kwargs = {
                "clarified_question": clarified_q,
                "clarify_id": clarify_id,
                "thread_id": ticket.thread_id,  # 复用同 thread/checkpointer（接缝节第 1 点）
            }
            await self._start(turn, kwargs, user_payload, summary)
            return turn

        # --- ③ recalibrate ---
        source_turn_id = (recalibrate or {}).get("source_turn_id") or ""
        src = await asyncio.to_thread(self._message_repo.find_answer_by_turn, source_turn_id)
        if src is None:
            raise not_found("来源结果不存在")
        qspec = (src.get("internal") or {}).get("query_spec")
        if not qspec:
            raise not_found("该结果没有可用的查询口径，无法重新澄清")
        src_session_id = src.get("session_id")
        if session_id and session_id != src_session_id:
            raise validation_error("来源结果不属于该会话")
        q_text = (src.get("payload") or {}).get("question") or "重新澄清"
        await self._expire_pending_tickets(src_session_id)
        summary = await self._conversation_summary(session)
        turn = self._new_turn(session_id=src_session_id, question=q_text)
        user_payload = {"question": q_text}
        kwargs = {
            "query_spec": qspec,
            "start_at": "S4",  # 算法 recalibrate 入口：从 S4 强制出澄清卡，不执行 SQL（FR-4③）
            "thread_id": turn.turn_id,
        }
        await self._start(turn, kwargs, user_payload, summary)
        return turn

    async def _start(self, turn: Turn, kwargs: dict, user_payload: dict, summary: str) -> None:
        turn.thread_id = str(kwargs.get("thread_id") or turn.turn_id)
        # 落 user 消息（FR-9：建 turn 落 user 消息，seq 递增，touch last_question_at）
        await asyncio.to_thread(
            self._message_repo.append,
            turn.session_id,
            type="user",
            payload=user_payload,
            internal=None,
            touch_question=True,
        )
        kwargs["conversation_summary"] = summary
        self._turns[turn.turn_id] = turn
        turn.task = asyncio.create_task(self._run_turn(turn, kwargs))

    # ---------- 执行与终态（FR-5/FR-6/FR-9） ----------
    async def _run_turn(self, turn: Turn, kwargs: dict) -> None:
        def on_event(event: str, payload: dict) -> None:
            if event in ("node_started", "node_finished"):
                stage = mappers.stage_of_node((payload or {}).get("node", ""))
                if stage is not None:
                    name, label = stage
                    frames = turn.buffer.frames
                    last = frames[-1] if frames else None
                    if last is None or last.event != "stage" or last.data.get("stage") != name:
                        turn.buffer.append("stage", {"stage": name, "label": label})

        turn.started = True
        if turn.cancel_requested:  # 任务启动前已被取消：自行进入取消收尾（task.cancel 对未启动协程不生效）
            await self._finalize_cancelled(turn)
            return
        try:
            result: ChainResult = await self._chain_runner(
                deps=self._deps,
                on_event=on_event,
                checkpointer=self._checkpointer,
                **kwargs,
            )
        except asyncio.CancelledError:
            await self._finalize_cancelled(turn)
            return
        except Exception as e:  # noqa: BLE001  兜底：任何链路外异常 → error 终态（FR-6）
            logger.exception("turn %s 链路异常", turn.turn_id)
            result = ChainResult(
                action="error",
                error={"code": "E_INTERNAL", "message": "服务内部处理失败，请重试", "retryable": True},
                trace=Trace(),
                meta=Meta(turn_id=turn.turn_id, question=turn.question),
            )
        # 链路已返回：收尾不可取消（shield 防外部 cancel 打断落库与 close）
        await asyncio.shield(self._finalize(turn, result))

    async def _finalize(self, turn: Turn, result: ChainResult) -> None:
        event_name, frame = mappers.terminal_frame(result, turn_id=turn.turn_id, session_id=turn.session_id)
        mtype, payload, internal = mappers.terminal_message(result, turn_id=turn.turn_id, session_id=turn.session_id)
        await asyncio.to_thread(self._message_repo.append, turn.session_id, type=mtype, payload=payload, internal=internal)
        if mappers.action_name(result) == "clarify":
            self._tickets.add(
                ClarifyTicket(
                    clarify_id=payload["clarify_id"],
                    thread_id=turn.thread_id,
                    session_id=turn.session_id,
                    payload=payload,
                    question=turn.question,
                )
            )
        turn.buffer.append(event_name, frame)
        turn.buffer.append("done", {"turn_id": turn.turn_id})  # 每帧后恒收尾 done（FR-6）
        turn.buffer.close()
        turn.status = "done"

    async def _finalize_cancelled(self, turn: Turn) -> None:
        turn.buffer.append("cancelled", {"turn_id": turn.turn_id})
        mtype, payload = mappers.cancelled_message()
        await asyncio.to_thread(self._message_repo.append, turn.session_id, type=mtype, payload=payload, internal=None)
        turn.buffer.append("done", {"turn_id": turn.turn_id})
        turn.buffer.close()
        turn.status = "cancelled"

    # ---------- 取消（FR-8 / B6） ----------
    def cancel(self, turn_id: str) -> Turn:
        turn = self._turns.get(turn_id)
        if turn is None:
            raise turn_not_found()
        if turn.status == "running":
            turn.cancel_requested = True
            turn.status = "cancelling"
            if turn.started and turn.task is not None and not turn.task.done():
                turn.task.cancel()  # 已启动才投递 CancelledError；未启动由 _run_turn 启动时自查标志
        return turn

    # ---------- 查询（SSE 路由用） ----------
    def get_turn(self, turn_id: str) -> Optional[Turn]:
        return self._turns.get(turn_id)

    # ---------- 内部 ----------
    def _new_turn(self, *, session_id: str, question: str) -> Turn:
        buffer = EventBuffer(retention_seconds=self._config.sse_buffer_seconds, clock=self._clock)
        return Turn(
            turn_id=str(uuid.uuid4()),
            session_id=session_id,
            question=question,
            thread_id="",  # 由各分支 kwargs 决定并回填
            buffer=buffer,
        )

    async def _conversation_summary(self, session: Optional[dict]) -> str:
        """conversation_summary = 最近 N 轮 answer 的 caliber.detail + 会话首问时拼入继承口径（FR-10/FR-15）。"""
        if session is None:
            return ""
        msgs = await asyncio.to_thread(self._message_repo.list_by_session, session["id"])
        answers = [m["payload"] for m in msgs if m.get("type") == "answer"]
        parts: list[str] = []
        inherited = session.get("inherited_spec")
        if inherited and not msgs:  # 首问：会话尚无任何消息（AC-12）
            text = mappers.inherited_summary_text(inherited)
            if text:
                parts.append(text)
        summary = mappers.build_conversation_summary(answers, max_rounds=self._config.summary_rounds)
        if summary:
            parts.append(summary)
        return "；".join(parts)

    async def _expire_pending_tickets(self, session_id: str) -> None:
        """同会话新 turn 进来，未确认的澄清票据作废（status 终态化，AC-6 cancelled 态）。"""
        for t in self._tickets.pending_in_session(session_id):
            self._tickets.set_status(t.clarify_id, "cancelled")
            await asyncio.to_thread(self._message_repo.update_clarification_status, t.clarify_id, "cancelled")

    def _prune_expired_turns(self) -> None:
        """清理已过期且已收尾的 turn（缓冲保留 10 分钟，NFR-4）。"""
        for tid in list(self._turns):
            t = self._turns[tid]
            if t.status in ("done", "cancelled") and t.buffer.expired():
                self._turns.pop(tid, None)
