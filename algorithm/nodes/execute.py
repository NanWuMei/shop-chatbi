"""S6 执行 execute（SDD §3-S6）：只调注入的 QueryRunner，算法不直连库。

超时 → query_failed(QUERY_TIMEOUT)；执行异常 → query_failed(QUERY_ERROR)；
0 行照常前进（如实空表，非拒答）。
"""
from __future__ import annotations

from typing import Any

from ..protocols import QueryTimeoutError, deps_from_config, emit
from langchain_core.runnables import RunnableConfig

from ..state import Action, ChainState, Rejection, RejectionReasonCode, RejectionSuggestion

_RETRY_SUGGESTIONS = [
    RejectionSuggestion(label="换个问法", question="618大促期间各渠道GMV是多少，按从高到低排"),
]


async def execute(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    emit(deps, "node_started", {"node": "S6"})
    sql = state.sql or ""
    base: dict[str, Any] = {"trace_path": state.trace_path + ["S6"]}
    try:
        result = await deps.query_runner.run(sql)
    except QueryTimeoutError:
        rejection = Rejection(
            reason_code=RejectionReasonCode.QUERY_TIMEOUT,
            reason_text="查询超时了，数据量可能太大，缩小时间范围再试一次。",
            suggestions=_RETRY_SUGGESTIONS,
        )
        emit(deps, "node_finished", {"node": "S6"})
        return {
            **base,
            "rejection": rejection,
            "final_action": Action.QUERY_FAILED,
            "trace_notes": state.trace_notes + ["S6: 查询超时"],
        }
    except Exception as e:
        rejection = Rejection(
            reason_code=RejectionReasonCode.QUERY_ERROR,
            reason_text="查询执行出错了，请稍后重试或换个问法。",
            suggestions=_RETRY_SUGGESTIONS,
        )
        emit(deps, "node_finished", {"node": "S6"})
        return {
            **base,
            "rejection": rejection,
            "final_action": Action.QUERY_FAILED,
            "trace_notes": state.trace_notes + [f"S6: 执行异常 {type(e).__name__}: {e}"],
        }
    emit(deps, "node_finished", {"node": "S6"})
    return {**base, "query_result": result}
