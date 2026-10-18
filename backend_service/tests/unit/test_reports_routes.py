"""TR-8.1 / TR-8.2：报表存/列/开/改/删全分支；只读快照零链路调用 spy。"""
from datetime import datetime

from ..conftest import (
    make_answer_result,
    make_chain_runner,
    make_clarify_result,
    make_client,
    make_empty_answer_result,
    make_services,
)

_BASE = "/api/v1"


class QueryRunnerSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, sql: str):
        self.calls.append(sql)
        raise AssertionError("只读快照不应执行 SQL")


async def _saved_report(svc, *, title: str = "大促GMV", rows_present: bool = True):
    result = make_answer_result() if rows_present else make_empty_answer_result()
    svc.conversation._chain_runner = make_chain_runner([result])
    turn = await svc.conversation.create_turn(question="618 各渠道 GMV")
    await turn.task
    rep, created = await svc.reports.save(turn_id=turn.turn_id, title=title)
    assert created is True
    return rep, turn


async def test_save_report_201_conflict_overwrite():
    svc = make_services()
    rep, turn = await _saved_report(svc)
    with make_client(svc) as c:
        # 直存（服务层已存过一次，这里走 HTTP 重存同 turn 不同名）
        r = c.post(f"{_BASE}/reports", json={"turn_id": turn.turn_id, "title": "新报表"})
        assert r.status_code == 201
        body = r.json()
        assert set(body) == {"id", "title", "created_at"}
        # 同名冲突 → 409 + existing
        r2 = c.post(f"{_BASE}/reports", json={"turn_id": turn.turn_id, "title": "新报表"})
        assert r2.status_code == 409
        err = r2.json()["error"]
        assert err["code"] == "E_NAME_CONFLICT" and err["existing"]["id"] == body["id"]
        # 覆盖 → 200 且 id 不变
        r3 = c.post(f"{_BASE}/reports", json={"turn_id": turn.turn_id, "title": "新报表", "overwrite": True})
        assert r3.status_code == 200
        assert r3.json()["id"] == body["id"]
        assert "updated_at" in r3.json()
        # 空名 → 400
        assert c.post(f"{_BASE}/reports", json={"turn_id": turn.turn_id, "title": "  "}).status_code == 400


async def test_save_converts_queried_at_to_aware_datetime():
    """回归：payload.queried_at 是 "Z" 结尾 ISO 串，落库列是 DateTime(timezone=True)；
    save 必须转 aware datetime 再交仓储（真实 ORM 插入后立即序列化，字符串会炸 _iso）。"""
    svc = make_services()
    svc.conversation._chain_runner = make_chain_runner([make_answer_result()])
    turn = await svc.conversation.create_turn(question="618 各渠道 GMV")
    await turn.task
    rep, created = await svc.reports.save(turn_id=turn.turn_id, title="时间类型回归")
    assert created is True
    assert isinstance(rep["queried_at"], datetime) and rep["queried_at"].tzinfo is not None


async def test_save_guards_empty_and_non_answer():
    svc = make_services()
    # 空结果 answer（建 turn，不落报表）
    svc.conversation._chain_runner = make_chain_runner([make_empty_answer_result()])
    empty_turn = await svc.conversation.create_turn(question="营销费用的 GMV")
    await empty_turn.task
    # clarify turn
    svc.conversation._chain_runner = make_chain_runner([make_clarify_result(turn_id="tc", clarify_id="cl-1")])
    ct = await svc.conversation.create_turn(question="美妆 GMV 怎么样")
    await ct.task
    with make_client(svc) as c:
        r = c.post(f"{_BASE}/reports", json={"turn_id": empty_turn.turn_id, "title": "空结果"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "E_REPORT_NOT_SAVEABLE"
        r2 = c.post(f"{_BASE}/reports", json={"turn_id": ct.turn_id, "title": "澄清轮"})
        assert r2.status_code == 409 and r2.json()["error"]["code"] == "E_REPORT_NOT_SAVEABLE"
        r3 = c.post(f"{_BASE}/reports", json={"turn_id": "ghost", "title": "幽灵"})
        assert r3.status_code == 409


async def test_list_reports_with_q_filter():
    svc = make_services()
    await _saved_report(svc, title="大促GMV汇总")
    await _saved_report(svc, title="渠道明细")
    with make_client(svc) as c:
        r = c.get(f"{_BASE}/reports")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        assert set(items[0]) == {"id", "title", "caliber_summary", "data_time_range", "queried_at", "created_at"}
        r2 = c.get(f"{_BASE}/reports", params={"q": "GMV"})
        assert len(r2.json()["items"]) == 1
        assert r2.json()["items"][0]["title"] == "大促GMV汇总"
        r3 = c.get(f"{_BASE}/reports", params={"q": "不存在"})
        assert r3.json()["items"] == []
        # 分页校验
        assert c.get(f"{_BASE}/reports", params={"limit": 0}).status_code == 400
        assert c.get(f"{_BASE}/reports", params={"limit": 201}).status_code == 400


async def test_get_report_snapshot_readonly_spy():
    svc = make_services()
    spy = QueryRunnerSpy()
    svc.deps.query_runner = spy
    rep, _ = await _saved_report(svc)
    with make_client(svc) as c:
        r = c.get(f"{_BASE}/reports/{rep['id']}")
        assert r.status_code == 200
        body = r.json()
        # TR-8.2：零 run_chain / 零 analytics 调用
        assert svc.chain_runner.calls == []
        assert spy.calls == []
    # 直读快照：不出 query_spec/sql
    assert set(body) == {"id", "title", "question", "caliber", "snapshot", "data_time_range", "queried_at", "created_at", "updated_at"}
    assert "query_spec" not in body and "sql" not in body
    assert body["snapshot"]["insight"] == "渠道A GMV 领先，占比约 55%。"
    assert body["snapshot"]["table"]["rows"][0]["channel"] == "渠道A"
    assert body["caliber"]["summary"] == "大促三天 GMV 按渠道"


async def test_get_report_404():
    svc = make_services()
    with make_client(svc) as c:
        r = c.get(f"{_BASE}/reports/ghost")
        assert r.status_code == 404 and r.json()["error"]["code"] == "E_NOT_FOUND"


async def test_rename_and_delete():
    svc = make_services()
    rep, _ = await _saved_report(svc, title="原名")
    await _saved_report(svc, title="其他报表")
    with make_client(svc) as c:
        # 改名成功
        r = c.put(f"{_BASE}/reports/{rep['id']}", json={"title": "改名后"})
        assert r.status_code == 200
        assert r.json() == {"id": rep["id"], "title": "改名后"}
        # 空名 400
        assert c.put(f"{_BASE}/reports/{rep['id']}", json={"title": " "}).status_code == 400
        # 同名冲突（另一报表占用）409
        r2 = c.put(f"{_BASE}/reports/{rep['id']}", json={"title": "其他报表"})
        assert r2.status_code == 409
        # 改回自己的名字不冲突
        assert c.put(f"{_BASE}/reports/{rep['id']}", json={"title": "改名后"}).status_code == 200
        # 删除 204 → 404
        assert c.delete(f"{_BASE}/reports/{rep['id']}").status_code == 204
        assert c.delete(f"{_BASE}/reports/{rep['id']}").status_code == 404
        assert c.get(f"{_BASE}/reports/{rep['id']}").status_code == 404
