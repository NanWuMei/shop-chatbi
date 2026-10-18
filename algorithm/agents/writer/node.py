"""S8 解读 insight（SDD §3-S8）。

严格一句、数字落地校验（正则抽取逐一核对真实行/changes/口径，容差=按句中精度舍入）；
失败重生成 1 次 → 规则模板句兜底（trace 标注 writer_fallback）；
空结果固定「该范围内没有符合条件的数据。」；解读失败永不阻断 answer。
本节点看不到 SQL（边界铁律 2）：输入对象中不取 state.sql。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from ...llm import registry
from ...nodes.build_view import build_caliber
from ...protocols import deps_from_config, emit
from langchain_core.runnables import RunnableConfig

from ...state import Action, Caliber, ChainState, QueryResult
from ..shared import call_with_retry
from . import prompts
from .agent_schemas import WriterOutput

EMPTY_INSIGHT = "该范围内没有符合条件的数据。"

_BAN_WORDS = re.compile(r"因为|由于|原因是|建议|应该|预计|预测|将会|可能涨|可能降")
_NUM_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
_PCT_Q = Decimal("0.1")


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _share_breakdown(state: ChainState) -> list[tuple[str, Decimal, Decimal]]:
    """占比形态分解：[(组名, 值, 占比%)]，代码 Decimal 计算（1 位小数），Writer 不自己算。

    仅 slot_form=share 且有饼图时计算；行值本身已是百分比（合计≈100）则返回空（无需再算）。
    """
    if not (state.intent and state.intent.slot_form == "share"):
        return []
    result = state.query_result
    chart = state.chart
    if result is None or not result.rows or chart is None or not chart.series:
        return []
    x, y = chart.x_field, chart.series[0].field
    vals = [(str(row.get(x, "")), _dec(row.get(y))) for row in result.rows]
    vals = [(k, v) for k, v in vals if v is not None]
    total = sum((v for _, v in vals), Decimal(0))
    if total == 0 or total.quantize(Decimal("1"), rounding=ROUND_HALF_UP) == Decimal("100"):
        return []
    return [(k, v, (v / total * 100).quantize(_PCT_Q, rounding=ROUND_HALF_UP)) for k, v in vals]


# ---------------------------------------------------------------------------
# 数字落地校验
# ---------------------------------------------------------------------------
def _extract_numbers(text: str) -> list[Decimal]:
    out: list[Decimal] = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(0).replace(",", "")
        try:
            out.append(Decimal(raw))
        except InvalidOperation:
            continue
    return out


def _allowed_numbers(state: ChainState, caliber: Caliber) -> set[Decimal]:
    """允许出现的数字：真实行值 + 代码算好的 changes + 口径/时间/期限文本中的数字。"""
    allowed: set[Decimal] = set()

    def add(v: Any) -> None:
        if v is None or isinstance(v, bool):
            return
        if isinstance(v, (int, float, Decimal, str)):
            try:
                allowed.add(Decimal(str(v).replace(",", "")))
            except InvalidOperation:
                pass

    result = state.query_result
    if result is not None:
        for row in result.rows:
            for v in row.values():
                add(v)
    if state.comparison_result is not None:
        for ch in state.comparison_result.changes:
            add(ch.value_delta)
            add(ch.rate_delta)
    for _, _, pct in _share_breakdown(state):  # 占比%代码算好，允许解读引用
        allowed.add(pct)
    texts = [
        caliber.summary,
        caliber.detail.time_range,
        *caliber.detail.filters,
        *(caliber.detail.metrics or []),
        *(caliber.detail.dimensions or []),
    ]
    if state.query_spec is not None:
        spec = state.query_spec
        if spec.limit is not None:
            add(spec.limit)
        if spec.time_range is not None:
            texts.extend([spec.time_range.start, spec.time_range.end, spec.time_range.label])
        if spec.comparison is not None:
            for p in spec.comparison.periods:
                texts.extend([p.label, p.start, p.end])
    if state.template_match is not None:
        for v in state.template_match.bindings.values():
            if isinstance(v, str):
                texts.append(v)
            else:
                add(v)
    for t in texts:
        for n in _extract_numbers(t or ""):
            allowed.add(n)
    return allowed


def _grounded(sentence: str, allowed: set[Decimal]) -> bool:
    """句中每个数字都能在允许集合中按句中精度舍入命中（容差=格式化误差）。"""
    for n in _extract_numbers(sentence):
        quantum = Decimal(1).scaleb(n.as_tuple().exponent)
        ok = any(s.quantize(quantum, rounding=ROUND_HALF_UP) == n for s in allowed)
        if not ok:
            return False
    return True


def _one_sentence(text: str) -> bool:
    parts = [p for p in re.split(r"[。！？!?]+", text.strip()) if p.strip()]
    return len(parts) == 1


def validate_insight(text: str, allowed: set[Decimal]) -> list[str]:
    violations: list[str] = []
    if not _one_sentence(text):
        violations.append("不是严格一句")
    if _BAN_WORDS.search(text):
        violations.append("含建议/归因/预测措辞")
    if not _grounded(text, allowed):
        violations.append("含不来自真实行/对比值的数字")
    return violations


# ---------------------------------------------------------------------------
# 规则模板句兜底（只陈述事实，数字全部来自真实行/changes）
# ---------------------------------------------------------------------------
def _fmt(v: Any) -> str:
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return str(v)
    return format(d.normalize(), "f")


def fallback_insight(state: ChainState) -> str:
    table = state.table
    result: Optional[QueryResult] = state.query_result
    if table is None or result is None or not result.rows:
        return EMPTY_INSIGHT
    spec = state.query_spec
    metric_label = spec.metrics[0].label or spec.metrics[0].name if spec and spec.metrics else "数值"

    if state.comparison_result is not None and state.comparison_result.changes:
        ch = state.comparison_result.changes[-1]
        if ch.rate_delta is None:
            return f"{metric_label}{ch.key}变化 {ch.value_delta}，基期为 0 变化率不可比。"
        return f"{metric_label}{ch.key}变化 {ch.value_delta}，变化率 {ch.rate_delta}%。"

    cols = result.columns
    first = result.rows[0]
    if len(cols) >= 2:
        x_field = state.chart.x_field if state.chart else cols[0]
        y_fields = [c for c in cols if c != x_field]
        y = y_fields[0] if y_fields else cols[-1]
        if state.intent and state.intent.slot_form == "share":
            breakdown = _share_breakdown(state)
            if breakdown:
                parts = "、".join(f"{k} {_fmt(v)}（{p}%）" for k, v, p in breakdown)
                return f"{metric_label}分别为{parts}。"
            parts = "、".join(f"{row.get(x_field)} {_fmt(row.get(y))}" for row in result.rows)
            return f"{metric_label}分别为{parts}。"
        if state.intent and state.intent.slot_form == "trend":
            peak = max(result.rows, key=lambda r: Decimal(str(r.get(y) or 0)))
            return f"{metric_label}按天波动，{peak.get(x_field)}最高，为{_fmt(peak.get(y))}。"
        return f"{first.get(x_field)}的{metric_label}最高，为{_fmt(first.get(y))}。"
    # 单标量
    return f"{metric_label}为{_fmt(first.get(cols[0]))}。"


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------
async def writer(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    emit(deps, "node_started", {"node": "S8"})
    base: dict[str, Any] = {"trace_path": state.trace_path + ["S8"]}
    if state.table is None:  # 防御：正常链路不会发生
        return base
    if not state.table.rows:
        emit(deps, "node_finished", {"node": "S8"})
        return {**base, "insight": EMPTY_INSIGHT, "final_action": Action.ANSWER}

    caliber = build_caliber(state)
    allowed = _allowed_numbers(state, caliber)
    messages = prompts.build_messages(
        state.table,
        caliber,
        state.chart,
        state.comparison_result,
        share_percentages=[f"{k} {p}%" for k, _, p in _share_breakdown(state)] or None,
    )

    total_calls = 0
    insight: Optional[str] = None
    for _ in range(2):  # 首次 + 校验失败重生成 1 次
        result, attempts, err = await call_with_retry(
            lambda: deps.llm.complete(
                agent="writer",
                tier=registry.tier_for("writer"),
                messages=messages,
                schema=WriterOutput,
            )
        )
        total_calls += attempts
        if err is not None or result is None:
            break  # LLM 故障 → 直接兜底（解读失败永不阻断 answer）
        candidate = result.insight.strip()  # type: ignore[union-attr]
        if not validate_insight(candidate, allowed):
            insight = candidate
            break

    base["llm_calls"] = state.llm_calls + total_calls
    if insight is None:
        insight = fallback_insight(state)
        base["writer_fallback"] = True
        base["trace_notes"] = state.trace_notes + ["S8: 解读落地校验未过/LLM 故障，降级模板句（writer_fallback=true）"]
    emit(deps, "node_finished", {"node": "S8"})
    return {**base, "insight": insight, "final_action": Action.ANSWER}
