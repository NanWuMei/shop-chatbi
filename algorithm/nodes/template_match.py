"""S2 语义缓存 template_match（SDD §3-S2）：纯规则，不调 LLM。

槽位填满且无模板外新约束才 hit=true，直跳 S6；
模板库为空/无匹配/抽不齐/有新约束一律未命中走 S3（正常分叉，非失败）。
"""
from __future__ import annotations

from typing import Any, Optional

from ..protocols import deps_from_config, emit
from langchain_core.runnables import RunnableConfig

from ..state import ChainState, ChartType, IntentSpec, TemplateMatch


def _norm(words: list[str]) -> set[str]:
    return {w.strip().lower() for w in words if w and w.strip()}


def _resolve_time(time_expr: Optional[str], calendar: dict[str, Any]) -> Optional[dict[str, str]]:
    """用 L1 time-calendar 把口头时间解析为绝对区间；无日历/解析不出 → None（未命中）。"""
    if not time_expr or not calendar:
        return None
    expr = time_expr.strip()
    for key, rng in calendar.items():
        if key and (key in expr or expr in key):
            return {"label": key, "start": str(rng[0]), "end": str(rng[1])}
    return None


def _match_one(tpl: dict[str, Any], intent: IntentSpec, calendar: dict[str, Any]) -> Optional[TemplateMatch]:
    match = tpl.get("match") or {}
    tpl_metrics = _norm(match.get("metrics", []))
    tpl_dims = _norm(match.get("dimensions", []))
    if not tpl_metrics:
        return None

    # 槽位对齐：模板声明的指标/维度集合须与意图完全一致（不多不少）
    if _norm(intent.metrics) != tpl_metrics:
        return None
    if _norm(intent.dimensions) != tpl_dims:
        return None

    # 模板外新约束一律未命中
    if intent.filters or intent.comparison_intent:
        return None
    if intent.top_n is not None and not match.get("allow_top_n", False):
        return None
    if intent.sort and not match.get("allow_sort", False):
        return None

    # 时间槽位必须能落成绝对区间
    time_binding = _resolve_time(intent.time_expr, calendar)
    if time_binding is None:
        return None

    sql_t = tpl.get("sql") or ""
    if not sql_t.strip():
        return None
    sql = sql_t.replace("{start}", time_binding["start"]).replace("{end}", time_binding["end"])
    if "{start}" in sql or "{end}" in sql:
        return None  # 槽位未填满

    chart = tpl.get("chart_type")
    return TemplateMatch(
        hit=True,
        template_id=str(tpl.get("id")),
        sql=sql,
        chart_type=ChartType(chart) if chart else None,
        bindings={
            "time_label": time_binding["label"],
            "start": time_binding["start"],
            "end": time_binding["end"],
            "sort": intent.sort,
            "top_n": intent.top_n,
        },
    )


async def template_match(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    intent = state.intent
    hit: Optional[TemplateMatch] = None
    if intent is not None:
        for tpl in deps.resources.templates:
            hit = _match_one(tpl, intent, deps.resources.calendar)
            if hit is not None:
                break
    tm = hit or TemplateMatch(hit=False)
    out: dict[str, Any] = {"template_match": tm}
    if tm.hit:
        # 未命中是正常分叉（决策点），不进 trace.path、不发节点事件
        emit(deps, "node_started", {"node": "S2"})
        out["sql"] = tm.sql
        out["trace_path"] = state.trace_path + ["S2"]
        out["trace_notes"] = state.trace_notes + [f"S2: 命中模板 {tm.template_id}"]
        emit(deps, "node_finished", {"node": "S2"})
    return out
