"""TR-5.1~5.5：六 action 帧映射、三入参互斥、澄清票据、internal 三键、缓冲/取消。"""
import pytest

from algorithm.state import Action

from backend_service.application import mappers
from backend_service.errors import AppError

from ..conftest import (
    DEFAULT_QSPEC,
    make_answer_result,
    make_chain_runner,
    make_clarify_result,
    make_empty_answer_result,
    make_error_result,
    make_rejection_result,
    make_services,
    make_slow_chain_runner,
)

QSPEC_DICT = DEFAULT_QSPEC.model_dump(mode="json")


async def wait_done(turn) -> None:
    await turn.task


# ---------------------------------------------------------------------------
# TR-5.1：六 action → 帧名/帧序/载荷逐字段
# ---------------------------------------------------------------------------
ANSWER_KEYS = {
    "turn_id", "session_id", "question", "table", "chart", "insight",
    "caliber", "comparison", "data_time_range", "queried_at", "saveable",
}


async def test_answer_turn_frames_and_payload():
    svc = make_services(chain_runner=make_chain_runner([make_answer_result(turn_id="t1", question="618 各渠道 GMV")]))
    turn = await svc.conversation.create_turn(question="618 各渠道 GMV")
    await wait_done(turn)
    assert turn.status == "done"
    events = [f.event for f in turn.buffer.frames]
    assert events == ["answer", "done"]
    frame = turn.buffer.frames[0]
    assert set(frame.data) == ANSWER_KEYS
    assert frame.data["turn_id"] == turn.turn_id
    assert frame.data["session_id"] == turn.session_id
    assert frame.data["question"] == "618 各渠道 GMV"
    assert frame.data["saveable"] is True
    assert frame.data["data_time_range"] == {"start": "2026-06-16", "end": "2026-06-18", "label": "本期大促·正式期"}
    assert frame.data["table"]["rows"][0]["channel"] == "渠道A"
    assert frame.data["caliber"]["summary"] == "大促三天 GMV 按渠道"
    # 落库：user + answer
    types = [m["type"] for m in svc.message_repo.list_by_session(turn.session_id)]
    assert types == ["user", "answer"]


async def test_empty_answer_saveable_false():
    svc = make_services(chain_runner=make_chain_runner([make_empty_answer_result(turn_id="t1")]))
    turn = await svc.conversation.create_turn(question="营销费用的 GMV")
    await wait_done(turn)
    assert turn.buffer.frames[0].event == "answer"
    assert turn.buffer.frames[0].data["saveable"] is False


async def test_clarify_turn_frame_and_ticket_registered():
    svc = make_services(chain_runner=make_chain_runner([make_clarify_result(turn_id="t1", clarify_id="cl-9")]))
    turn = await svc.conversation.create_turn(question="美妆 GMV 怎么样")
    await wait_done(turn)
    events = [f.event for f in turn.buffer.frames]
    assert events == ["clarification", "done"]
    data = turn.buffer.frames[0].data
    assert data["clarify_id"] == "cl-9"
    assert data["status"] == "pending"
    assert data["input_type"] == "single_choice"
    assert data["round"] == 1
    assert len(data["options"]) == 4
    assert "sql" not in data and "trace" not in data and "query_spec" not in data
    # 票据已登记（进程内）
    assert svc.conversation._tickets.get("cl-9") is not None
    types = [m["type"] for m in svc.message_repo.list_by_session(turn.session_id)]
    assert types == ["user", "clarification"]


@pytest.mark.parametrize(
    ("result", "frame_event", "reason_code"),
    [
        (make_rejection_result(action=Action.NOT_ANSWERABLE, reason_code="NOT_DATA_QUESTION"), "rejection", "NOT_DATA_QUESTION"),
        (make_rejection_result(action=Action.QUERY_GEN_FAILED, reason_code="GEN_LINT_EXHAUSTED"), "rejection", "GEN_LINT_EXHAUSTED"),
        (make_rejection_result(action=Action.QUERY_FAILED, reason_code="QUERY_TIMEOUT"), "rejection", "QUERY_TIMEOUT"),
    ],
)
async def test_rejection_turns_frame(result, frame_event, reason_code):
    svc = make_services(chain_runner=make_chain_runner([result]))
    turn = await svc.conversation.create_turn(question="明年 GMV 预测")
    await wait_done(turn)
    events = [f.event for f in turn.buffer.frames]
    assert events == ["rejection", "done"]
    data = turn.buffer.frames[0].data
    assert data["reason_code"] == reason_code
    assert "sql" not in data and "trace" not in data
    types = [m["type"] for m in svc.message_repo.list_by_session(turn.session_id)]
    assert types == ["user", "rejection"]


async def test_error_turn_frame_and_note_message():
    svc = make_services(chain_runner=make_chain_runner([make_error_result(turn_id="t1", code="E_LLM_UNAVAILABLE")]))
    turn = await svc.conversation.create_turn(question="618 GMV")
    await wait_done(turn)
    events = [f.event for f in turn.buffer.frames]
    assert events == ["error", "done"]
    data = turn.buffer.frames[0].data
    assert data == {"code": "E_LLM_UNAVAILABLE", "message": "服务繁忙，请稍后重试", "retryable": True}
    types = [m["type"] for m in svc.message_repo.list_by_session(turn.session_id)]
    assert types == ["user", "note"]  # §3.3 无 error 消息 → note
    note = svc.message_repo.list_by_session(turn.session_id)[-1]
    assert note["payload"]["kind"] == "system"


# ---------------------------------------------------------------------------
# TR-5.4：internal 三键落库；出口序列化不含 sql/trace/query_spec；stage 不落库
# ---------------------------------------------------------------------------
async def test_internal_three_keys_and_payload_whitelist():
    svc = make_services(chain_runner=make_chain_runner([make_answer_result(turn_id="t1", sql="SELECT 1")]))
    turn = await svc.conversation.create_turn(question="618 各渠道 GMV")
    await wait_done(turn)
    msgs = svc.message_repo.list_by_session(turn.session_id)
    answer_msg = msgs[-1]
    assert set(answer_msg["internal"]) == {"sql", "trace", "query_spec"}
    assert answer_msg["internal"]["sql"] == "SELECT 1"
    assert answer_msg["internal"]["query_spec"] == QSPEC_DICT
    assert set(answer_msg["internal"]["trace"]) >= {"path", "llm_calls"}
    # payload 白名单：不含三键
    for m in msgs:
        assert "sql" not in m["payload"]
        assert "trace" not in m["payload"]
        assert "query_spec" not in m["payload"]
    # 帧也不含
    for f in turn.buffer.frames:
        assert "sql" not in f.data and "trace" not in f.data and "query_spec" not in f.data
    # stage 不落库：消息类型只有 user/answer
    assert all(m["type"] in ("user", "answer") for m in msgs)


async def test_stage_events_mapped_and_deduped():
    """on_event node_started/finished → stage 帧：写死映射、同段去重、未知节点忽略。"""
    async def emitting_runner(**kwargs):
        on_event = kwargs["on_event"]
        on_event("node_started", {"node": "S1"})
        on_event("node_started", {"node": "S2"})
        on_event("node_started", {"node": "S4"})
        on_event("node_finished", {"node": "S4"})
        on_event("node_started", {"node": "S5"})
        on_event("node_started", {"node": "S9"})  # 未知节点 → 忽略
        return make_answer_result()

    svc = make_services(chain_runner=emitting_runner)
    turn = await svc.conversation.create_turn(question="618 各渠道 GMV")
    await wait_done(turn)
    stage_names = [f.data["stage"] for f in turn.buffer.frames if f.event == "stage"]
    # S2/S4 同属 checking_caliber → 去重成一帧
    assert stage_names == ["understanding", "checking_caliber", "querying"]
    labels = [f.data["label"] for f in turn.buffer.frames if f.event == "stage"]
    assert labels == ["正在理解问题", "正在核对口径", "正在取数"]


# ---------------------------------------------------------------------------
# TR-5.2：三入参互斥、票据失效 409、recalibrate 缺源 404
# ---------------------------------------------------------------------------
async def test_three_modes_mutually_exclusive():
    svc = make_services()
    with pytest.raises(AppError) as e1:
        await svc.conversation.create_turn(question="q", clarify={"clarify_id": "x", "selection": {"type": "custom", "value": "y"}})
    assert e1.value.code == "E_VALIDATION"
    with pytest.raises(AppError) as e2:
        await svc.conversation.create_turn(clarify={"clarify_id": "x", "selection": {"type": "custom", "value": "y"}}, recalibrate={"source_turn_id": "t"})
    assert e2.value.code == "E_VALIDATION"
    with pytest.raises(AppError):
        await svc.conversation.create_turn()
    # 空问题 / 超长
    with pytest.raises(AppError):
        await svc.conversation.create_turn(question="   ")
    with pytest.raises(AppError):
        await svc.conversation.create_turn(question="长" * 501)


async def test_recalibrate_missing_source_404():
    svc = make_services()
    session = svc.session_repo.create(title="空会话")
    with pytest.raises(AppError) as e:
        await svc.conversation.create_turn(session_id=session["id"], recalibrate={"source_turn_id": "no-such"})
    assert e.value.code == "E_NOT_FOUND"


async def test_recalibrate_without_query_spec_404():
    """源 turn 是澄清终态（internal.query_spec=None）→ 不可重新澄清。"""
    svc = make_services(chain_runner=make_chain_runner([make_clarify_result(turn_id="t1", clarify_id="cl-1")]))
    t1 = await svc.conversation.create_turn(question="美妆 GMV 怎么样")
    await wait_done(t1)
    with pytest.raises(AppError) as e:
        await svc.conversation.create_turn(session_id=t1.session_id, recalibrate={"source_turn_id": t1.turn_id})
    assert e.value.code == "E_NOT_FOUND"


async def test_recalibrate_passes_query_spec_and_start_at_s4():
    svc = make_services(chain_runner=make_chain_runner([make_answer_result(turn_id="t1")]))
    t1 = await svc.conversation.create_turn(question="618 各渠道 GMV")
    await wait_done(t1)
    runner2 = make_chain_runner([make_clarify_result(turn_id="t2", clarify_id="cl-2")])
    svc.conversation._chain_runner = runner2
    t2 = await svc.conversation.create_turn(session_id=t1.session_id, recalibrate={"source_turn_id": t1.turn_id})
    await wait_done(t2)
    call = runner2.calls[0]
    assert call["start_at"] == "S4"
    assert call["query_spec"] == QSPEC_DICT
    assert call["thread_id"] == t2.turn_id
    assert "question" not in call and "clarified_question" not in call
    assert call["conversation_summary"] != ""  # 带 recent answer 口径
    # 消息落在源会话
    types = [m["type"] for m in svc.message_repo.list_by_session(t1.session_id)]
    assert types == ["user", "answer", "user", "clarification"]


async def test_recalibrate_session_mismatch_400():
    svc = make_services(chain_runner=make_chain_runner([make_answer_result(turn_id="t1")]))
    t1 = await svc.conversation.create_turn(question="618 各渠道 GMV")
    await wait_done(t1)
    other = svc.session_repo.create(title="别的会话")
    with pytest.raises(AppError) as e:
        await svc.conversation.create_turn(session_id=other["id"], recalibrate={"source_turn_id": t1.turn_id})
    assert e.value.code == "E_VALIDATION"


# ---------------------------------------------------------------------------
# TR-5.3：澄清链路 QueryRunner=0；三种 selection 拼接；重复确认被拒
# ---------------------------------------------------------------------------
class QueryRunnerSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, sql: str):
        self.calls.append(sql)
        raise AssertionError("澄清链路不应执行 SQL")


async def test_clarify_flow_runs_no_query():
    svc = make_services(chain_runner=make_chain_runner([make_clarify_result()]))
    spy = QueryRunnerSpy()
    svc.deps.query_runner = spy
    turn = await svc.conversation.create_turn(question="美妆 GMV 怎么样")
    await wait_done(turn)
    assert spy.calls == []
    assert turn.buffer.frames[0].event == "clarification"


async def test_three_selection_compositions():
    payload = make_clarify_result().clarify.model_dump(mode="json")
    # option
    assert mappers.compose_clarified_question("美妆 GMV 怎么样", payload, {"type": "option", "value": "彩妆"}) == "美妆 GMV 怎么样（彩妆）"
    # time_preset（选项 label）
    tp = {**payload, "options": [{"value": "last_7d", "label": "近7天"}]}
    assert mappers.compose_clarified_question("看GMV", tp, {"type": "time_preset", "value": "last_7d"}) == "看GMV（时间：近7天）"
    # time_preset（起止 dict）
    assert (
        mappers.compose_clarified_question("看GMV", tp, {"type": "time_preset", "value": {"start": "2026-06-01", "end": "2026-06-18"}})
        == "看GMV（时间：2026-06-01 至 2026-06-18）"
    )
    # custom
    assert mappers.compose_clarified_question("看GMV", payload, {"type": "custom", "value": "只看线上渠道"}) == "只看线上渠道"
    with pytest.raises(ValueError):
        mappers.compose_clarified_question("看GMV", payload, {"type": "custom", "value": "  "})


async def test_confirm_flow_and_duplicate_rejected():
    svc = make_services(chain_runner=make_chain_runner([make_clarify_result(turn_id="t1", clarify_id="cl-1")]))
    t1 = await svc.conversation.create_turn(question="美妆 GMV 怎么样")
    await wait_done(t1)
    ticket = svc.conversation._tickets.get("cl-1")
    assert ticket is not None and ticket.status == "pending"
    # 跨会话（票据仍 pending）→ 400；未知票据 → 409
    other = svc.session_repo.create(title="别的会话")
    with pytest.raises(AppError) as e2:
        await svc.conversation.create_turn(session_id=other["id"], clarify={"clarify_id": "cl-1", "selection": {"type": "custom", "value": "x"}})
    assert e2.value.code == "E_VALIDATION"
    with pytest.raises(AppError):
        await svc.conversation.create_turn(session_id=t1.session_id, clarify={"clarify_id": "ghost", "selection": {"type": "custom", "value": "x"}})
    # 确认 → 复用票据 thread_id
    runner2 = make_chain_runner([make_answer_result(turn_id="t2", question="美妆 GMV 怎么样（彩妆）")])
    svc.conversation._chain_runner = runner2
    t2 = await svc.conversation.create_turn(
        session_id=t1.session_id,
        clarify={"clarify_id": "cl-1", "selection": {"type": "option", "value": "彩妆"}},
    )
    await wait_done(t2)
    call = runner2.calls[0]
    assert call["clarified_question"] == "美妆 GMV 怎么样（彩妆）"
    assert call["clarify_id"] == "cl-1"
    assert call["thread_id"] == ticket.thread_id
    assert call["conversation_summary"] == ""  # 尚无 answer 消息
    # 票据 confirmed（内存 + 落库）
    assert ticket.status == "confirmed"
    msg = svc.message_repo.find_clarification("cl-1")
    assert msg["payload"]["status"] == "confirmed"
    # 重复确认 → 409
    with pytest.raises(AppError) as e:
        await svc.conversation.create_turn(
            session_id=t1.session_id,
            clarify={"clarify_id": "cl-1", "selection": {"type": "option", "value": "彩妆"}},
        )
    assert e.value.code == "E_CLARIFY_EXPIRED"


async def test_new_question_expires_pending_tickets():
    svc = make_services(chain_runner=make_chain_runner([make_clarify_result(turn_id="t1", clarify_id="cl-1")]))
    t1 = await svc.conversation.create_turn(question="美妆 GMV 怎么样")
    await wait_done(t1)
    runner2 = make_chain_runner([make_answer_result(turn_id="t2")])
    svc.conversation._chain_runner = runner2
    await svc.conversation.create_turn(session_id=t1.session_id, question="换个问法")
    ticket = svc.conversation._tickets.get("cl-1")
    assert ticket.status == "cancelled"
    assert svc.message_repo.find_clarification("cl-1")["payload"]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# TR-5.5：缓冲补帧与过期（可控时钟）；取消 → cancelled + note
# ---------------------------------------------------------------------------
class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_event_buffer_after_and_expiry():
    clock = FakeClock()
    from backend_service.application.event_buffer import EventBuffer

    buf = EventBuffer(retention_seconds=600, clock=clock)
    buf.append("stage", {"stage": "understanding"})
    buf.append("stage", {"stage": "querying"})
    buf.append("answer", {"x": 1})
    assert [f.id for f in buf.after(0)] == [1, 2, 3]
    assert [f.id for f in buf.after(1)] == [2, 3]  # Last-Event-ID 补帧
    assert buf.closed is False
    clock.now = 100 + 601
    assert buf.expired() is True
    clock.now = 100 + 599
    assert buf.expired() is False


async def test_turn_pruned_after_expiry():
    clock = FakeClock()
    script = [make_answer_result(turn_id="t1"), make_answer_result(turn_id="t2")]
    svc = make_services(chain_runner=make_chain_runner(script), clock=clock)
    t1 = await svc.conversation.create_turn(question="第一问")
    await wait_done(t1)
    assert svc.conversation.get_turn(t1.turn_id) is not None
    clock.now += 700  # 超过 10min 保留期
    t2 = await svc.conversation.create_turn(session_id=t1.session_id, question="第二问")
    await wait_done(t2)
    assert svc.conversation.get_turn(t1.turn_id) is None  # 旧 turn 已被清理
    assert svc.conversation.get_turn(t2.turn_id) is not None


async def test_cancel_flow_to_cancelled_note():
    slow = make_slow_chain_runner(make_answer_result(turn_id="t1"), delay=30)
    svc = make_services(chain_runner=slow)
    turn = await svc.conversation.create_turn(question="慢查询")
    svc.conversation.cancel(turn.turn_id)
    await wait_done(turn)
    assert turn.status == "cancelled"
    events = [f.event for f in turn.buffer.frames]
    assert events == ["cancelled", "done"]
    types = [m["type"] for m in svc.message_repo.list_by_session(turn.session_id)]
    assert types == ["user", "note"]
    note = svc.message_repo.list_by_session(turn.session_id)[-1]
    assert note["payload"] == {"kind": "cancelled", "text": "已取消"}


async def test_cancel_idempotent_and_unknown():
    svc = make_services(chain_runner=make_slow_chain_runner(make_answer_result(), delay=30))
    with pytest.raises(AppError) as e:
        svc.conversation.cancel("ghost")
    assert e.value.code == "E_TURN_NOT_FOUND"
    turn = await svc.conversation.create_turn(question="慢查询")
    svc.conversation.cancel(turn.turn_id)
    again = svc.conversation.cancel(turn.turn_id)  # 重复取消幂等
    assert again.turn_id == turn.turn_id
    await wait_done(turn)


async def test_chain_exception_falls_back_to_error():
    """链路外异常兜底 → error 终态（FR-6）。"""
    async def boom(**kwargs):
        raise RuntimeError("意外")

    svc = make_services(chain_runner=boom)
    turn = await svc.conversation.create_turn(question="618 GMV")
    await wait_done(turn)
    assert turn.buffer.frames[0].event == "error"
    assert turn.buffer.frames[0].data["code"] == "E_INTERNAL"


async def test_conversation_summary_from_recent_answers():
    svc = make_services(chain_runner=make_chain_runner([make_answer_result(turn_id="t1")]))
    t1 = await svc.conversation.create_turn(question="第一问")
    await wait_done(t1)
    runner2 = make_chain_runner([make_answer_result(turn_id="t2")])
    svc.conversation._chain_runner = runner2
    t2 = await svc.conversation.create_turn(session_id=t1.session_id, question="第二问")
    await wait_done(t2)
    summary = runner2.calls[0]["conversation_summary"]
    assert "指标 GMV" in summary
    assert "维度 渠道" in summary
    assert "时间 2026-06-16~2026-06-18" in summary
