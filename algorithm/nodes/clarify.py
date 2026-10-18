"""澄清卡构造（SDD §6 clarify 载荷，FR-14）。

options 来自 L0 层级/枚举候选或 L1 增强（确认前不出数）；
round 计数与两轮上限的状态推进由 S4 节点与 run_chain 配合完成。
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from ..state import (
    ChainState,
    ClarifyOption,
    ClarifyPayload,
    ClarifyReasonCode,
    ClarifySuggestion,
    InputType,
)

# 列名 → 业务可读层级标签
_COLUMN_LABELS = {
    "level1_name": "一级类目",
    "level2_name": "二级类目",
    "channel_name": "渠道",
    "promo_phase": "档期",
    "pay_status": "支付状态",
}

_TITLES = {
    ClarifyReasonCode.METRIC_DIM_AMBIGUOUS: "这个问题有多种理解，你指的是哪一个？",
    ClarifyReasonCode.MISSING_TIME: "想查哪个时间段？",
    ClarifyReasonCode.VAGUE: "这个问题有点泛，换个更具体的问法试试？",
    ClarifyReasonCode.ANAPHORA_UNRESOLVED: "没听清指代的是哪一个，补充说明一下？",
}

# 死卡兜底：question_suggestions 卡建议为空时前端无可点项（确认钮置灰），统一保底建议（实测 VAGUE 空建议死卡过）
FALLBACK_SUGGESTION_QUESTIONS = [
    "618大促期间各渠道GMV是多少，按从高到低排",
    "大促期间哪个渠道转化率最高",
    "大促期间退货率最高的三个类目是哪些",
]


def new_clarify_id() -> str:
    return f"clz-{uuid.uuid4().hex[:8]}"


def build_clarify_payload(
    *,
    reason: ClarifyReasonCode,
    round: int,
    focus: Optional[str] = None,
    title: Optional[str] = None,
    candidates: Optional[list[dict[str, str]]] = None,
    calendar: Optional[dict[str, Any]] = None,
    suggestions: Optional[list[str]] = None,
    time_quick: bool = False,
) -> ClarifyPayload:
    """按澄清码组装载荷；候选项为空时退化为可自由输入（allow_custom_text 恒 true）。

    安全网：最终形态为 question_suggestions 且建议为空时统一填保底建议（前端空建议即死卡）。
    """
    options: list[ClarifyOption] = []
    sug: list[ClarifySuggestion] = [ClarifySuggestion(question=q) for q in (suggestions or [])]

    if reason == ClarifyReasonCode.METRIC_DIM_AMBIGUOUS:
        if time_quick:
            # recalibrate 缺时间项（FR-22）：时间快捷选项 + 逐项重选引导放 suggestions
            input_type = InputType.TIME_QUICK
            for key, rng in (calendar or {}).items():
                options.append(ClarifyOption(value=str(key), label=f"{key}（{rng[0]}~{rng[1]}）"))
        elif candidates:
            input_type = InputType.SINGLE_CHOICE
            for c in candidates:
                col = c.get("column", "")
                scope = _COLUMN_LABELS.get(col, col)
                label = f"{c.get('value')}（{scope}）" if scope else str(c.get("value"))
                options.append(ClarifyOption(value=str(c.get("value")), label=label))
        else:
            # 枚举零候选时发 single_choice 会死卡（空选项确认钮置灰），降级为建议问法
            input_type = InputType.QUESTION_SUGGESTIONS
        if focus and not title:
            title = f"「{focus}」具体指哪一个？"
    elif reason == ClarifyReasonCode.MISSING_TIME:
        input_type = InputType.TIME_QUICK
        for key, rng in (calendar or {}).items():
            options.append(ClarifyOption(value=str(key), label=f"{key}（{rng[0]}~{rng[1]}）"))
    else:
        input_type = InputType.QUESTION_SUGGESTIONS

    if input_type == InputType.QUESTION_SUGGESTIONS and not sug:
        sug = [ClarifySuggestion(question=q) for q in FALLBACK_SUGGESTION_QUESTIONS]

    return ClarifyPayload(
        clarify_id=new_clarify_id(),
        round=round,
        title=title or _TITLES[reason],
        reason_code=reason,
        input_type=input_type,
        options=options,
        suggestions=sug,
        allow_custom_text=True,
    )


def calendar_for_clarify(state: ChainState, deps: Any) -> dict[str, Any]:
    """时间澄清的快捷选项来源：L1 time-calendar 优先，否则 L0 meta.promo_calendar。"""
    if deps.resources.calendar:
        return deps.resources.calendar
    meta = getattr(deps.schema_provider, "meta", {}) or {}
    return dict(meta.get("promo_calendar", {}))
