"""TR-6.1 / TR-6.2：chat 路由端到端（SSE 取帧、建流 404、参数校验、取消幂等）。"""
import re
import time

from backend_service.errors import AppError

from ..conftest import (
    make_answer_result,
    make_chain_runner,
    make_clarify_result,
    make_client,
    make_services,
    make_slow_chain_runner,
)

_BASE = "/api/v1"


def parse_sse(text: str) -> list[tuple[int, str, dict]]:
    """把 SSE 文本还原为 (id, event, data) 列表；忽略心跳注释行。"""
    frames = []
    for block in re.split(r"\r?\n\r?\n", text):
        fid, ev, data = None, None, None
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                fid = int(line[3:].strip())
            elif line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                import json

                data = json.loads(line[5:].strip())
        if ev is not None or data is not None:
            frames.append((fid, ev, data))
    return frames


async def test_create_turn_and_sse_e2e():
    svc = make_services(chain_runner=make_chain_runner([make_answer_result(turn_id="t1", question="618 各渠道 GMV")]))
    with make_client(svc) as c:
        resp = c.post(f"{_BASE}/chat/turns", json={"question": "618 各渠道 GMV"})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "running"
        assert body["turn_id"] and body["session_id"]
        # SSE 取帧
        with c.stream("GET", f"{_BASE}/chat/turns/{body['turn_id']}/events") as stream:
            assert stream.headers["content-type"].startswith("text/event-stream")
            frames = parse_sse(stream.read().decode("utf-8"))
    assert [ev for _, ev, _ in frames] == ["answer", "done"]
    ids = [i for i, _, _ in frames]
    assert ids == [1, 2]
    assert frames[0][2]["turn_id"] == body["turn_id"]
    assert frames[0][2]["saveable"] is True
    assert frames[1][2] == {"turn_id": body["turn_id"]}
    # 落库已发生
    types = [m["type"] for m in svc.message_repo.list_by_session(body["session_id"])]
    assert types == ["user", "answer"]


async def test_sse_with_stage_frames_then_terminal():
    """带节点事件的假链路：stage 帧在终态帧之前。"""
    async def emitting_runner(**kwargs):
        kwargs["on_event"]("node_started", {"node": "S1"})
        kwargs["on_event"]("node_started", {"node": "S5"})
        return make_answer_result()

    svc = make_services(chain_runner=emitting_runner)
    with make_client(svc) as c:
        resp = c.post(f"{_BASE}/chat/turns", json={"question": "q"})
        tid = resp.json()["turn_id"]
        with c.stream("GET", f"{_BASE}/chat/turns/{tid}/events") as stream:
            frames = parse_sse(stream.read().decode("utf-8"))
    assert [ev for _, ev, _ in frames] == ["stage", "stage", "answer", "done"]


def test_turn_events_unknown_404():
    svc = make_services()
    with make_client(svc) as c:
        resp = c.get(f"{_BASE}/chat/turns/ghost/events")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "E_TURN_NOT_FOUND"


def test_sse_last_event_id_resume():
    svc = make_services(chain_runner=make_chain_runner([make_answer_result()]))
    with make_client(svc) as c:
        tid = c.post(f"{_BASE}/chat/turns", json={"question": "q"}).json()["turn_id"]
        with c.stream("GET", f"{_BASE}/chat/turns/{tid}/events", headers={"last-event-id": "1"}) as stream:
            frames = parse_sse(stream.read().decode("utf-8"))
    # 全帧 [answer(1), done(2)]；从 id=1 之后补帧 → 只剩 done
    assert [ev for _, ev, _ in frames] == ["done"]
    assert frames[0][0] == 2


async def test_create_turn_validation_errors():
    svc = make_services()
    with make_client(svc) as c:
        # 空问题
        r = c.post(f"{_BASE}/chat/turns", json={"question": "  "})
        assert r.status_code == 400 and r.json()["error"]["code"] == "E_VALIDATION"
        # 超长（501 字）
        r = c.post(f"{_BASE}/chat/turns", json={"question": "长" * 501})
        assert r.status_code == 400
        # 三入参互斥
        r = c.post(f"{_BASE}/chat/turns", json={"question": "q", "recalibrate": {"source_turn_id": "t"}})
        assert r.status_code == 400
        # 会话不存在 → 404
        r = c.post(f"{_BASE}/chat/turns", json={"session_id": "ghost-session", "clarify": {"clarify_id": "x", "selection": {"type": "custom", "value": "y"}}})
        assert r.status_code == 404 and r.json()["error"]["code"] == "E_NOT_FOUND"
        # 真实会话下未知票据 → 409
        sid = c.post(f"{_BASE}/chat/turns", json={"question": "q"}).json()["session_id"]
        r = c.post(f"{_BASE}/chat/turns", json={"session_id": sid, "clarify": {"clarify_id": "ghost", "selection": {"type": "custom", "value": "x"}}})
        assert r.status_code == 409 and r.json()["error"]["code"] == "E_CLARIFY_EXPIRED"


async def test_cancel_flow_and_idempotency():
    svc = make_services(chain_runner=make_slow_chain_runner(make_answer_result(), delay=30))
    with make_client(svc) as c:
        tid = c.post(f"{_BASE}/chat/turns", json={"question": "慢查询"}).json()["turn_id"]
        r1 = c.post(f"{_BASE}/chat/turns/{tid}/cancel")
        assert r1.status_code == 202 and r1.json()["status"] == "cancelling"
        r2 = c.post(f"{_BASE}/chat/turns/{tid}/cancel")  # 重复取消不 500
        assert r2.status_code == 202
        # 等待取消收尾完成
        for _ in range(40):
            turn = svc.conversation.get_turn(tid)
            if turn is not None and turn.status == "cancelled":
                break
            time.sleep(0.05)
        assert turn.status == "cancelled"
        # 未知 turn → 404
        r3 = c.post(f"{_BASE}/chat/turns/ghost/cancel")
        assert r3.status_code == 404 and r3.json()["error"]["code"] == "E_TURN_NOT_FOUND"


async def test_clarify_confirm_via_http():
    svc = make_services(
        chain_runner=make_chain_runner(
            [
                make_clarify_result(turn_id="t1", clarify_id="cl-1"),
                make_answer_result(turn_id="t2", question="美妆 GMV 怎么样（彩妆）"),
            ]
        )
    )
    with make_client(svc) as c:
        r = c.post(f"{_BASE}/chat/turns", json={"question": "美妆 GMV 怎么样"})
        sid = r.json()["session_id"]
        # 等票据登记（后台 finalize）
        for _ in range(100):
            if svc.conversation._tickets.get("cl-1") is not None:
                break
            time.sleep(0.02)
        # 确认澄清
        r2 = c.post(f"{_BASE}/chat/turns", json={"session_id": sid, "clarify": {"clarify_id": "cl-1", "selection": {"type": "option", "value": "彩妆"}}})
        assert r2.status_code == 202
        assert r2.json()["session_id"] == sid
        # 重复确认 → 409
        r3 = c.post(f"{_BASE}/chat/turns", json={"session_id": sid, "clarify": {"clarify_id": "cl-1", "selection": {"type": "option", "value": "彩妆"}}})
        assert r3.status_code == 409 and r3.json()["error"]["code"] == "E_CLARIFY_EXPIRED"
