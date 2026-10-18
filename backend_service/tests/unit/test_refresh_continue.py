"""TR-9.1 / TR-9.2：报表刷新（S5 接缝、四终态同构、无副作用）与 continue-session 继承口径。"""
from ..conftest import (
    DEFAULT_QSPEC,
    make_answer_result,
    make_chain_runner,
    make_client,
    make_empty_answer_result,
    make_error_result,
    make_rejection_result,
    make_services,
)

_BASE = "/api/v1"
QSPEC_DICT = DEFAULT_QSPEC.model_dump(mode="json")


async def _saved_report(svc, *, title: str = "大促GMV"):
    svc.conversation._chain_runner = make_chain_runner([make_answer_result(turn_id="t1")])
    turn = await svc.conversation.create_turn(question="618 各渠道 GMV")
    await turn.task
    rep, _created = await svc.reports.save(turn_id=turn.turn_id, title=title)
    return rep


def _assert_s5_seam(call: dict) -> None:
    """断言调用的是 refresh 接缝而非 S1 主入口。"""
    assert call["start_at"] == "S5"
    assert call["query_spec"] == QSPEC_DICT
    assert call["thread_id"] is None
    assert call["checkpointer"] is None
    assert call["conversation_summary"] == ""
    assert "question" not in call and "clarified_question" not in call


async def test_refresh_answer_no_side_effects():
    svc = make_services()
    rep = await _saved_report(svc)
    before_msgs = sum(len(svc.message_repo.list_by_session(s)) for s in svc.session_repo.sessions)
    before_updated_at = rep["updated_at"]
    svc.reports._chain_runner = make_chain_runner([make_answer_result(turn_id="r1")])
    with make_client(svc) as c:
        r = c.post(f"{_BASE}/reports/{rep['id']}/refresh")
        assert r.status_code == 200
        body = r.json()
    _assert_s5_seam(svc.reports._chain_runner.calls[0])
    # 同构 answer 响应
    assert body["action"] == "answer"
    assert body["question"] == "618 各渠道 GMV"
    assert body["saveable"] is True
    assert body["table"]["rows"][0]["channel"] == "渠道A"
    assert body["data_time_range"]["start"] == "2026-06-16"
    assert body["queried_at"]
    assert "sql" not in body and "trace" not in body and "query_spec" not in body
    # 无副作用：消息数与快照 updated_at 不变
    after_msgs = sum(len(svc.message_repo.list_by_session(s)) for s in svc.session_repo.sessions)
    assert after_msgs == before_msgs
    assert svc.report_repo.get(rep["id"])["updated_at"] == before_updated_at


async def test_refresh_four_terminal_states():
    cases = [
        (make_empty_answer_result(turn_id="r1"), "answer", None),
        (
            make_rejection_result(action="query_gen_failed", reason_code="GEN_LINT_EXHAUSTED", turn_id="r1"),
            "query_gen_failed",
            "GEN_LINT_EXHAUSTED",
        ),
        (
            make_rejection_result(action="query_failed", reason_code="QUERY_TIMEOUT", turn_id="r1"),
            "query_failed",
            "QUERY_TIMEOUT",
        ),
        (make_error_result(turn_id="r1", code="E_LLM_UNAVAILABLE"), "error", None),
    ]
    for result, action, reason in cases:
        svc = make_services()
        rep = await _saved_report(svc)
        svc.reports._chain_runner = make_chain_runner([result])
        with make_client(svc) as c:
            r = c.post(f"{_BASE}/reports/{rep['id']}/refresh")
            assert r.status_code == 200
            body = r.json()
        _assert_s5_seam(svc.reports._chain_runner.calls[0])
        assert body["action"] == action
        if reason is not None:
            assert body["reason_code"] == reason
    # 空结果同构体：answer 且 saveable=false
    svc = make_services()
    rep = await _saved_report(svc)
    svc.reports._chain_runner = make_chain_runner([make_empty_answer_result(turn_id="r1")])
    with make_client(svc) as c:
        body = c.post(f"{_BASE}/reports/{rep['id']}/refresh").json()
    assert body["action"] == "answer" and body["saveable"] is False


async def test_refresh_missing_query_spec_409_and_unknown_404():
    svc = make_services()
    # 手工插一条没有 query_spec 的报表（insert 必填字段齐全）
    rep = svc.report_repo.insert(
        "default",
        {"title": "旧快照", "question": "q", "caliber": {"summary": "s"}, "snapshot": {"insight": "i"}, "queried_at": "2026-06-18T00:00:00Z"},
    )
    with make_client(svc) as c:
        r = c.post(f"{_BASE}/reports/{rep['id']}/refresh")
        assert r.status_code == 409 and r.json()["error"]["code"] == "E_REPORT_NOT_SAVEABLE"
        r2 = c.post(f"{_BASE}/reports/ghost/refresh")
        assert r2.status_code == 404 and r2.json()["error"]["code"] == "E_NOT_FOUND"


async def test_continue_session_creates_inherited_session():
    svc = make_services()
    rep = await _saved_report(svc)
    with make_client(svc) as c:
        r = c.post(f"{_BASE}/reports/{rep['id']}/continue-session")
        assert r.status_code == 201
        sid = r.json()["session_id"]
    session = svc.session_repo.get(sid)
    assert session["title"] == "618 各渠道 GMV"
    assert session["inherited_spec"] == QSPEC_DICT
    # 不插假消息
    assert svc.message_repo.list_by_session(sid) == []


async def test_continue_session_first_question_carries_inherited_summary():
    svc = make_services()
    rep = await _saved_report(svc)
    sid = (await svc.reports.continue_session(rep["id"]))["session_id"]
    runner2 = make_chain_runner([make_answer_result(turn_id="t2")])
    svc.conversation._chain_runner = runner2
    turn = await svc.conversation.create_turn(session_id=sid, question="那客单价呢")
    await turn.task
    summary = runner2.calls[0]["conversation_summary"]
    assert "【继承口径】" in summary
    assert "指标 gmv" in summary
    assert "维度 channel" in summary
    assert "时间 本期大促·正式期" in summary
    # 第二问不再带继承口径，改为最近 answer 口径
    runner3 = make_chain_runner([make_answer_result(turn_id="t3")])
    svc.conversation._chain_runner = runner3
    turn2 = await svc.conversation.create_turn(session_id=sid, question="第三问")
    await turn2.task
    summary2 = runner3.calls[0]["conversation_summary"]
    assert "【继承口径】" not in summary2
    assert "指标 GMV" in summary2  # 来自 t2 的 caliber.detail
