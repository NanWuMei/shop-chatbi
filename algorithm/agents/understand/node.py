"""S1 理解 understand（SDD §3-S1）。

IntentSpec 输出；闲聊/归因/预测 → not_answerable(NOT_DATA_QUESTION)；
LLM 异常重试 1 次后 error(E_LLM_UNAVAILABLE, retryable=true)。
本节点不引用任何表名/白名单/Repository（边界铁律 3）。
"""
from __future__ import annotations

from typing import Any

from ...llm import registry
from ...protocols import deps_from_config, emit
from langchain_core.runnables import RunnableConfig

from ...state import Action, ChainState, IntentSpec, Rejection, RejectionReasonCode, RejectionSuggestion
from ..shared import call_with_retry, error_state, llm_error_payload
from . import prompts
from .agent_schemas import IntentSpec as UnderstandOutput

_ATTRIBUTION_TEXT = "我不算原因，但可以给你相关数据。"
_NON_DATA_TEXT = {
    "attribution": _ATTRIBUTION_TEXT,
    "prediction": "我不做预测，但可以给你已有数据。",
    "chitchat": "我是数据查询助手，可以帮你查业务数据。",
}
_NON_DATA_SUGGESTIONS = {
    "attribution": [
        RejectionSuggestion(label="各档期退货率", question="618期间各档期退货率分别是多少"),
        RejectionSuggestion(label="各品类退货率", question="618期间退货率最高的三个类目是哪些"),
    ],
    "prediction": [
        RejectionSuggestion(label="大促 GMV", question="618大促期间各渠道GMV是多少，按从高到低排"),
        RejectionSuggestion(label="大促退货率", question="618期间退货率最高的三个类目是哪些"),
    ],
    "chitchat": [
        RejectionSuggestion(label="大促 GMV", question="618大促期间各渠道GMV是多少，按从高到低排"),
        RejectionSuggestion(label="客单价", question="618大促期间客单价（AOV）是多少"),
    ],
}


async def understand(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    emit(deps, "node_started", {"node": "S1"})
    question = state.clarified_question or state.question
    messages = prompts.build_messages(question, state.conversation_summary)

    result, attempts, err = await call_with_retry(
        lambda: deps.llm.complete(
            agent="understand",
            tier=registry.tier_for("understand"),
            messages=messages,
            schema=UnderstandOutput,
        )
    )
    base: dict[str, Any] = {"llm_calls": state.llm_calls + attempts}
    if err is not None or result is None:
        out = {**base, **error_state(state, llm_error_payload(err), attempts)}
        emit(deps, "node_finished", {"node": "S1"})
        return out

    intent: IntentSpec = result  # type: ignore[assignment]
    if not intent.is_data_question:
        kind = intent.non_data_kind or "chitchat"
        rejection = Rejection(
            reason_code=RejectionReasonCode.NOT_DATA_QUESTION,
            reason_text=_NON_DATA_TEXT.get(kind, _NON_DATA_TEXT["chitchat"]),
            suggestions=_NON_DATA_SUGGESTIONS.get(kind, _NON_DATA_SUGGESTIONS["chitchat"]),
        )
        out = {
            **base,
            "intent": intent,
            "rejection": rejection,
            "final_action": Action.NOT_ANSWERABLE,
            "trace_path": state.trace_path + ["S1"],
        }
        emit(deps, "node_finished", {"node": "S1"})
        return out
    out = {**base, "intent": intent, "trace_path": state.trace_path + ["S1"]}
    emit(deps, "node_finished", {"node": "S1"})
    return out
