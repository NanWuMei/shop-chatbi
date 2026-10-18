"""S5 Coder 生成节点（SDD §3-S5）：调 strong 档生成 sql+lineage，失败重试 1 次。

Coder 不持有执行工具（边界铁律 1）：本模块不 import QueryRunner/execute。
"""
from __future__ import annotations

from typing import Any

from ...llm import registry
from ...protocols import deps_from_config, emit
from langchain_core.runnables import RunnableConfig

from ...state import ChainState, RetrievalContext
from ..shared import call_with_retry, error_state, llm_error_payload
from . import prompts
from .agent_schemas import CoderOutput


async def gen(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    if state.query_spec is None:  # 防御：正常链路不会发生
        return {**error_state(state, llm_error_payload(None), 0)}

    # S5 刷新入口（FR-21）无检索上下文：Coder 仅按 QuerySpec + L0 生成
    ctx = state.retrieval or RetrievalContext()
    messages = prompts.build_messages(
        state.query_spec,
        ctx,
        lint_errors=state.lint_errors or None,
    )
    result, attempts, err = await call_with_retry(
        lambda: deps.llm.complete(
            agent="coder",
            tier=registry.tier_for("coder"),
            messages=messages,
            schema=CoderOutput,
        )
    )
    first_entry = "S5" not in state.trace_path
    if first_entry:
        emit(deps, "node_started", {"node": "S5"})
    trace_path = state.trace_path if not first_entry else state.trace_path + ["S5"]
    base: dict[str, Any] = {"llm_calls": state.llm_calls + attempts, "trace_path": trace_path}
    if err is not None or result is None:
        emit(deps, "node_finished", {"node": "S5"})
        return {**base, **error_state(state, llm_error_payload(err), attempts)}

    out: CoderOutput = result  # type: ignore[assignment]
    return {
        **base,
        "sql": out.sql,
        "lineage": out.lineage,
        "lint_rounds": state.lint_rounds + 1,
    }
