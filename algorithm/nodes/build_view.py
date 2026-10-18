"""S7 出表+图 build_view（SDD §3-S7、§4）：Presenter 纯规则，不调 LLM。

图型对照（只看规格形态）：排名→bar｜趋势→trend_line｜对比→grouped_bar/trend_line｜
占比→pie｜单标量/空结果→chart=null。TableData 始终产出。
对比 changes 由代码用 Decimal 计算：金额 2 位、率 1 位；缺段/分母 0 → rate_delta=None。
「日期+维度+单指标」长表按形态规则透视成宽表（x=日期、每个维度取值一列=指标值，
形态触发不依赖 grain 取值），表图同形、图型钉 trend_line——前端 mapper 只消费 table rows，无独立图数据通道。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from ..protocols import deps_from_config, emit
from langchain_core.runnables import RunnableConfig

from ..state import (
    ChainState,
    ChartSeries,
    ChartSpec,
    ChartType,
    ComparisonChange,
    ComparisonResult,
    DimSpec,
    MetricSpec,
    QueryResult,
    QuerySpec,
    TableColumn,
    TableData,
)

_MONEY_Q = Decimal("0.01")
_RATE_Q = Decimal("0.1")


# ---------------------------------------------------------------------------
# Decimal 对比计算（私有；全程 Decimal，禁止 float 参与业务运算）
# ---------------------------------------------------------------------------
def _dec(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _match_period_label(key: str, labels: list[str]) -> Optional[str]:
    """行内 period 值 → spec 时段 label：精确优先；否则取唯一「互相包含」者
    （如 SQL 产字面值「前一周」而 spec label 是「大促前一周」）；多候选/无候选 → None（不强行配对）。"""
    if key in labels:
        return key
    if not key:
        return None
    candidates = [lb for lb in labels if key in lb or lb in key]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _resolve_field(name: str, columns: list[str]) -> Optional[str]:
    """规格字段名 → 结果列名：精确优先；否则唯一大小写不敏感命中（LLM 指标名 GMV/gmv 大小写漂移）。"""
    if name in columns:
        return name
    low = name.lower()
    hits = [c for c in columns if c.lower() == low]
    return hits[0] if len(hits) == 1 else None


def _ci_get(mapping: dict[str, str], key: str) -> Optional[str]:
    """大小写宽容查映射：精确 → 唯一大小写不敏感命中。"""
    if key in mapping:
        return mapping[key]
    low = key.lower()
    hits = [v for k, v in mapping.items() if k.lower() == low]
    return hits[0] if len(hits) == 1 else None


def _compute_changes(
    spec: QuerySpec, result: QueryResult, *, period_field: str, value_field: str
) -> ComparisonResult:
    comp = spec.comparison
    assert comp is not None
    labels = [p.label for p in comp.periods]
    vf = _resolve_field(value_field, result.columns)
    if vf is None:
        return ComparisonResult(mode=comp.mode, periods=labels, changes=[])

    # 各时段聚合值（多行求和；缺段 → None 如实为空）
    sums: dict[str, Optional[Decimal]] = {p.label: None for p in comp.periods}
    for row in result.rows:
        key = _match_period_label(str(row.get(period_field, "")), labels)
        if key is None:
            continue
        v = _dec(row.get(vf))
        if v is None:
            continue
        sums[key] = v if sums[key] is None else sums[key] + v  # type: ignore[operator]

    changes: list[ComparisonChange] = []
    for prev, cur in zip(comp.periods, comp.periods[1:]):
        a = sums.get(prev.label)
        b = sums.get(cur.label)
        if a is None or b is None:
            continue  # 缺段：该对变化如实为空，不编造
        delta = (b - a).quantize(_MONEY_Q, rounding=ROUND_HALF_UP)
        if a == 0:
            rate: Optional[str] = None  # 分母为 0 → 不可比，严禁编造无穷大
        else:
            rate = str(((b - a) / a * 100).quantize(_RATE_Q, rounding=ROUND_HALF_UP))
        changes.append(
            ComparisonChange(key=f"{cur.label} vs {prev.label}", value_delta=str(delta), rate_delta=rate)
        )
    return ComparisonResult(mode=comp.mode, periods=labels, changes=changes)


# ---------------------------------------------------------------------------
# 图型对照（FR-12）
# ---------------------------------------------------------------------------
def _is_day_grain(grain: str) -> bool:
    """grain 契约为 total|day，但 aligner 实测会产出 daily/day_channel 等变体，宽容识别。"""
    g = (grain or "").lower()
    return g == "daily" or g.startswith("day")


def _pick_chart_type(spec: Optional[QuerySpec], result: QueryResult, template_chart: Optional[str]) -> Optional[ChartType]:
    if result.row_count == 0 or not result.rows:
        return None  # 空结果不硬画图
    if template_chart:
        return ChartType(template_chart)
    if spec is None:
        return ChartType.BAR if result.columns else None
    if spec.comparison is not None:
        return ChartType.TREND_LINE if _is_day_grain(spec.grain) else ChartType.GROUPED_BAR
    if not spec.dimensions:
        return None  # 单标量只出表
    if _is_day_grain(spec.grain):
        return ChartType.TREND_LINE
    if spec.sort or spec.limit:
        return ChartType.BAR
    return ChartType.BAR


def _is_share(spec: Optional[QuerySpec], intent_slot_form: str) -> bool:
    return intent_slot_form == "share"


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------
async def build_view(state: ChainState, config: RunnableConfig) -> dict[str, Any]:
    deps = deps_from_config(config)
    emit(deps, "node_started", {"node": "S7"})
    result = state.query_result
    spec = state.query_spec
    if result is None:  # 防御：正常链路不会发生
        return {"trace_path": state.trace_path + ["S7"]}

    display_limit = deps.settings.row_limit_default
    metrics: list[MetricSpec] = spec.metrics if spec else []
    dims: list[DimSpec] = spec.dimensions if spec else []
    slot_form = state.intent.slot_form if state.intent else ""

    # 列名 → 业务名/格式（透视与常规两路共用）
    label_by_field: dict[str, str] = {}
    fmt_by_field: dict[str, str] = {}
    for d in dims:
        if d.column:
            label_by_field[d.column] = d.label or d.name
            fmt_by_field[d.column] = "text"
    for m in metrics:
        key = m.name
        label_by_field[key] = m.label or m.name
        fmt_by_field[key] = m.fmt if m.fmt in ("money", "percent", "number") else "number"

    # 对比 changes（代码 Decimal 计算，Writer 不自己算）
    comparison_result: Optional[ComparisonResult] = None
    period_field: Optional[str] = None
    if spec is not None and spec.comparison is not None:
        value_field = spec.comparison.value_fields[0] if spec.comparison.value_fields else (
            metrics[0].name if metrics else "value"
        )
        period_field = _find_period_field(result)
        if period_field is not None:
            comparison_result = _compute_changes(spec, result, period_field=period_field, value_field=value_field)

    # 图型判定（先定类型，趋势透视依赖它）
    template_chart = state.template_match.chart_type if state.template_match else None
    ctype = _pick_chart_type(spec, result, template_chart)
    if _is_share(spec, slot_form) and result.rows:
        ctype = ChartType.PIE

    # 趋势长表→宽表透视（对比段列 period_key 已是宽形，不参与）：
    # 形态匹配（日期维+另 1 维+单指标）即透视，不再依赖图型先判为趋势；透视成功图型钉 trend_line。
    # 模板指定图型时尊重模板，仅趋势类模板图型参与透视。
    pivot: Optional[tuple[str, list[str], list[TableColumn], list[dict[str, Any]]]] = None
    if (
        spec is not None
        and spec.comparison is None
        and period_field is None
        and result.rows
        and ctype != ChartType.PIE
        and (template_chart is None or ctype in (ChartType.LINE, ChartType.TREND_LINE))
    ):
        pivot = _pivot_trend_long_to_wide(result, dims, fmt_by_field, label_by_field)
        if pivot is not None:
            ctype = ChartType.TREND_LINE

    if pivot is not None:
        x_field, series_fields, wide_columns, wide_rows = pivot
        table = TableData(
            columns=wide_columns,
            rows=wide_rows,
            truncated=result.truncated,
            display_limit=display_limit,
        )
        chart = ChartSpec(
            type=ctype,  # type: ignore[arg-type]
            x_field=x_field,
            series=[ChartSeries(field=f, label=f) for f in series_fields],
            switchable=[],
        )
    else:
        # TableData：列名用规格业务名，行即查询结果（大小写宽容：LLM 指标名可能 GMV/gmv 漂移）
        columns = [
            TableColumn(
                field=c,
                label=_ci_get(label_by_field, c) or c,
                format=_ci_get(fmt_by_field, c) or "text",
            )
            for c in result.columns
        ]
        table = TableData(
            columns=columns,
            rows=result.rows,
            truncated=result.truncated,
            display_limit=display_limit,
        )
        chart = None
        if ctype is not None:
            x_field = _pick_x_field(result, dims, period_field)
            series = [
                ChartSeries(field=c, label=_ci_get(label_by_field, c) or c)
                for c in result.columns
                if c != x_field
            ]
            chart = ChartSpec(type=ctype, x_field=x_field, series=series, switchable=[])

    out: dict[str, Any] = {
        "table": table,
        "chart": chart,
        "comparison_result": comparison_result,
        "trace_path": state.trace_path + ["S7"],
    }
    emit(deps, "node_finished", {"node": "S7"})
    return out


def _find_period_field(result: QueryResult) -> Optional[str]:
    for cand in ("period_key", "period", "period_label"):
        if cand in result.columns:
            return cand
    return result.columns[0] if result.columns else None


_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _looks_like_date_column(col: str, rows: list[dict[str, Any]]) -> bool:
    if "date" in col.lower():
        return True
    sample = [str(r.get(col, "")) for r in rows[:5]]
    return bool(sample) and all(_DATE_PREFIX.match(v) for v in sample)


def _match_dim_column(d: DimSpec, columns: list[str]) -> Optional[str]:
    """维度列匹配结果集：物理列名优先，退化到业务名/标签（Coder 可能把维度别名成中文，实测发生过）。"""
    for cand in (d.column, d.name, d.label):
        if cand and cand in columns:
            return cand
    return None


def _pivot_trend_long_to_wide(
    result: QueryResult,
    dims: list[DimSpec],
    fmt_by_field: dict[str, str],
    label_by_field: dict[str, str],
) -> Optional[tuple[str, list[str], list[TableColumn], list[dict[str, Any]]]]:
    """趋势长表（日期+维度+单指标）→ 宽表（x=日期、每个维度取值一列=指标值）。

    仅当恰好 2 个维度列（其一为日期列）+ 恰好 1 个指标列才透视；
    形状不符返回 None，调用方保持原长表 fallback。缺组合单元格如实留 None。
    """
    dim_cols: list[str] = []
    for d in dims:
        m = _match_dim_column(d, result.columns)
        if m is not None and m not in dim_cols:
            dim_cols.append(m)
    if len(dim_cols) != 2:
        return None
    date_col = next((c for c in dim_cols if _looks_like_date_column(c, result.rows)), None)
    if date_col is None:
        return None
    series_col = dim_cols[0] if dim_cols[1] == date_col else dim_cols[1]
    metric_cols = [c for c in result.columns if c not in (date_col, series_col)]
    if len(metric_cols) != 1:
        return None
    metric_col = metric_cols[0]

    x_values: list[str] = []
    series_values: list[str] = []
    cells: dict[tuple[str, str], Any] = {}
    for row in result.rows:
        xv = str(row.get(date_col, ""))
        sv = str(row.get(series_col, ""))
        if xv not in x_values:
            x_values.append(xv)
        if sv not in series_values:
            series_values.append(sv)
        cells[(xv, sv)] = row.get(metric_col)
    x_values.sort()

    metric_fmt = fmt_by_field.get(metric_col, "number")
    columns = [
        TableColumn(field=date_col, label=label_by_field.get(date_col, date_col), format="text"),
        *[TableColumn(field=sv, label=sv, format=metric_fmt) for sv in series_values],
    ]
    wide_rows = [
        {date_col: xv, **{sv: cells.get((xv, sv)) for sv in series_values}}
        for xv in x_values
    ]
    return date_col, series_values, columns, wide_rows


def build_caliber(state: ChainState) -> "Caliber":
    """组装口径载荷：QuerySpec 优先，S2 模板快路径用 bindings 兜底。"""
    from ..state import Caliber, CaliberDetail

    spec = state.query_spec
    if spec is not None:
        time_range = ""
        if spec.comparison is not None and spec.comparison.periods:
            time_range = "；".join(f"{p.label} {p.start}~{p.end}" for p in spec.comparison.periods)
        elif spec.time_range is not None:
            tr = spec.time_range
            time_range = f"{tr.label} {tr.start}~{tr.end}".strip() if tr.label else f"{tr.start}~{tr.end}"
        summary = spec.caliber_summary or "；".join(
            [m.caliber_note for m in spec.metrics if m.caliber_note]
        )
        filters = list(spec.caliber_filters)
        for m in spec.metrics:
            filters.extend(m.filters)
        return Caliber(
            summary=summary or "按库结构列注释推断的口径",
            detail=CaliberDetail(
                metrics=[m.label or m.name for m in spec.metrics],
                dimensions=[d.label or d.name for d in spec.dimensions],
                time_range=time_range,
                filters=filters,
                comparison=spec.comparison.mode if spec.comparison else None,
            ),
        )
    # S2 模板快路径：无 QuerySpec，用模板绑定组装最小口径
    tm = state.template_match
    bindings = tm.bindings if tm else {}
    time_range = ""
    if bindings.get("start"):
        label = bindings.get("time_label") or ""
        time_range = f"{label} {bindings['start']}~{bindings['end']}".strip()
    return Caliber(
        summary=f"模板口径（{tm.template_id}）" if tm and tm.template_id else "模板口径",
        detail=CaliberDetail(time_range=time_range),
    )


def _pick_x_field(result: QueryResult, dims: list[DimSpec], period_field: Optional[str]) -> str:
    if period_field is not None:
        return period_field
    for d in dims:
        if d.column and d.column in result.columns:
            return d.column
    return result.columns[0] if result.columns else ""
