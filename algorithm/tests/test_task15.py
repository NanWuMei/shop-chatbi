"""Task 15 中段入口测试（FR-21/22，AC-18/19；checklist C38~C40）。

S5 刷新入口：start_at="S5" 从 gen_sql 起跑，四终态与主链同构；
S4 recalibrate 入口：start_at="S4" 强制澄清卡（不调 LLM、不执行 SQL）；
兼容性：不带新参数的主入口行为与既有用例完全一致（TR-15.5 冒烟 + 全量回归）。
"""
from __future__ import annotations

from typing import Any

import pytest

from algorithm.graph import run_chain
from algorithm.protocols import LLMUnavailableError
from algorithm.state import (
    Action,
    ComparisonMode,
    ComparisonSpec,
    DimSpec,
    Lineage,
    MetricSpec,
    Period,
    QuerySpec,
    TimeRange,
)

from .conftest import load_scenario, make_deps


def _spec(with_time: bool = True) -> QuerySpec:
    """渠道 GMV 规格（时间可选），枚举候选由 L0 dim_channel 提供。"""
    return QuerySpec(
        metrics=[
            MetricSpec(
                name="gmv",
                label="GMV",
                table="fact_order_item",
                expression="SUM(pay_amount - refund_amount)",
                agg="sum",
                fmt="money",
            )
        ],
        dimensions=[DimSpec(name="渠道", label="渠道", table="dim_channel", column="channel_name")],
        time_range=(
            TimeRange(start="2026-06-01", end="2026-06-20", label="618大促") if with_time else None
        ),
        sort="gmv desc",
        caliber_summary="GMV ｜ 按渠道" + (" ｜ 618大促" if with_time else ""),
    )


def _bad_sql_script() -> list[dict[str, Any]]:
    """两条白名单外表 SQL（schema 合法、lint 拒绝）。"""
    bad = {
        "sql": "SELECT secret_value FROM secret_table LIMIT 10",
        "lineage": Lineage(tables=["secret_table"], columns=["secret_value"]),
    }
    return [bad, bad]


async def test_s5_refresh_answer() -> None:
    """TR-15.1：刷新成功 → answer，path=S5,S6,S7,S8（不含 S1~S4）。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)
    al = scn["llm"]["aligner"][0]
    assert al.get("status") == "ok" and al.get("query_spec"), "t01 aligner 脚本应为 ok 分支"
    spec = QuerySpec.model_validate(al["query_spec"])

    result = await run_chain(query_spec=spec, start_at="S5", deps=deps, thread_id="r15-a")

    assert result.action == Action.ANSWER, f"实际 {result.action}（error={result.error}）"
    assert result.trace.path == ["S5", "S6", "S7", "S8"], f"path 不符：{result.trace.path}"
    assert result.answer is not None and len(result.answer.table.rows) > 0
    assert result.answer.insight  # S8 解读照常产出
    assert result.model_dump_json()  # 契约可序列化
    # service-only 契约字段（OQ-4）：刷新入参规格原样回传 + 执行 SQL 可供 internal 落库
    assert result.query_spec == spec, "service-only query_spec 应为刷新入参规格"
    assert result.sql, "service-only sql 应为 S5 生成并执行的 SQL"


async def test_s5_refresh_empty_result() -> None:
    """TR-15.1：0 行 → 空 answer（rows=[]、chart=null），不是拒答。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)
    spec = QuerySpec.model_validate(scn["llm"]["aligner"][0]["query_spec"])
    runner.set_script({"empty": True})

    result = await run_chain(query_spec=spec, start_at="S5", deps=deps, thread_id="r15-e")

    assert result.action == Action.ANSWER
    assert result.answer is not None
    assert result.answer.table.rows == []
    assert result.answer.chart is None
    assert result.answer.insight == "该范围内没有符合条件的数据。"
    assert result.trace.path == ["S5", "S6", "S7", "S8"]


async def test_s5_refresh_lint_exhausted() -> None:
    """TR-15.1：连续 2 轮 lint 不过 → query_gen_failed(GEN_LINT_EXHAUSTED)，path 只到 S5。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)
    llm.set_script("coder", _bad_sql_script())

    result = await run_chain(
        query_spec=_spec(), start_at="S5", deps=deps, thread_id="r15-l"
    )

    assert result.action == Action.QUERY_GEN_FAILED
    assert result.rejection is not None
    assert result.rejection.reason_code == "GEN_LINT_EXHAUSTED"
    assert result.trace.path == ["S5"], f"path 不符：{result.trace.path}"
    assert runner.call_count == 0  # 未执行任何 SQL


async def test_s5_refresh_query_timeout() -> None:
    """TR-15.1：Runner 超时 → query_failed(QUERY_TIMEOUT)。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)
    spec = QuerySpec.model_validate(scn["llm"]["aligner"][0]["query_spec"])
    runner.set_script({"timeout": True})

    result = await run_chain(query_spec=spec, start_at="S5", deps=deps, thread_id="r15-t")

    assert result.action == Action.QUERY_FAILED
    assert result.rejection is not None
    assert result.rejection.reason_code == "QUERY_TIMEOUT"


async def test_s5_refresh_llm_error() -> None:
    """TR-15.1：Coder 不可用 → error(E_LLM_UNAVAILABLE, retryable=true)。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)
    llm.set_script("coder", [LLMUnavailableError("mock coder 不可用")])

    result = await run_chain(query_spec=_spec(), start_at="S5", deps=deps, thread_id="r15-x")

    assert result.action == Action.ERROR
    assert result.error is not None
    assert result.error.code == "E_LLM_UNAVAILABLE"
    assert result.error.retryable is True


async def test_s5_refresh_with_comparison() -> None:
    """TR-15.2：带 ComparisonSpec 的刷新 → 对比图 + changes（与主链 T07 同构）。"""
    scn = load_scenario("t07")
    deps, llm, runner = make_deps(scn)
    al = scn["llm"]["aligner"][0]
    assert al.get("status") == "ok" and al.get("query_spec"), "t07 aligner 脚本应为 ok 分支"
    spec = QuerySpec.model_validate(al["query_spec"])
    assert spec.comparison is not None, "t07 QuerySpec 应带 ComparisonSpec"

    result = await run_chain(query_spec=spec, start_at="S5", deps=deps, thread_id="r15-c")

    assert result.action == Action.ANSWER, f"实际 {result.action}（error={result.error}）"
    a = result.answer
    assert a is not None and a.chart is not None
    assert a.chart.type == "grouped_bar"
    # changes 按相邻对计数（T07 三段 periods → 2 条变化），与主链同构
    assert a.comparison is not None
    assert len(a.comparison.changes) == len(spec.comparison.periods) - 1
    assert result.trace.path == ["S5", "S6", "S7", "S8"]


async def test_s4_recalibrate_clarify() -> None:
    """TR-15.3：recalibrate → 强制澄清卡（round=1、四码复用、L0 候选逐项重选）。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)  # llm 脚本全程不应被消费

    result = await run_chain(query_spec=_spec(with_time=True), start_at="S4", deps=deps, thread_id="r15-rc")

    assert result.action == Action.CLARIFY
    c = result.clarify
    assert c is not None
    assert c.round == 1
    assert c.reason_code == "METRIC_DIM_AMBIGUOUS"
    assert c.input_type == "single_choice"
    assert len(c.options) >= 1, f"逐项重选选项不足：{c.options}"
    assert c.allow_custom_text is True
    assert runner.call_count == 0  # 不执行 SQL
    assert llm.calls_of("aligner") == 0  # 不调 LLM
    assert llm.calls_of("understand") == 0
    assert result.trace.path == ["S4"]
    assert result.query_spec is not None  # service-only： recalibrate 源规格随返回体带回


async def test_s4_recalibrate_missing_time() -> None:
    """TR-15.3：原规格缺时间项 → time_quick 快捷补时间（档期四值）。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)

    result = await run_chain(query_spec=_spec(with_time=False), start_at="S4", deps=deps, thread_id="r15-rt")

    assert result.action == Action.CLARIFY
    c = result.clarify
    assert c is not None
    assert c.reason_code == "METRIC_DIM_AMBIGUOUS"
    assert c.input_type == "time_quick"
    assert len(c.options) >= 1, f"时间快捷选项不足：{c.options}"
    assert len(c.suggestions) >= 1  # 逐项重选引导
    assert runner.call_count == 0


async def test_recalibrate_confirm_reenter() -> None:
    """TR-15.4：确认后带 clarified_question+clarify_id 从 S1 重入并直达终态。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)
    first = await run_chain(query_spec=_spec(with_time=True), start_at="S4", deps=deps, thread_id="r15-re")
    assert first.action == Action.CLARIFY and first.clarify is not None

    second = await run_chain(
        clarified_question="618大促期间各渠道GMV，按从高到低排",
        clarify_id=first.clarify.clarify_id,
        deps=deps,
        thread_id="r15-re",
    )

    assert second.action == Action.ANSWER, f"重入终态不符：{second.action}（error={second.error}）"
    assert second.answer is not None and len(second.answer.table.rows) > 0
    assert runner.call_count == 1  # 重入后执行了一次查询


async def test_main_entry_unchanged() -> None:
    """TR-15.5：不带新参数的主入口行为不变（t01 冒烟，全量回归见 pytest 输出）。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)

    result = await run_chain(question=scn["question"], deps=deps, thread_id="r15-main")

    assert result.action == Action.ANSWER
    assert result.trace.path == scn["expect"]["path"]
    assert result.query_spec is not None and result.sql  # 主入口同样携带 service-only 字段


async def test_start_at_validation() -> None:
    """中段入口参数校验：非法值 / 缺 query_spec / 与澄清重入互斥。"""
    scn = load_scenario("t01")
    deps, llm, runner = make_deps(scn)

    with pytest.raises(ValueError, match="start_at"):
        await run_chain(start_at="S3", query_spec=_spec(), deps=deps)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="query_spec"):
        await run_chain(start_at="S5", deps=deps)
    with pytest.raises(ValueError, match="互斥"):
        await run_chain(start_at="S5", query_spec=_spec(), clarified_question="x", deps=deps)


def test_comparison_mode_enum_unchanged() -> None:
    """契约零变更守卫：ComparisonMode/澄清码枚举成员不变（后端/前端镜像依赖）。"""
    assert [m.value for m in ComparisonMode] == ["yoy", "mom", "custom"]
