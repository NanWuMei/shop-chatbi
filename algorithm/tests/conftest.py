"""离线默认装配（Task 14）：静态 L0 + 空资源 + mock LLM/embedding + 内存 repo + MockQueryRunner。

所有测试不接真库、不需要 key/网络；仅替换 deps 中协议实现即可切「半真实」装配（TR-14.5）。
场景断言辅助 assert_expect 供 test_scenarios / test_paths 共用。
"""
from __future__ import annotations

import pathlib
from typing import Any, Optional

import yaml

from algorithm.config import Settings
from algorithm.protocols import Deps, Resources
from algorithm.retrieval.repo import InMemoryRepository
from algorithm.state import ChainResult
from algorithm.tests.mocks.mock_embeddings import MockEmbeddingClient
from algorithm.tests.mocks.mock_llm import MockLLMClient
from algorithm.tests.mocks.mock_query_runner import MockQueryRunner
from algorithm.tests.mocks.static_schema import StaticSchemaProvider

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
SCENARIO_IDS = [f"t{i:02d}" for i in range(1, 16)]


def load_scenario(sid: str) -> dict[str, Any]:
    """读取场景 YAML，并按 rows_key 合并行数据（rows/ 与 scenarios/ 分离，便于走读核对）。"""
    scn = yaml.safe_load((FIXTURES / "scenarios" / f"{sid}.yaml").read_text(encoding="utf-8"))
    rows_key = scn.get("rows_key")
    if rows_key:
        scn["runner"] = yaml.safe_load(
            (FIXTURES / "rows" / f"{rows_key}.yaml").read_text(encoding="utf-8")
        )
    else:
        scn["runner"] = {"columns": [], "rows": []}
    return scn


def make_deps(
    scn: dict[str, Any],
    *,
    embedding: Any = None,
    repository: Any = None,
    resources: Optional[Resources] = None,
    schema_provider: Any = None,
    settings: Optional[Settings] = None,
    on_event: Any = None,
) -> tuple[Deps, MockLLMClient, MockQueryRunner]:
    """默认装配：静态 L0、空资源、mock LLM/embedding(不可用)、内存 repo、MockQueryRunner。"""
    llm = MockLLMClient(scn.get("llm"))
    runner = MockQueryRunner(scn.get("runner"))
    deps = Deps(
        settings=settings or Settings(),
        llm=llm,
        schema_provider=schema_provider or StaticSchemaProvider(),
        query_runner=runner,
        embedding=embedding if embedding is not None else MockEmbeddingClient(available=False),
        repository=repository if repository is not None else InMemoryRepository(),
        resources=resources if resources is not None else Resources(),
        on_event=on_event,
    )
    return deps, llm, runner


def assert_expect(
    result: ChainResult,
    exp: dict[str, Any],
    runner: Optional[MockQueryRunner] = None,
    llm: Optional[MockLLMClient] = None,
) -> None:
    """按场景 expect 段逐项断言；契约 ChainResult 必须 JSON 可序列化。"""
    assert result.action == exp["action"], f"action 不符：{result.action} != {exp['action']}（error={result.error}）"
    result.model_dump_json()  # 契约可序列化（AC-2）

    if exp.get("path") is not None:
        assert result.trace.path == exp["path"], f"path 不符：{result.trace.path}"
    if "template_hit" in exp:
        assert result.trace.template_hit == exp["template_hit"]
    if "retrieval_mode" in exp:
        assert result.trace.retrieval_mode == exp["retrieval_mode"]
    if "llm_calls" in exp:
        assert result.trace.llm_calls == exp["llm_calls"]
    if "lint_rounds" in exp:
        assert result.trace.lint_rounds == exp["lint_rounds"]
    if exp.get("writer_fallback"):
        assert any("writer_fallback" in n for n in result.trace.notes), f"缺 writer_fallback 标注：{result.trace.notes}"

    if exp["action"] == "answer":
        a = result.answer
        assert a is not None
        if "chart" in exp:
            if exp["chart"] is None:
                assert a.chart is None, f"期望无图，实际 {a.chart}"
            else:
                assert a.chart is not None and a.chart.type == exp["chart"], f"图型不符：{a.chart}"
        if "rows" in exp:
            assert len(a.table.rows) == exp["rows"], f"行数不符：{len(a.table.rows)}"
        if "insight_contains" in exp:
            assert exp["insight_contains"] in a.insight, f"解读不含「{exp['insight_contains']}」：{a.insight}"
        if "insight_equals" in exp:
            assert a.insight == exp["insight_equals"], f"解读不符：{a.insight}"
        if "caliber_contains" in exp:
            for s in exp["caliber_contains"]:
                assert s in a.caliber.summary, f"口径摘要不含「{s}」：{a.caliber.summary}"
        if "changes" in exp:
            assert a.comparison is not None and len(a.comparison.changes) == exp["changes"], (
                f"changes 数不符：{a.comparison}"
            )
        if "periods" in exp:
            assert a.comparison is not None and len(a.comparison.periods) == exp["periods"], (
                f"periods 数不符：{a.comparison}"
            )
        if "changes_rate" in exp:
            assert a.comparison is not None
            rates = [c.rate_delta for c in a.comparison.changes]
            assert exp["changes_rate"] in rates, f"变化率 {exp['changes_rate']} 不在 {rates}"

    if exp["action"] in ("not_answerable", "query_gen_failed", "query_failed"):
        r = result.rejection
        assert r is not None
        if "reason_code" in exp:
            assert r.reason_code == exp["reason_code"], f"拒答码不符：{r.reason_code}"
        if "suggestions_min" in exp:
            assert len(r.suggestions) >= exp["suggestions_min"], "拒答引导建议不足"
        assert "SQL" not in r.reason_text and "Exception" not in r.reason_text  # 大白话

    if exp["action"] == "clarify":
        c = result.clarify
        assert c is not None
        if "reason_code" in exp:
            assert c.reason_code == exp["reason_code"], f"澄清码不符：{c.reason_code}"
        if "input_type" in exp:
            assert c.input_type == exp["input_type"], f"输入类型不符：{c.input_type}"
        if "options_min" in exp:
            assert len(c.options) >= exp["options_min"], f"澄清选项不足：{c.options}"
        if "round" in exp:
            assert c.round == exp["round"], f"澄清轮次不符：{c.round}"
        assert c.allow_custom_text is True
        assert c.clarify_id

    if exp["action"] == "error":
        e = result.error
        assert e is not None
        if "error_code" in exp:
            assert e.code == exp["error_code"], f"错误码不符：{e.code}"
        if "retryable" in exp:
            assert e.retryable == exp["retryable"]

    if runner is not None and "sql_contains" in exp:
        assert any(exp["sql_contains"] in s for s in runner.executed_sql), (
            f"执行 SQL 不含「{exp['sql_contains']}」：{runner.executed_sql}"
        )
    if llm is not None and "llm_agent_calls" in exp:
        for agent, n in exp["llm_agent_calls"].items():
            assert llm.calls_of(agent) == n, f"{agent} 调用 {llm.calls_of(agent)} 次 != {n}"
