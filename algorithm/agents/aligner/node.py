"""S4 对齐 align（SDD §3-S4）。

规格钉死 → S5；多候选/缺时间/指代失败/过泛 → clarify（四码）；
无对应表列 / 口径矛盾 → not_answerable（两码）。第二轮仍未消歧 → not_answerable。
"""
from __future__ import annotations

from typing import Any, Optional

from ...llm import registry
from ...nodes.clarify import (
    FALLBACK_SUGGESTION_QUESTIONS,
    build_clarify_payload,
    calendar_for_clarify,
)
from ...protocols import deps_from_config, emit
from langchain_core.runnables import RunnableConfig

from ...state import (
    Action,
    ChainState,
    ClarifyReasonCode,
    Rejection,
    RejectionReasonCode,
    RejectionSuggestion,
)
from ..shared import call_with_retry, error_state, llm_error_payload
from . import prompts
from .agent_schemas import AlignerOutput

_MAX_CLARIFY_ROUND = 2

_NO_MATCH_SUGGESTIONS = [
    RejectionSuggestion(label="GMV", question="618大促期间各渠道GMV是多少，按从高到低排"),
    RejectionSuggestion(label="转化率", question="大促期间哪个渠道转化率最高"),
    RejectionSuggestion(label="退货率", question="大促期间退货率最高的三个类目是哪些"),
    RejectionSuggestion(label="客单价", question="618大促期间客单价（AOV）是多少"),
]
_CONFLICT_SUGGESTIONS = [
    RejectionSuggestion(label="各渠道转化率", question="大促期间各渠道转化率分别是多少"),
    RejectionSuggestion(label="各渠道 GMV", question="618大促期间各渠道GMV是多少，按从高到低排"),
]

_REJECT_DEFAULT_TEXT = {
    "NO_MATCHING_DATA": "已接入的数据表里没有能回答这个问题的数据。",
    "CALIBER_CONFLICT": "这个指标按你要的维度算不出来，口径上自相矛盾。",
}

_FOCUS_SUFFIXES = ("类目", "品类", "类别")


def _enum_candidates_with_suffix_strip(deps: Any, focus: str) -> list[dict[str, str]]:
    """查枚举候选；「美妆类目」类带后缀词先剥尾再查一次（LLM focus 常带类目/品类/类别后缀）。"""
    candidates = deps.schema_provider.enum_candidates(focus)
    if not candidates:
        for suffix in _FOCUS_SUFFIXES:
            if focus.endswith(suffix) and len(focus) > len(suffix):
                candidates = deps.schema_provider.enum_candidates(focus[: -len(suffix)])
                break
    return candidates


def _to_suggestions(items: list[dict[str, str]]) -> list[RejectionSuggestion]:
    out = []
    for it in items:
        q = it.get("question")
        if q:
            out.append(RejectionSuggestion(label=it.get("label") or q, question=q))
    return out


def _recalibrate_clarify(state: ChainState, deps: Any) -> dict[str, Any]:
    """recalibrate（S4 入口，FR-22）：按原 QuerySpec 强制产出逐项重选澄清卡。

    不调 LLM、不执行 SQL；round=1、reason_code 固定 METRIC_DIM_AMBIGUOUS（复用四码不扩枚举）；
    原规格缺时间项 → time_quick 快捷补时间（重选引导放 suggestions）；确认后走主链 S1 重入。
    """
    spec = state.query_spec
    assert spec is not None
    if spec.dimensions:
        focus = spec.dimensions[0].name
    elif spec.metrics:
        focus = spec.metrics[0].name
    else:
        focus = None
    if spec.time_range is None:
        payload = build_clarify_payload(
            reason=ClarifyReasonCode.METRIC_DIM_AMBIGUOUS,
            round=1,
            focus=focus,
            title="重新确认口径：先选时间段，也可以直接换个问法",
            calendar=calendar_for_clarify(state, deps),
            suggestions=["618大促期间各渠道GMV是多少，按从高到低排"],
            time_quick=True,
        )
    else:
        candidates = _enum_candidates_with_suffix_strip(deps, focus) if focus else []
        payload = build_clarify_payload(
            reason=ClarifyReasonCode.METRIC_DIM_AMBIGUOUS,
            round=1,
            focus=focus,
            title="重新确认口径：你指的是哪一个？",
            candidates=candidates,
            # 零候选时降级为建议问法卡，建议必须非空（否则前端死卡）
            suggestions=None if candidates else list(FALLBACK_SUGGESTION_QUESTIONS),
        )
    emit(deps, "node_finished", {"node": "S4"})
    return {
        "clarify_payload": payload,
        "final_action": Action.CLARIFY,
        "trace_path": state.trace_path + ["S4"],
    }


async def align(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    emit(deps, "node_started", {"node": "S4"})

    # recalibrate 入口（FR-22）：「口径不对，重新澄清」从 S4 强制出卡，不调 LLM、不执行 SQL
    if state.recalibrate and state.query_spec is not None:
        return _recalibrate_clarify(state, deps)

    intent = state.intent
    ctx = state.retrieval
    if intent is None or ctx is None:  # 防御：正常链路不会发生
        return {**error_state(state, llm_error_payload(None), 0)}

    meta = getattr(deps.schema_provider, "meta", {}) or {}
    calendar = calendar_for_clarify(state, deps)
    messages = prompts.build_messages(
        intent,
        ctx,
        coverage=meta.get("coverage"),
        calendar=calendar,
        round=state.round,
    )
    result, attempts, err = await call_with_retry(
        lambda: deps.llm.complete(
            agent="aligner",
            tier=registry.tier_for("aligner"),
            messages=messages,
            schema=AlignerOutput,
        )
    )
    base: dict[str, Any] = {
        "llm_calls": state.llm_calls + attempts,
        "trace_path": state.trace_path + ["S4"],
    }
    if err is not None or result is None:
        emit(deps, "node_finished", {"node": "S4"})
        return {**base, **error_state(state, llm_error_payload(err), attempts)}

    out: AlignerOutput = result  # type: ignore[assignment]

    if out.status == "ok" and out.query_spec is not None:
        emit(deps, "node_finished", {"node": "S4"})
        return {**base, "query_spec": out.query_spec}

    if out.status == "clarify" and out.clarify_reason is not None:
        if state.round >= _MAX_CLARIFY_ROUND:
            # 两轮仍未消歧 → not_answerable（SDD §10 T09）
            rejection = Rejection(
                reason_code=RejectionReasonCode.NO_MATCHING_DATA,
                reason_text="两轮确认后仍无法确定你指的口径，换个更具体的问法试试。",
                suggestions=_NO_MATCH_SUGGESTIONS,
            )
            emit(deps, "node_finished", {"node": "S4"})
            return {**base, "rejection": rejection, "final_action": Action.NOT_ANSWERABLE}
        candidates: list[dict[str, str]] = []
        if out.clarify_reason == ClarifyReasonCode.METRIC_DIM_AMBIGUOUS and out.clarify_focus:
            candidates = _enum_candidates_with_suffix_strip(deps, out.clarify_focus)
        suggestions = [s.get("question", "") for s in out.suggestions if s.get("question")]
        if (
            out.clarify_reason == ClarifyReasonCode.METRIC_DIM_AMBIGUOUS
            and not candidates
            and not suggestions
        ):
            suggestions = list(FALLBACK_SUGGESTION_QUESTIONS)
        payload = build_clarify_payload(
            reason=out.clarify_reason,
            round=state.round,
            focus=out.clarify_focus,
            title=out.clarify_title,
            candidates=candidates,
            calendar=calendar if out.clarify_reason == ClarifyReasonCode.MISSING_TIME else None,
            suggestions=suggestions or None,
        )
        emit(deps, "node_finished", {"node": "S4"})
        return {**base, "clarify_payload": payload, "final_action": Action.CLARIFY}

    # not_answerable 分支（含 LLM 输出不完整时的兜底）
    reason_code: Optional[str] = out.reject_reason if out.status == "not_answerable" else None
    if reason_code == "CALIBER_CONFLICT":
        rejection = Rejection(
            reason_code=RejectionReasonCode.CALIBER_CONFLICT,
            reason_text=out.reject_text or _REJECT_DEFAULT_TEXT["CALIBER_CONFLICT"],
            suggestions=_to_suggestions(out.suggestions) or _CONFLICT_SUGGESTIONS,
        )
    else:
        rejection = Rejection(
            reason_code=RejectionReasonCode.NO_MATCHING_DATA,
            reason_text=out.reject_text or _REJECT_DEFAULT_TEXT["NO_MATCHING_DATA"],
            suggestions=_to_suggestions(out.suggestions) or _NO_MATCH_SUGGESTIONS,
        )
    emit(deps, "node_finished", {"node": "S4"})
    return {**base, "rejection": rejection, "final_action": Action.NOT_ANSWERABLE}
