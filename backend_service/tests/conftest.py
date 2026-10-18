"""api 测试总夹具（NFR-2 / AC-20）。

离线装配：同签名假 run_chain（场景脚本化）、内存仓储替身、内存注册表/缓冲、FakeQueryRunner；
不依赖 DB/key/网络。集成装配见 tests/integration/conftest.py。
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, Callable, Optional

import pytest

from algorithm.state import (
    Action,
    Answer,
    Caliber,
    CaliberDetail,
    ChainResult,
    ChartSpec,
    ChartType,
    ComparisonChange,
    ComparisonMode,
    ComparisonResult,
    ClarifyPayload,
    ClarifyOption,
    ClarifyReasonCode,
    ErrorPayload,
    InputType,
    Meta,
    MetricSpec,
    DimSpec,
    QuerySpec,
    Rejection,
    RejectionReasonCode,
    RejectionSuggestion,
    TableColumn,
    TableData,
    TimeRange,
    Trace,
)

from backend_service.application.conversation_service import ConversationService, TicketRegistry
from backend_service.application.report_service import ReportService
from backend_service.config import ApiConfig

# ---------------------------------------------------------------------------
# 内存仓储替身（与 storage/repositories 同接口）
# ---------------------------------------------------------------------------


class FakeSessionRepo:
    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}

    def create(self, *, title: str, session_id: Optional[str] = None, inherited_spec: Optional[dict] = None) -> dict:
        sid = session_id or str(uuid.uuid4())
        m = {
            "id": sid,
            "title": title,
            "owner_id": "default",
            "inherited_spec": inherited_spec,
            "message_count": 0,
            "last_question_at": None,
            "created_at": "2026-06-18T00:00:00Z",
            "updated_at": "2026-06-18T00:00:00Z",
        }
        self.sessions[sid] = m
        return dict(m)

    def get(self, session_id: str) -> Optional[dict]:
        m = self.sessions.get(session_id)
        return dict(m) if m else None

    def list(self, *, offset: int = 0, limit: int = 50) -> list[dict]:
        items = sorted(
            self.sessions.values(),
            key=lambda m: (m["last_question_at"] or "", m["created_at"]),
            reverse=True,
        )
        return [dict(m) for m in items[offset : offset + limit]]

    def delete(self, session_id: str) -> bool:
        return self.sessions.pop(session_id, None) is not None


class FakeMessageRepo:
    def __init__(self, session_repo: FakeSessionRepo) -> None:
        self._sessions = session_repo
        self.messages: list[dict] = []

    def append(self, session_id: str, *, type: str, payload: dict, internal: Optional[dict] = None, touch_question: bool = False) -> dict:
        s = self._sessions.sessions.get(session_id)
        if s is None:
            raise ValueError(f"会话不存在：{session_id}")
        seq = max([m["seq"] for m in self.messages if m["session_id"] == session_id], default=0) + 1
        m = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "seq": seq,
            "type": type,
            "payload": payload,
            "internal": internal,
            "created_at": "2026-06-18T00:00:01Z",
        }
        self.messages.append(m)
        s["message_count"] += 1
        if touch_question:
            s["last_question_at"] = "2026-06-18T00:00:01Z"
        return dict(m)

    def list_by_session(self, session_id: str) -> list[dict]:
        return [dict(m) for m in sorted(self.messages, key=lambda m: m["seq"]) if m["session_id"] == session_id]

    def count_by_session(self, session_id: str) -> int:
        return sum(1 for m in self.messages if m["session_id"] == session_id)

    def find_answer_by_turn(self, turn_id: str) -> Optional[dict]:
        found = [m for m in self.messages if m["type"] == "answer" and m["payload"].get("turn_id") == turn_id]
        return dict(found[-1]) if found else None

    def find_clarification(self, clarify_id: str) -> Optional[dict]:
        found = [m for m in self.messages if m["type"] == "clarification" and m["payload"].get("clarify_id") == clarify_id]
        return dict(found[-1]) if found else None

    def update_clarification_status(self, clarify_id: str, status: str) -> bool:
        for m in reversed(self.messages):
            if m["type"] == "clarification" and m["payload"].get("clarify_id") == clarify_id:
                m["payload"] = {**m["payload"], "status": status}
                return True
        return False


class FakeReportRepo:
    _REQUIRED = ("title", "question", "caliber", "snapshot", "queried_at")

    def __init__(self) -> None:
        self.reports: dict[str, dict] = {}

    def get(self, report_id: str) -> Optional[dict]:
        r = self.reports.get(report_id)
        return dict(r) if r else None

    def find_by_title(self, owner_id: str, title: str) -> Optional[dict]:
        for r in self.reports.values():
            if r["owner_id"] == owner_id and r["title"] == title:
                return dict(r)
        return None

    def insert(self, owner_id: str, fields: dict) -> dict:
        missing = [k for k in self._REQUIRED if not fields.get(k)]
        if missing:
            raise ValueError(f"报表字段缺失，整体回滚：{','.join(missing)}")
        rid = str(uuid.uuid4())
        r = {"id": rid, "owner_id": owner_id, **fields, "created_at": "2026-06-18T00:00:00Z", "updated_at": "2026-06-18T00:00:00Z"}
        self.reports[rid] = r
        return dict(r)

    def overwrite(self, report_id: str, fields: dict) -> dict:
        missing = [k for k in self._REQUIRED if not fields.get(k)]
        if missing:
            raise ValueError(f"报表字段缺失，整体回滚：{','.join(missing)}")
        if report_id not in self.reports:
            raise ValueError("报表不存在")
        r = self.reports[report_id]
        r.update({k: v for k, v in fields.items() if v is not None or k in self._REQUIRED})
        r["updated_at"] = "2026-06-18T09:00:00Z"
        return dict(r)

    def list(self, owner_id: str, *, q: Optional[str] = None, offset: int = 0, limit: int = 50) -> list[dict]:
        items = [r for r in self.reports.values() if r["owner_id"] == owner_id]
        if q:
            items = [r for r in items if q in r["title"]]
        items.sort(key=lambda r: r["created_at"], reverse=True)
        return [dict(r) for r in items[offset : offset + limit]]

    def rename(self, report_id: str, title: str) -> Optional[dict]:
        r = self.reports.get(report_id)
        if r is None:
            return None
        r["title"] = title
        r["updated_at"] = "2026-06-18T09:00:00Z"
        return dict(r)

    def delete(self, report_id: str) -> bool:
        return self.reports.pop(report_id, None) is not None


# ---------------------------------------------------------------------------
# 假 run_chain：同签名，脚本化返回 + 记录入参（断言接缝用）
# ---------------------------------------------------------------------------


def make_chain_runner(script: Optional[list[ChainResult]] = None) -> Callable[..., Any]:
    calls: list[dict] = []

    async def runner(**kwargs) -> ChainResult:
        calls.append(kwargs)
        if script is not None:
            return script.pop(0)
        raise AssertionError("chain_runner 被未预期的调用触发")

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def make_slow_chain_runner(result: ChainResult, delay: float = 30.0) -> Callable[..., Any]:
    async def runner(**kwargs) -> ChainResult:
        await asyncio.sleep(delay)
        return result

    return runner


# ---------------------------------------------------------------------------
# ChainResult 构造器（六 action 场景）
# ---------------------------------------------------------------------------

DEFAULT_QSPEC = QuerySpec(
    metrics=[MetricSpec(name="gmv", label="GMV", table="fact_order_item", expression="SUM(paid_amount)")],
    dimensions=[DimSpec(name="channel", label="渠道", table="dim_channel", column="channel_name")],
    time_range=TimeRange(start="2026-06-16", end="2026-06-18", label="本期大促·正式期"),
    caliber_summary="大促三天 GMV 按渠道",
)


def make_table(rows: list[dict]) -> TableData:
    return TableData(
        columns=[TableColumn(field="channel", label="渠道", format="text"), TableColumn(field="gmv", label="GMV", format="money")],
        rows=rows,
    )


def make_answer_result(
    *,
    turn_id: str = "turn-1",
    question: str = "618 各渠道 GMV",
    rows: Optional[list[dict]] = None,
    chart: Optional[ChartSpec] = None,
    comparison: Optional[ComparisonResult] = None,
    query_spec: Optional[QuerySpec] = DEFAULT_QSPEC,
    sql: Optional[str] = "SELECT channel, SUM(amount) FROM dw.fact_order_item GROUP BY 1 LIMIT 500",
    caliber_summary: str = "大促三天 GMV 按渠道",
) -> ChainResult:
    rows = rows if rows is not None else [{"channel": "渠道A", "gmv": "120000.00"}, {"channel": "渠道B", "gmv": "98000.00"}]
    return ChainResult(
        action=Action.ANSWER,
        answer=Answer(
            table=make_table(rows),
            chart=chart,
            insight="渠道A GMV 领先，占比约 55%。",
            caliber=Caliber(summary=caliber_summary, detail=CaliberDetail(
                metrics=["GMV"], dimensions=["渠道"], time_range="2026-06-16~2026-06-18",
                filters=["已支付"], comparison=None,
            )),
            comparison=comparison,
        ),
        trace=Trace(path=["S1", "S3", "S4", "S5", "S6", "S7", "S8"], lint_rounds=1, llm_calls=3, elapsed_ms=4200),
        meta=Meta(turn_id=turn_id, question=question),
        query_spec=query_spec,
        sql=sql,
    )


def make_clarify_result(
    *,
    turn_id: str = "turn-1",
    question: str = "美妆 GMV 怎么样",
    clarify_id: str = "cl-1",
    input_type: InputType = InputType.SINGLE_CHOICE,
    round: int = 1,
) -> ChainResult:
    return ChainResult(
        action=Action.CLARIFY,
        clarify=ClarifyPayload(
            clarify_id=clarify_id,
            round=round,
            title="「美妆」想看哪个范围？",
            reason_code=ClarifyReasonCode.METRIC_DIM_AMBIGUOUS,
            input_type=input_type,
            options=[
                ClarifyOption(value="美妆个护", label="美妆个护（一级类目整体）"),
                ClarifyOption(value="彩妆", label="彩妆"),
                ClarifyOption(value="护肤", label="护肤"),
                ClarifyOption(value="美妆工具", label="美妆工具"),
            ],
            allow_custom_text=True,
        ),
        trace=Trace(path=["S1", "S3", "S4"], llm_calls=1),
        meta=Meta(turn_id=turn_id, question=question),
        query_spec=None,
        sql=None,
    )


def make_rejection_result(
    *,
    turn_id: str = "turn-1",
    question: str = "明年 GMV 预测",
    action: Action = Action.NOT_ANSWERABLE,
    reason_code: RejectionReasonCode = RejectionReasonCode.NOT_DATA_QUESTION,
) -> ChainResult:
    assert action in (Action.NOT_ANSWERABLE, Action.QUERY_GEN_FAILED, Action.QUERY_FAILED)
    return ChainResult(
        action=action,
        rejection=Rejection(
            reason_code=reason_code,
            reason_text="这个超出了可答范围，可以试试已有数据的问法。",
            suggestions=[RejectionSuggestion(label="换个问法", question="618 各渠道 GMV")],
        ),
        trace=Trace(path=["S1", "S4"], llm_calls=1),
        meta=Meta(turn_id=turn_id, question=question),
        query_spec=DEFAULT_QSPEC if action != Action.NOT_ANSWERABLE else None,
        sql=None if action == Action.NOT_ANSWERABLE else "SELECT 1",
    )


def make_error_result(*, turn_id: str = "turn-1", question: str = "618 GMV", code: str = "E_LLM_UNAVAILABLE") -> ChainResult:
    return ChainResult(
        action=Action.ERROR,
        error=ErrorPayload(code=code, message="服务繁忙，请稍后重试", retryable=True),
        trace=Trace(path=["S1"], llm_calls=1),
        meta=Meta(turn_id=turn_id, question=question),
        query_spec=None,
        sql=None,
    )


def make_empty_answer_result(**kw) -> ChainResult:
    kw.setdefault("question", "营销费用的 GMV")
    return make_answer_result(rows=[], **kw)


# ---------------------------------------------------------------------------
# 服务与应用装配（离线）
# ---------------------------------------------------------------------------


def make_services(
    *,
    chain_runner: Optional[Callable[..., Any]] = None,
    config: Optional[ApiConfig] = None,
    clock: Optional[Callable[[], float]] = None,
    slow_first: bool = False,
) -> SimpleNamespace:
    """装配内存版服务组：session/message/report 仓储 + conversation + reports。"""
    config = config or ApiConfig()
    session_repo = FakeSessionRepo()
    message_repo = FakeMessageRepo(session_repo)
    report_repo = FakeReportRepo()
    runner = chain_runner or make_chain_runner()
    deps = SimpleNamespace(query_runner=None)
    conversation = ConversationService(
        config=config,
        chain_runner=runner,
        deps=deps,
        checkpointer=object(),
        session_repo=session_repo,
        message_repo=message_repo,
        clock=clock,
    )
    reports = ReportService(
        config=config,
        chain_runner=runner,
        deps=deps,
        report_repo=report_repo,
        message_repo=message_repo,
        session_repo=session_repo,
    )
    return SimpleNamespace(
        config=config,
        session_repo=session_repo,
        message_repo=message_repo,
        report_repo=report_repo,
        conversation=conversation,
        reports=reports,
        chain_runner=runner,
        deps=deps,
    )


def make_app_ctx(services: SimpleNamespace, *, probes: Optional[dict] = None) -> SimpleNamespace:
    """路由层消费的 ctx 形状（与 composition.AppContext 鸭子类型兼容）。"""
    return SimpleNamespace(
        config=services.config,
        session_repo=services.session_repo,
        message_repo=services.message_repo,
        report_repo=services.report_repo,
        conversation=services.conversation,
        reports=services.reports,
        probes=probes or {"db": lambda: "ok", "llm": lambda: "unconfigured", "embedding": lambda: "unconfigured"},
        deps=services.deps,
    )


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def services() -> SimpleNamespace:
    return make_services()


@pytest.fixture()
def app_ctx(services: SimpleNamespace) -> SimpleNamespace:
    return make_app_ctx(services)


@pytest.fixture()
def client(app_ctx: SimpleNamespace):
    from fastapi.testclient import TestClient

    from backend_service.config import load_config
    from backend_service.main import create_app

    config = load_config({})
    with TestClient(create_app(config, app_ctx)) as c:  # with：触发 lifespan（ctx 自带 startup 替身时跳过）
        yield c


def make_client(services: SimpleNamespace, *, probes: Optional[dict] = None):
    """按需装配的 TestClient（未进入上下文；测试用 `with make_client(svc) as c:` 保证后台任务存活）。"""
    from fastapi.testclient import TestClient

    from backend_service.config import load_config
    from backend_service.main import create_app

    return TestClient(create_app(load_config({}), make_app_ctx(services, probes=probes)))
