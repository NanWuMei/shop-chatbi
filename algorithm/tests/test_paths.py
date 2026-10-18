"""专项路径测试（TR-14.3）：S2 命中/空库、lexical 降级、lint 超轮、超时/错误、
LLM 不可用、空结果、澄清两轮转拒答、checkpointer 重入恢复、无 key build、模型档位、归因拒答文案。
"""
from __future__ import annotations

import pytest

from algorithm.config import Settings, load_settings
from algorithm.graph import build_graph, run_chain
from algorithm.protocols import (
    Deps,
    LLMUnavailableError,
    Resources,
)
from algorithm.retrieval.repo import InMemoryRepository
from algorithm.state import E_LLM_UNAVAILABLE, Exemplar
from algorithm.tests.mocks.mock_embeddings import MockEmbeddingClient
from algorithm.tests.mocks.mock_llm import MockLLMClient
from algorithm.tests.mocks.mock_query_runner import MockQueryRunner
from algorithm.tests.mocks.static_schema import StaticSchemaProvider
from algorithm.agents.understand.agent_schemas import IntentSpec as UnderstandOutput

from .conftest import assert_expect, load_scenario, make_deps

# ---------------------------------------------------------------------------
# S2 语义缓存：命中 vs 空库
# ---------------------------------------------------------------------------

_HIT_RESOURCES = Resources(
    calendar={"618大促期间": ["2026-06-01", "2026-06-20"]},
    templates=[
        {
            "id": "tpl_channel_gmv",
            "match": {"metrics": ["gmv"], "dimensions": ["渠道"], "allow_sort": True},
            "sql": (
                "SELECT c.channel_name, SUM(o.gmv_amount) AS gmv FROM fact_order o "
                "JOIN dim_channel c ON o.channel_id = c.channel_id "
                "WHERE o.pay_status = '已支付' AND o.order_date BETWEEN '{start}' AND '{end}' "
                "GROUP BY c.channel_name ORDER BY gmv DESC"
            ),
            "chart_type": "bar",
        }
    ],
)


async def test_s2_template_hit_skips_s3_s4_s5() -> None:
    scn = load_scenario("t01")
    # 命中路径不调 aligner/coder：脚本只留 understand/writer
    scn["llm"] = {"understand": scn["llm"]["understand"], "writer": scn["llm"]["writer"]}
    deps, llm, runner = make_deps(scn, resources=_HIT_RESOURCES)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-s2-hit")
    assert_expect(
        r,
        {
            "action": "answer",
            "path": ["S1", "S2", "S6", "S7", "S8"],
            "template_hit": True,
            "chart": "bar",
            "llm_agent_calls": {"understand": 1, "aligner": 0, "coder": 0, "writer": 1},
        },
        runner,
        llm,
    )
    assert "2026-06-01" in runner.executed_sql[0] and "{start}" not in runner.executed_sql[0]
    assert any("命中模板 tpl_channel_gmv" in n for n in r.trace.notes)


async def test_s2_empty_template_lib_goes_s3() -> None:
    scn = load_scenario("t01")  # 默认空资源 → 未命中走 S3（正常分叉非失败）
    deps, llm, runner = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-s2-miss")
    assert r.trace.template_hit is False
    assert "S2" not in r.trace.path  # 未命中是决策点，不进 path
    assert r.trace.path[:2] == ["S1", "S3"]


# ---------------------------------------------------------------------------
# S3 检索降级
# ---------------------------------------------------------------------------


async def test_retrieval_lexical_when_embedding_unavailable() -> None:
    scn = load_scenario("t01")
    deps, _, _ = make_deps(scn, embedding=MockEmbeddingClient(available=False))
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-lex-1")
    assert r.trace.retrieval_mode == "lexical"


async def test_retrieval_lexical_when_embedding_fails() -> None:
    scn = load_scenario("t01")
    deps, _, _ = make_deps(scn, embedding=MockEmbeddingClient(available=True, fail=True))
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-lex-2")
    assert r.trace.retrieval_mode == "lexical"
    assert any("降级 lexical" in n for n in r.trace.notes)


async def test_retrieval_vector_channel_when_available() -> None:
    scn = load_scenario("t01")
    emb = MockEmbeddingClient(available=True)
    repo = InMemoryRepository()
    vec = (await emb.embed(["各渠道GMV排名"]))[0]
    await repo.upsert_exemplar(
        Exemplar(id="ex-gmv-1", question="各渠道GMV排名", sql="SELECT ...", tags=["gmv"]),
        embedding=vec,
    )
    deps, _, _ = make_deps(scn, embedding=emb, repository=repo)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-vec-1")
    assert r.trace.retrieval_mode == "vector"


# ---------------------------------------------------------------------------
# S5 lint 超轮
# ---------------------------------------------------------------------------


async def test_lint_exhausted_maps_query_gen_failed() -> None:
    scn = load_scenario("t01")
    bad = {
        "sql": "SELECT o.no_such_col FROM fact_order o",
        "lineage": {"tables": ["fact_order"], "columns": ["no_such_col"], "calibers": [], "exemplar_ids": []},
    }
    scn["llm"]["coder"] = [dict(bad), dict(bad)]  # 两轮都生成坏 SQL
    deps, llm, runner = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-lint-x")
    assert_expect(
        r,
        {
            "action": "query_gen_failed",
            "reason_code": "GEN_LINT_EXHAUSTED",
            "lint_rounds": 2,
            "llm_agent_calls": {"coder": 2, "writer": 0},
        },
        runner,
        llm,
    )
    assert runner.call_count == 0  # lint 不过的 SQL 绝不执行


# ---------------------------------------------------------------------------
# S6 执行异常
# ---------------------------------------------------------------------------


async def test_query_timeout_maps_query_failed() -> None:
    scn = load_scenario("t01")
    scn["runner"] = {"timeout": True}
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-timeout")
    assert_expect(
        r,
        {"action": "query_failed", "reason_code": "QUERY_TIMEOUT", "suggestions_min": 1},
    )
    assert r.trace.path[-1] == "S6"


async def test_query_error_maps_query_failed_plain_text() -> None:
    scn = load_scenario("t01")
    scn["runner"] = {"error": "boom: relation xxx does not exist"}
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-qerr")
    assert_expect(
        r,
        {"action": "query_failed", "reason_code": "QUERY_ERROR", "suggestions_min": 1},
    )
    assert "boom" not in r.rejection.reason_text  # 技术细节只进 trace，不见用户


# ---------------------------------------------------------------------------
# LLM 不可用（节点内重试 1 次后 error）
# ---------------------------------------------------------------------------


async def test_llm_unavailable_maps_error_retryable() -> None:
    scn = load_scenario("t01")
    scn["llm"] = {}  # 无脚本 → Mock 抛 LLMUnavailableError
    deps, llm, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-llm-x")
    assert_expect(
        r,
        {
            "action": "error",
            "error_code": E_LLM_UNAVAILABLE,
            "retryable": True,
            "llm_agent_calls": {"understand": 2},  # 首次 + 节点内重试 1 次
        },
        llm=llm,
    )


# ---------------------------------------------------------------------------
# 空结果：如实空表 + 固定文案，不拒答不硬画图
# ---------------------------------------------------------------------------


async def test_empty_result_still_answers() -> None:
    scn = load_scenario("t01")
    scn["runner"] = {"empty": True, "columns": ["channel_name", "gmv"]}
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-empty")
    assert_expect(
        r,
        {
            "action": "answer",
            "chart": None,
            "rows": 0,
            "insight_equals": "该范围内没有符合条件的数据。",
        },
    )


# ---------------------------------------------------------------------------
# 澄清两轮转拒答 + checkpointer 重入恢复
# ---------------------------------------------------------------------------


async def test_clarify_two_rounds_then_not_answerable() -> None:
    scn = load_scenario("t09")
    scn["llm"]["understand"] = scn["llm"]["understand"] + [dict(scn["llm"]["understand"][0])]
    scn["llm"]["aligner"] = scn["llm"]["aligner"] + [dict(scn["llm"]["aligner"][0])]
    deps, _, _ = make_deps(scn)
    tid = "spec-clarify-2r"
    r1 = await run_chain(question=scn["question"], deps=deps, thread_id=tid)
    assert r1.action == "clarify" and r1.clarify is not None and r1.clarify.round == 1

    r2 = await run_chain(
        clarified_question="还是美妆那个，随便看看",
        clarify_id=r1.clarify.clarify_id,
        deps=deps,
        thread_id=tid,
    )
    assert_expect(
        r2,
        {
            "action": "not_answerable",
            "reason_code": "NO_MATCHING_DATA",
            "path": ["S1", "S3", "S4"],
            "suggestions_min": 1,
        },
    )


async def test_reentry_recovers_from_checkpoint() -> None:
    """T05 双程：第一轮澄清入档 → 同 thread 重入后全链重跑出答案（MemorySaver 恢复 round）。"""
    scn = load_scenario("t05")
    deps, _, _ = make_deps(scn)
    tid = "spec-reentry"
    r1 = await run_chain(question=scn["question"], deps=deps, thread_id=tid)
    assert r1.action == "clarify" and r1.clarify is not None and r1.clarify.clarify_id

    r2 = await run_chain(
        clarified_question=scn["reentry"]["clarified_question"],
        clarify_id=r1.clarify.clarify_id,
        deps=deps,
        thread_id=tid,
    )
    assert r2.action == "answer"
    assert r2.trace.path == ["S1", "S3", "S4", "S5", "S6", "S7", "S8"]  # 重入全链重跑，无残留
    assert r2.trace.llm_calls == 4  # 新一轮四 agent 各 1 次（上轮计数已复位）


# ---------------------------------------------------------------------------
# 无 key build：import/构图/工厂不报错，问数时才 E_LLM_UNAVAILABLE
# ---------------------------------------------------------------------------


async def test_build_without_keys_no_error() -> None:
    settings = load_settings(env={})  # 全缺省不抛错
    assert settings.llm_configured is False
    graph = build_graph()  # 构图不依赖 key
    assert graph is not None

    from algorithm.llm.client import build_llm_client

    client = build_llm_client(settings)  # 工厂延迟构建，无 key 不报错
    with pytest.raises(LLMUnavailableError):
        await client.complete(agent="understand", tier="fast", messages=[], schema=UnderstandOutput)

    # 真实客户端无 key 问数 → error(E_LLM_UNAVAILABLE)，而非异常/崩溃
    deps = Deps(
        settings=settings,
        llm=client,
        schema_provider=StaticSchemaProvider(),
        query_runner=MockQueryRunner({}),
        embedding=None,
        repository=None,
        resources=Resources(),
    )
    r = await run_chain(question="测试问法", deps=deps, thread_id="spec-nokey")
    assert r.action == "error" and r.error is not None and r.error.code == E_LLM_UNAVAILABLE


# ---------------------------------------------------------------------------
# 模型档位 + 归因拒答文案
# ---------------------------------------------------------------------------


async def test_model_tiers_per_agent() -> None:
    scn = load_scenario("t01")
    deps, llm, _ = make_deps(scn)
    await run_chain(question=scn["question"], deps=deps, thread_id="spec-tier")
    tier_by_agent = {c["agent"]: c["tier"] for c in llm.calls}
    assert tier_by_agent == {
        "understand": "fast",
        "aligner": "strong",
        "coder": "strong",
        "writer": "fast",
    }


async def test_attribution_rejection_plain_text() -> None:
    scn = load_scenario("t15")
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-t15")
    assert r.rejection is not None
    assert r.rejection.reason_text == "我不算原因，但可以给你相关数据。"
    assert len(r.rejection.suggestions) >= 1  # 给数据入口，不给因果结论


# ---------------------------------------------------------------------------
# S7 趋势长转宽 + 澄清零候选降级（第3轮实测 bug 回归）
# ---------------------------------------------------------------------------


async def test_trend_long_table_pivoted_to_wide() -> None:
    """T03 趋势：S7 把「日期+渠道+GMV」长表透视为宽表，表图同形（前端 mapper 只消费 table rows）。"""
    scn = load_scenario("t03")
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-pivot")
    a = r.answer
    assert a is not None and a.chart is not None and a.chart.type == "trend_line"
    assert [c.field for c in a.table.columns] == ["order_date", "渠道A", "渠道B"]
    assert len(a.table.rows) == 3  # 3 天 × 2 渠道长表 → 3 行宽表
    assert a.table.rows[1]["渠道A"] == "520000.00"  # 数值与长表一致不错位
    assert a.chart.x_field == "order_date"
    assert [s.field for s in a.chart.series] == ["渠道A", "渠道B"]


async def test_clarify_empty_candidates_degrades_to_suggestions() -> None:
    """枚举零候选时不得发空 single_choice（前端确认钮置灰死卡）：降级 question_suggestions 且建议非空。"""
    scn = load_scenario("t05")
    scn["llm"]["aligner"] = [
        {"status": "clarify", "clarify_reason": "METRIC_DIM_AMBIGUOUS", "clarify_focus": "宇宙飞船"}
    ]
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-clarify-empty")
    c = r.clarify
    assert r.action == "clarify" and c is not None
    assert c.input_type == "question_suggestions"
    assert len(c.suggestions) >= 1  # 前端建议为空即死卡，必须兜底


async def test_clarify_focus_suffix_strip_recovers_candidates() -> None:
    """focus 带「类目/品类/类别」后缀（如「美妆类目」）剥尾重查枚举，仍能出 single_choice 选项。"""
    scn = load_scenario("t05")
    scn["llm"]["aligner"] = [
        {"status": "clarify", "clarify_reason": "METRIC_DIM_AMBIGUOUS", "clarify_focus": "美妆类目"}
    ]
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-clarify-suffix")
    c = r.clarify
    assert r.action == "clarify" and c is not None
    assert c.input_type == "single_choice"
    assert len(c.options) >= 2  # 剥尾后命中「美妆个护」等枚举值


async def test_lint_cte_reference_with_alias_passes() -> None:
    """T02 实测 bug：CTE 以别名引用（FROM payers p）合法，lint 不得误杀（曾判「未知表/别名 p」两轮拒答）。"""
    scn = load_scenario("t02")
    scn["llm"]["coder"] = [
        {
            "sql": (
                "WITH payers AS ("
                "SELECT o.channel_id, COUNT(DISTINCT o.customer_id) AS pay_converted_customers "
                "FROM fact_order o WHERE o.pay_status = '已支付' "
                "AND o.order_date BETWEEN '2026-06-01' AND '2026-06-20' GROUP BY o.channel_id"
                "), traffic AS ("
                "SELECT t.channel_id, SUM(t.visitors) AS visitors "
                "FROM fact_traffic_daily t WHERE t.date BETWEEN '2026-06-01' AND '2026-06-20' "
                "GROUP BY t.channel_id) "
                "SELECT ch.channel_name, "
                "ROUND(p.pay_converted_customers * 100.0 / NULLIF(tr.visitors, 0), 1) AS conversion_rate "
                "FROM payers p JOIN traffic tr ON p.channel_id = tr.channel_id "
                "JOIN dim_channel ch ON p.channel_id = ch.channel_id "
                "ORDER BY conversion_rate DESC"
            ),
            "lineage": {
                "tables": ["fact_order", "dim_channel", "fact_traffic_daily"],
                "columns": ["channel_name", "customer_id", "visitors", "channel_id", "order_date", "pay_status", "date"],
                "calibers": ["转化率=已支付客户数/访客数UV×100%"],
                "exemplar_ids": [],
            },
        }
    ]
    deps, _, runner = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-lint-cte")
    assert r.action == "answer", f"CTE+别名 SQL 应过 lint 出数：{r.rejection}"
    assert runner.call_count == 1


async def test_clarify_vague_empty_suggestions_gets_fallback() -> None:
    """T05 实测 bug ③：VAGUE 卡 LLM 不给建议时不得发空 question_suggestions（前端死卡），统一保底建议。"""
    scn = load_scenario("t05")
    scn["llm"]["aligner"] = [
        {"status": "clarify", "clarify_reason": "VAGUE", "clarify_title": "请选择类目的展示粒度"}
    ]
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-clarify-vague")
    c = r.clarify
    assert r.action == "clarify" and c is not None
    assert c.input_type == "question_suggestions"
    assert len(c.suggestions) >= 1  # 空建议即死卡，必须兜底


async def test_lint_derived_table_alias_and_prefixed_lineage_pass() -> None:
    """T02 实测 bug ②：子查询派生表别名（(SELECT ...) d1）与带 dw. 前缀的 lineage 不得被 lint 误杀。"""
    scn = load_scenario("t02")
    scn["llm"]["coder"] = [
        {
            "sql": (
                "SELECT ch.channel_name, "
                "ROUND(d1.pay_converted_customers * 100.0 / NULLIF(d2.visitors, 0), 1) AS conversion_rate "
                "FROM (SELECT o.channel_id, COUNT(DISTINCT o.customer_id) AS pay_converted_customers "
                "FROM fact_order o WHERE o.pay_status = '已支付' "
                "AND o.order_date BETWEEN '2026-06-01' AND '2026-06-20' GROUP BY o.channel_id) d1 "
                "JOIN (SELECT t.channel_id, SUM(t.visitors) AS visitors "
                "FROM fact_traffic_daily t WHERE t.date BETWEEN '2026-06-01' AND '2026-06-20' "
                "GROUP BY t.channel_id) d2 ON d1.channel_id = d2.channel_id "
                "JOIN dim_channel ch ON d1.channel_id = ch.channel_id "
                "ORDER BY conversion_rate DESC"
            ),
            "lineage": {
                "tables": ["dw.fact_order", "dw.dim_channel", "dw.fact_traffic_daily"],
                "columns": ["fact_order.channel_id", "fact_order.customer_id", "fact_order.order_date",
                            "fact_order.pay_status", "fact_traffic_daily.visitors", "fact_traffic_daily.date",
                            "dim_channel.channel_name"],
                "calibers": ["转化率=已支付客户数/访客数UV×100%"],
                "exemplar_ids": [],
            },
        }
    ]
    deps, _, runner = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-lint-derived")
    assert r.action == "answer", f"派生表别名+前缀 lineage 应过 lint 出数：{r.rejection}"
    assert runner.call_count == 1


async def test_trend_pivot_with_aliased_dims_and_grain_variant() -> None:
    """T03 实测 bug：Coder 把维度别名成中文 + grain=daily 变体时，S7 仍须透视（形态触发，不依赖图型先判）。"""
    scn = load_scenario("t03")
    scn["llm"]["aligner"][0]["query_spec"]["grain"] = "daily"  # aligner 实测产出变体
    scn["llm"]["aligner"][0]["query_spec"]["dimensions"] = [
        {"name": "渠道", "label": "渠道名称", "table": "dim_channel", "column": "channel_name"},
        {"name": "天", "label": "日期", "table": "fact_order", "column": "order_date"},
    ]
    scn["llm"]["coder"][0]["sql"] = (
        'SELECT c.channel_name AS "渠道", o.order_date AS "天", SUM(o.gmv_amount) AS gmv '
        "FROM fact_order o JOIN dim_channel c ON o.channel_id = c.channel_id "
        "WHERE o.pay_status = '已支付' AND o.order_date BETWEEN '2026-06-16' AND '2026-06-18' "
        "GROUP BY c.channel_name, o.order_date ORDER BY o.order_date, c.channel_name"
    )
    scn["runner"] = {
        "columns": ["渠道", "天", "gmv"],
        "rows": [
            {"渠道": "渠道A", "天": "2026-06-16", "gmv": "380000.00"},
            {"渠道": "渠道B", "天": "2026-06-16", "gmv": "290000.00"},
            {"渠道": "渠道A", "天": "2026-06-17", "gmv": "520000.00"},
            {"渠道": "渠道B", "天": "2026-06-17", "gmv": "350000.00"},
            {"渠道": "渠道A", "天": "2026-06-18", "gmv": "410000.00"},
            {"渠道": "渠道B", "天": "2026-06-18", "gmv": "310000.00"},
        ],
    }
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-pivot-alias")
    a = r.answer
    assert a is not None and a.chart is not None and a.chart.type == "trend_line"
    assert [c.field for c in a.table.columns] == ["天", "渠道A", "渠道B"]
    assert len(a.table.rows) == 3
    assert a.table.rows[1]["渠道A"] == "520000.00"  # 透视不错位
    assert a.chart.x_field == "天"
    assert [s.field for s in a.chart.series] == ["渠道A", "渠道B"]


async def test_comparison_changes_lenient_period_label_match() -> None:
    """T07 实测 bug：SQL period 字面值（前一周/后一周）与 spec label（大促前一周/大促后一周）不一致时，
    S7 仍须配对算出环比 changes（唯一互相包含即配对），不得 changes=[]。"""
    scn = load_scenario("t07")
    periods = scn["llm"]["aligner"][0]["query_spec"]["comparison"]["periods"]
    periods[0]["label"] = "大促前一周"
    periods[1]["label"] = "大促期间"
    periods[2]["label"] = "大促后一周"
    scn["llm"]["coder"][0]["sql"] = scn["llm"]["coder"][0]["sql"].replace("'当期'", "'大促期间'")
    scn["runner"] = {  # 实测行值（对齐真实 LLM 产出的字面值）
        "columns": ["period_key", "gmv"],
        "rows": [
            {"period_key": "前一周", "gmv": "1183194.10"},
            {"period_key": "大促期间", "gmv": "1951555.67"},
            {"period_key": "后一周", "gmv": "1009383.02"},
        ],
    }
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-t07-lenient")
    a = r.answer
    assert a is not None and a.comparison is not None
    assert [p for p in a.comparison.periods] == ["大促前一周", "大促期间", "大促后一周"]
    assert len(a.comparison.changes) == 2  # 两对环比全部配对算出
    assert a.comparison.changes[0].value_delta == "768361.57"  # 1951555.67-1183194.10
    assert a.comparison.changes[0].rate_delta == "64.9"


async def test_comparison_value_field_case_insensitive() -> None:
    """T08 实测 bug：aligner 指标名 GMV（大写）/value_fields=[GMV]，SQL 列 gmv（小写）时
    changes 不得因大小写漂移落空；表格列 label/format 也应命中规格业务名。"""
    scn = load_scenario("t08")
    spec = scn["llm"]["aligner"][0]["query_spec"]
    spec["metrics"][0]["name"] = "GMV"  # 实测 aligner 产出大写指标名
    spec["metrics"][0]["label"] = ""
    spec["comparison"]["value_fields"] = ["GMV"]
    spec["comparison"]["periods"] = [
        {"key": "current", "label": "今年618正式期", "start": "2026-06-16", "end": "2026-06-18"},
        {"key": "same_period_last_year", "label": "去年618正式期", "start": "2025-06-16", "end": "2025-06-18"},
    ]
    scn["runner"] = {  # 实测行（SQL 别名为小写 gmv）
        "columns": ["period_key", "gmv"],
        "rows": [
            {"period_key": "今年618正式期", "gmv": "1951555.67"},
            {"period_key": "去年618正式期", "gmv": "1085883.53"},
        ],
    }
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-t08-ci")
    a = r.answer
    assert a is not None and a.comparison is not None
    assert len(a.comparison.changes) == 1  # 大小写漂移不再吞掉变化
    assert a.comparison.changes[0].value_delta == "-865672.14"
    assert a.comparison.changes[0].rate_delta == "-44.4"
    gmv_col = [c for c in a.table.columns if c.field == "gmv"][0]
    assert gmv_col.format == "money"  # 规格 fmt 命中而非兜底 text


async def test_lint_rejects_group_by_string_constant_then_recovers() -> None:
    """T08 复测实测 bug：LLM 写 GROUP BY '今年618'（sqlglot 放行但 PG 运行时 SyntaxError）
    lint 规则⑤必须拦截并回炉，第二轮产出合法 SQL 后正常出数。"""
    scn = load_scenario("t08")
    good = scn["llm"]["coder"][0]
    bad_sql = (
        "SELECT '今年618大促' AS period_key, SUM(o.gmv_amount) AS gmv FROM fact_order o "
        "WHERE o.pay_status = '已支付' AND o.order_date BETWEEN '2026-06-01' AND '2026-06-20' "
        "GROUP BY '今年618大促' "
        "UNION ALL "
        "SELECT '去年同期' AS period_key, SUM(o.gmv_amount) AS gmv FROM fact_order o "
        "WHERE o.pay_status = '已支付' AND o.order_date BETWEEN '2025-06-01' AND '2025-06-20' "
        "GROUP BY '去年同期'"
    )
    scn["llm"]["coder"] = [dict(good, sql=bad_sql), good]
    deps, llm, runner = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-lint-gbc")
    assert r.action == "answer", f"lint 拦截回炉后应出数：{r.rejection}"
    assert llm.calls_of("coder") == 2  # 第一轮 GROUP BY 字符串常量被拦回炉
    assert runner.call_count == 1


def _t13_absolute_rows_scn() -> dict:
    """T13 实测偏差场景：SQL 退化为只出分组绝对值（未按 aligner 规则11窗口算 percent）。"""
    scn = load_scenario("t13")
    scn["runner"] = {  # 实测退化：share 列装的是绝对 GMV
        "columns": ["customer_type", "share"],
        "rows": [
            {"customer_type": "新客", "share": "255000.00"},
            {"customer_type": "老客", "share": "745000.00"},
        ],
    }
    return scn


async def test_lint_rejects_backtick_alias_then_recovers() -> None:
    """T13 复测实测 bug：LLM 写 MySQL 反引号别名（`新客 GMV 占比`），sqlglot/PG 均不认，
    lint 必须给「禁止反引号」的定向报错回炉（而非裸解析错误），第二轮改双引号后正常出数。"""
    scn = load_scenario("t13")
    good = scn["llm"]["coder"][0]
    bad_sql = (
        "SELECT CASE WHEN o.is_new_customer THEN '新客' ELSE '老客' END AS customer_type, "
        "SUM(o.gmv_amount) * 100.0 / SUM(SUM(o.gmv_amount)) OVER () AS `新客 GMV 占比` "
        "FROM fact_order o WHERE o.pay_status = '已支付' "
        "AND o.order_date BETWEEN '2026-06-01' AND '2026-06-20' GROUP BY o.is_new_customer"
    )
    scn["llm"]["coder"] = [dict(good, sql=bad_sql), good]
    deps, llm, runner = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-lint-backtick")
    assert r.action == "answer", f"反引号被拦回炉后应出数：{r.rejection}"
    assert llm.calls_of("coder") == 2  # 第一轮反引号被拦回炉
    assert runner.call_count == 1


async def test_share_writer_accepts_code_computed_percentages() -> None:
    """T13 修复：占比形态下 SQL 只出绝对值时，代码算好的各组占比（25.5/74.5）
    进入落地校验允许集，Writer 引用这些百分比不得被判「编造数字」打回。"""
    scn = _t13_absolute_rows_scn()
    scn["llm"]["writer"] = [{"insight": "老客GMV占比74.5%，新客占比25.5%。"}]
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-t13-share-pct")
    a = r.answer
    assert a is not None and r.action == "answer"
    assert "74.5" in a.insight, f"代码算的占比应能过落地校验被引用：{a.insight}"
    assert not any("writer_fallback" in n for n in r.trace.notes)  # 未降级


async def test_share_fallback_insight_computes_percentages() -> None:
    """T13 修复：Writer 连续产出编造数字被打回后，fallback 模板句必须由代码
    Decimal 算出各组占比（组名 值（pct%）），不得只报绝对值。"""
    scn = _t13_absolute_rows_scn()
    scn["llm"]["writer"] = [
        {"insight": "新客GMV占比99.9%。"},  # 编造数字 → 打回重生成
        {"insight": "新客GMV占比88.8%。"},  # 仍编造 → 降级
    ]
    deps, _, _ = make_deps(scn)
    r = await run_chain(question=scn["question"], deps=deps, thread_id="spec-t13-share-fb")
    a = r.answer
    assert a is not None and r.action == "answer"
    assert "（74.5%）" in a.insight and "（25.5%）" in a.insight, (
        f"fallback 应含代码算的占比：{a.insight}"
    )
    assert "745000" in a.insight.replace(",", "")  # 绝对值一并陈述
    assert any("writer_fallback" in n for n in r.trace.notes)
