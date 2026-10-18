"""LangGraph 主图编排 + run_chain 唯一入口（SDD §1/§9）。

节点注册与顺序：S1→S2→(命中跳 S6 | 未命中 S3)→S4→S5(Coder 编译子图)→S6→S7→S8；
所有分叉按 ChainState 显式枚举/布尔字段路由（template_hit / lint_passed / final_action），
不解析自然语言。MemorySaver checkpointer 支撑澄清重入（生产可换）。
"""
from __future__ import annotations

import dataclasses
import time
import uuid
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from .agents.aligner.node import align
from .agents.coder.subgraph import build_coder_subgraph
from .agents.understand.node import understand
from .agents.writer.node import writer
from .config import Settings
from .nodes.build_view import build_caliber, build_view
from .nodes.execute import execute
from .nodes.retrieve import retrieve
from .nodes.template_match import template_match
from .protocols import Deps, OnEvent, emit
from .state import (
    Action,
    Answer,
    ChainResult,
    ChainState,
    ErrorPayload,
    Meta,
    Rejection,
    RejectionReasonCode,
    RejectionSuggestion,
    Trace,
)

_CODER_SUBGRAPH: Any = None


def _coder() -> Any:
    global _CODER_SUBGRAPH
    if _CODER_SUBGRAPH is None:
        _CODER_SUBGRAPH = build_coder_subgraph()
    return _CODER_SUBGRAPH


async def _coder_node(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    return await _coder().ainvoke(state, config)


async def _gen_failed(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    """lint 超轮终态：query_gen_failed(GEN_LINT_EXHAUSTED)，带 lint 原因（不进 trace.path）。"""
    reason = state.lint_errors[0] if state.lint_errors else "查询多次生成仍未通过校验"
    rejection = Rejection(
        reason_code=RejectionReasonCode.GEN_LINT_EXHAUSTED,
        reason_text=f"查询生成未通过校验：{reason}。可以换个更具体的问法再试。",
        suggestions=[
            RejectionSuggestion(label="各渠道 GMV", question="618大促期间各渠道GMV是多少，按从高到低排"),
            RejectionSuggestion(label="客单价", question="618大促期间客单价（AOV）是多少"),
        ],
    )
    return {"rejection": rejection, "final_action": Action.QUERY_GEN_FAILED}


# ---------------------------------------------------------------------------
# 路由（只读 ChainState 显式字段，无字符串 contains 判断）
# ---------------------------------------------------------------------------
def _route_after_s1(state: ChainState) -> str:
    return END if state.final_action is not None else "S2"


def _route_after_s2(state: ChainState) -> str:
    hit = state.template_match.hit if state.template_match else False
    return "S6" if hit else "S3"


def _route_after_s4(state: ChainState) -> str:
    return END if state.final_action is not None else "S5"


def _route_after_s5(state: ChainState) -> str:
    if state.error is not None:
        return END
    return "S6" if state.lint_passed else "gen_failed"


def _route_after_s6(state: ChainState) -> str:
    return END if state.final_action is not None else "S7"


def _route_entry(state: ChainState) -> str:
    """中段入口路由（FR-21/22）：start_at 显式指定从 S4/S5 进入，否则主入口 S1。"""
    if state.start_at == "S4":
        return "S4"
    if state.start_at == "S5":
        return "S5"
    return "S1"


def build_graph(checkpointer: Any = None) -> Any:
    """编译主图；checkpointer 可注入（离线默认 MemorySaver，生产可换）。"""
    g = StateGraph(ChainState)
    g.add_node("S1", understand)
    g.add_node("S2", template_match)
    g.add_node("S3", retrieve)
    g.add_node("S4", align)
    g.add_node("S5", _coder_node)
    g.add_node("S6", execute)
    g.add_node("S7", build_view)
    g.add_node("S8", writer)
    g.add_node("gen_failed", _gen_failed)

    g.add_conditional_edges(START, _route_entry, {"S1": "S1", "S4": "S4", "S5": "S5"})
    g.add_conditional_edges("S1", _route_after_s1, {"S2": "S2", END: END})
    g.add_conditional_edges("S2", _route_after_s2, {"S6": "S6", "S3": "S3"})
    g.add_edge("S3", "S4")
    g.add_conditional_edges("S4", _route_after_s4, {"S5": "S5", END: END})
    g.add_conditional_edges("S5", _route_after_s5, {"S6": "S6", "gen_failed": "gen_failed", END: END})
    g.add_edge("gen_failed", END)
    g.add_conditional_edges("S6", _route_after_s6, {"S7": "S7", END: END})
    g.add_edge("S7", "S8")
    g.add_edge("S8", END)
    return g.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# run_chain（唯一入口）
# ---------------------------------------------------------------------------
_DEFAULT_CHECKPOINTER = MemorySaver()
_GRAPHS: dict[int, Any] = {}


def _graph_for(checkpointer: Any) -> Any:
    key = id(checkpointer)
    if key not in _GRAPHS:
        _GRAPHS[key] = build_graph(checkpointer)
    return _GRAPHS[key]


_RESET_FIELDS: dict[str, Any] = {
    "intent": None,
    "template_match": None,
    "retrieval": None,
    "query_spec": None,
    "sql": None,
    "lineage": None,
    "lint_passed": False,
    "lint_rounds": 0,
    "lint_errors": [],
    "query_result": None,
    "table": None,
    "chart": None,
    "comparison_result": None,
    "insight": None,
    "writer_fallback": False,
    "final_action": None,
    "clarify_payload": None,
    "rejection": None,
    "error": None,
    "trace_path": [],
    "trace_notes": [],
    "retrieval_mode": None,
    "llm_calls": 0,
}


async def run_chain(
    *,
    question: str = "",
    clarified_question: Optional[str] = None,
    clarify_id: Optional[str] = None,
    query_spec: Optional[Any] = None,
    start_at: Optional[str] = None,
    deps: Deps,
    thread_id: Optional[str] = None,
    on_event: Optional[OnEvent] = None,
    checkpointer: Any = None,
    conversation_summary: str = "",
) -> ChainResult:
    """一次问数：初始化 trace → ainvoke 主图 → 组装唯一契约 ChainResult。

    入口三态（FR-21/22）：① 主入口 question；② 澄清重入 clarified_question+clarify_id（S1）；
    ③ 中段入口 start_at="S5"（刷新，从 gen_sql 起跑）/ start_at="S4"（recalibrate，强制澄清卡），
    中段入口必须携带 query_spec、与澄清重入参数互斥。
    """
    if start_at not in (None, "S4", "S5"):
        raise ValueError(f"start_at 仅支持 None/'S4'/'S5'，实际: {start_at!r}")
    if start_at is not None and query_spec is None:
        raise ValueError(f"start_at={start_at} 需要提供 query_spec")
    if start_at is not None and (clarified_question or clarify_id):
        raise ValueError("start_at 中段入口与澄清重入参数（clarified_question/clarify_id）互斥")

    started = time.perf_counter()
    cp = checkpointer or _DEFAULT_CHECKPOINTER
    graph = _graph_for(cp)
    tid = thread_id or f"turn-{uuid.uuid4().hex[:8]}"
    if on_event is not None or deps.on_event is not None:
        deps = dataclasses.replace(deps, on_event=on_event or deps.on_event)

    config = {"configurable": {"thread_id": tid, "deps": deps}}

    round_no = 1
    if clarified_question and start_at is None:
        try:
            prev = await graph.aget_state(config)
            if prev and prev.values:
                round_no = min(int(prev.values.get("round", 1)) + 1, 2)
        except Exception:
            round_no = 1

    effective_question = clarified_question or question
    input_state: dict[str, Any] = {
        **_RESET_FIELDS,
        "question": effective_question,
        "clarified_question": clarified_question,
        "clarify_id": clarify_id,
        "round": round_no,
        "conversation_summary": conversation_summary,
        "start_at": start_at,
        "recalibrate": start_at == "S4",
        "query_spec": query_spec,
    }
    final = await graph.ainvoke(input_state, config)
    state = ChainState.model_validate(final)

    result = _assemble_result(state, tid, effective_question, started)
    emit(deps, "terminal", {"action": result.action})
    return result


def _assemble_result(state: ChainState, tid: str, question: str, started: float) -> ChainResult:
    action = state.final_action or Action.ERROR
    trace = Trace(
        path=list(state.trace_path),
        template_hit=bool(state.template_match and state.template_match.hit),
        retrieval_mode=state.retrieval_mode,
        lint_rounds=state.lint_rounds,
        llm_calls=state.llm_calls,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        notes=list(state.trace_notes),
    )
    meta = Meta(turn_id=tid, question=question)

    if action == Action.ANSWER:
        from .state import TableData

        answer = Answer(
            table=state.table or TableData(),
            chart=state.chart,
            insight=state.insight or "该范围内没有符合条件的数据。",
            caliber=build_caliber(state),
            comparison=state.comparison_result,
        )
        return ChainResult(
            action=action,
            answer=answer,
            trace=trace,
            meta=meta,
            query_spec=state.query_spec,
            sql=state.sql,
        )
    if action == Action.CLARIFY and state.clarify_payload is not None:
        return ChainResult(
            action=action,
            clarify=state.clarify_payload,
            trace=trace,
            meta=meta,
            query_spec=state.query_spec,
            sql=state.sql,
        )
    if action == Action.ERROR:
        error = state.error or ErrorPayload(code="E_INTERNAL", message="内部处理失败", retryable=True)
        return ChainResult(
            action=action,
            error=error,
            trace=trace,
            meta=meta,
            query_spec=state.query_spec,
            sql=state.sql,
        )
    # not_answerable / query_gen_failed / query_failed
    rejection = state.rejection or Rejection(
        reason_code=RejectionReasonCode.NO_MATCHING_DATA,
        reason_text="这个问题暂时没有答案。",
        suggestions=[],
    )
    return ChainResult(
        action=action,
        rejection=rejection,
        trace=trace,
        meta=meta,
        query_spec=state.query_spec,
        sql=state.sql,
    )
