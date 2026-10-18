"""TR-7.1 / TR-7.2：sessions 路由（列表分页、消息还原、删除、报文白名单）。"""
import time

from ..conftest import (
    make_answer_result,
    make_chain_runner,
    make_client,
    make_clarify_result,
    make_services,
)

_BASE = "/api/v1"


def _wait_ticket(svc, clarify_id: str, timeout: float = 2.0) -> None:
    """等票据登记（后台任务 finalize 完成），避免确认时 409 竞态。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if svc.conversation._tickets.get(clarify_id) is not None:
            return
        time.sleep(0.02)
    raise AssertionError(f"票据 {clarify_id} 未在超时前登记")


async def _session_with_full_flow():
    """clarify → 确认 → answer 的完整会话（含最终 status 与 note 场景另测）。"""
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
        _wait_ticket(svc, "cl-1")
        r2 = c.post(
            f"{_BASE}/chat/turns",
            json={"session_id": sid, "clarify": {"clarify_id": "cl-1", "selection": {"type": "option", "value": "彩妆"}}},
        )
        assert r2.status_code == 202
    return svc, sid


async def test_list_sessions_and_pagination():
    svc, sid = await _session_with_full_flow()
    # 再建两个会话
    with make_client(svc) as c:
        c.post(f"{_BASE}/chat/turns", json={"question": "第二问"})
        c.post(f"{_BASE}/chat/turns", json={"question": "第三问"})
        r = c.get(f"{_BASE}/sessions")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 3
        # 分页边界
        r2 = c.get(f"{_BASE}/sessions", params={"offset": 1, "limit": 1})
        assert len(r2.json()["items"]) == 1
        assert r2.status_code == 200
        for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
            assert c.get(f"{_BASE}/sessions", params=bad).status_code == 400
    assert all(set(i) >= {"id", "title", "message_count", "last_question_at", "created_at"} for i in items)


async def test_get_messages_full_flow_and_whitelist():
    svc, sid = await _session_with_full_flow()
    with make_client(svc) as c:
        r = c.get(f"{_BASE}/sessions/{sid}/messages")
        assert r.status_code == 200
        body = r.json()
    assert set(body["session"]) == {"id", "title", "message_count", "last_question_at", "created_at"}
    assert body["session"]["title"] == "美妆 GMV 怎么样"
    msgs = body["messages"]
    assert [m["type"] for m in msgs] == ["user", "clarification", "user", "answer"]
    assert [m["seq"] for m in msgs] == [1, 2, 3, 4]
    # clarification 最终 status（确认后 confirmed）
    assert msgs[1]["payload"]["clarify_id"] == "cl-1"
    assert msgs[1]["payload"]["status"] == "confirmed"
    # TR-7.2：还原报文白名单不含 internal 三键
    assert set(msgs[0]) == {"id", "seq", "type", "payload", "created_at"}
    for m in msgs:
        assert "sql" not in m["payload"] and "trace" not in m["payload"] and "query_spec" not in m["payload"]
        assert "internal" not in m
    # answer 载荷字段
    ans = msgs[3]["payload"]
    assert ans["question"] == "美妆 GMV 怎么样（彩妆）"
    assert ans["saveable"] is True


async def test_get_messages_unknown_session_404():
    svc, _ = await _session_with_full_flow()
    with make_client(svc) as c:
        r = c.get(f"{_BASE}/sessions/ghost/messages")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "E_NOT_FOUND"


async def test_note_message_restored():
    """error 终态落 note，还原时 type=payload 一致。"""
    async def boom(**kwargs):
        raise RuntimeError("x")

    svc = make_services(chain_runner=boom)
    with make_client(svc) as c:
        sid = c.post(f"{_BASE}/chat/turns", json={"question": "q"}).json()["session_id"]
        for _ in range(40):
            msgs = svc.message_repo.list_by_session(sid)
            if len(msgs) >= 2:
                break
            time.sleep(0.05)
        r = c.get(f"{_BASE}/sessions/{sid}/messages")
    msgs = r.json()["messages"]
    assert [m["type"] for m in msgs] == ["user", "note"]
    assert msgs[1]["payload"]["kind"] == "system"


async def test_delete_session_204_then_404():
    svc, sid = await _session_with_full_flow()
    with make_client(svc) as c:
        r = c.delete(f"{_BASE}/sessions/{sid}")
        assert r.status_code == 204
        assert c.delete(f"{_BASE}/sessions/{sid}").status_code == 404
        assert c.get(f"{_BASE}/sessions/{sid}/messages").status_code == 404
    assert svc.session_repo.get(sid) is None
