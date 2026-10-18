"""S5 Coder 子图（SDD §1/§9）：gen→lint 回边，自环 ≤2 轮。

lint 不过带结构化错误回炉；两轮不过退出（lint_passed=false），
由主图映射 query_gen_failed(GEN_LINT_EXHAUSTED)。
"""
from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from ...protocols import deps_from_config, emit
from ...state import ChainState
from .gen import gen
from .lint import lint_sql

MAX_LINT_ROUNDS = 2


async def lint(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    # lint 白名单按 L0：检索上下文存在时用其 schema_blocks，S5 刷新入口（FR-21）回落 SchemaProvider 全量 L0
    blocks = state.retrieval.schema_blocks if state.retrieval else deps.schema_provider.all_blocks()
    result = lint_sql(
        state.sql or "",
        blocks,
        lineage=state.lineage,
        default_limit=deps.settings.row_limit_default,
        max_limit=deps.settings.row_limit_max,
    )
    if result.ok:
        emit(deps, "node_finished", {"node": "S5"})
        return {"sql": result.sql, "lint_passed": True, "lint_errors": []}
    note = f"S5 lint 第 {state.lint_rounds} 轮未通过：{'；'.join(result.errors)}"
    if state.lint_rounds >= MAX_LINT_ROUNDS:
        emit(deps, "node_finished", {"node": "S5"})
    return {
        "lint_passed": False,
        "lint_errors": result.errors,
        "trace_notes": state.trace_notes + [note],
    }


def coder_route(state: ChainState) -> str:
    if state.error is not None or state.lint_passed:
        return END
    if state.lint_rounds >= MAX_LINT_ROUNDS:
        return END
    return "gen"


def build_coder_subgraph() -> Any:
    """编译后的 Coder 子图，作为主图 S5 节点接入。"""
    g = StateGraph(ChainState)
    g.add_node("gen", gen)
    g.add_node("lint", lint)
    g.add_edge(START, "gen")
    g.add_edge("gen", "lint")
    g.add_conditional_edges("lint", coder_route, {END: END, "gen": "gen"})
    return g.compile()
