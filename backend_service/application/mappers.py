"""ChainResult → 出前端报文 / 落库切片的唯一映射层（FR-6 / FR-7 / FR-9 / FR-10，AC-4）。

- 只从算法 ChainResult 派生，显式白名单构造 dict，确保 sql/trace/query_spec 绝不外泄（AC-7/B11）；
- stage 映射写死（SDD §3.2）：S1=understanding；S2/S3/S4=checking_caliber；S5~S8=querying；
- QUERY_TIMEOUT/QUERY_ERROR 拒答带可重试语义（FR-6）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from algorithm.state import ChainResult

# 节点 → SSE stage（写死映射，B3）
STAGE_BY_NODE: dict[str, tuple[str, str]] = {
    "S1": ("understanding", "正在理解问题"),
    "S2": ("checking_caliber", "正在核对口径"),
    "S3": ("checking_caliber", "正在核对口径"),
    "S4": ("checking_caliber", "正在核对口径"),
    "S5": ("querying", "正在取数"),
    "S6": ("querying", "正在取数"),
    "S7": ("querying", "正在取数"),
    "S8": ("querying", "正在取数"),
}

# 拒答 reason_code 中可重试的语义（QUERY_TIMEOUT/QUERY_ERROR）
RETRYABLE_REASONS = {"QUERY_TIMEOUT", "QUERY_ERROR"}

_REJECTION_ACTIONS = {"not_answerable", "query_gen_failed", "query_failed"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def action_name(result: ChainResult) -> str:
    a = result.action
    return a.value if hasattr(a, "value") else str(a)


def stage_of_node(node: str) -> Optional[tuple[str, str]]:
    return STAGE_BY_NODE.get(str(node or ""))


# ---- answer 信封（FR-7：五业务字段逐字镜像 + 后端信封字段） ----
def derive_data_time_range(result: ChainResult) -> Optional[dict]:
    """取 QuerySpec.time_range 派生（FR-7）；缺省 null。"""
    qs = result.query_spec
    if qs is not None and getattr(qs, "time_range", None) is not None:
        tr = qs.time_range
        return {"start": tr.start or "", "end": tr.end or "", "label": tr.label or ""}
    return None


def answer_slice(result: ChainResult, *, turn_id: str, session_id: str, queried_at: Optional[str] = None) -> dict:
    answer = result.answer
    return {
        "turn_id": turn_id,
        "session_id": session_id,
        "question": result.meta.question,
        "table": answer.table.model_dump(mode="json"),
        "chart": answer.chart.model_dump(mode="json") if answer.chart is not None else None,
        "insight": answer.insight,
        "caliber": answer.caliber.model_dump(mode="json"),
        "comparison": answer.comparison.model_dump(mode="json") if answer.comparison is not None else None,
        "data_time_range": derive_data_time_range(result),
        "queried_at": queried_at or utc_now_iso(),
        "saveable": bool(answer.table.rows),  # FR-7：saveable = answer 且 rows 非空（空结果 false）
    }


# ---- SSE 终态帧（FR-6：五终态帧 + 恒 done） ----
def terminal_frame(result: ChainResult, *, turn_id: str, session_id: str) -> tuple[str, dict]:
    action = action_name(result)
    if action == "answer":
        return "answer", answer_slice(result, turn_id=turn_id, session_id=session_id)
    if action == "clarify":
        data = result.clarify.model_dump(mode="json")
        data["status"] = "pending"  # 镜像载荷 + status:pending
        return "clarification", data
    if action in _REJECTION_ACTIONS:
        return "rejection", result.rejection.model_dump(mode="json")
    if action == "error":
        return "error", result.error.model_dump(mode="json")
    raise ValueError(f"未知终态 action：{action}")


# ---- 落库终态消息（FR-9：clarification/answer/rejection/note 四类；error 落 note） ----
def internal_of(result: ChainResult) -> dict:
    """internal 三键（OQ-3）：{sql, trace, query_spec}，取自 ChainResult 同名字段，仅服务端。"""
    return {
        "sql": result.sql,
        "trace": result.trace.model_dump(mode="json"),
        "query_spec": result.query_spec.model_dump(mode="json") if result.query_spec is not None else None,
    }


def terminal_message(result: ChainResult, *, turn_id: str, session_id: str) -> tuple[str, dict, dict]:
    """终态 → (消息类型, payload 切片, internal)。payload 一律不含 sql/trace/query_spec。"""
    action = action_name(result)
    if action == "answer":
        return "answer", answer_slice(result, turn_id=turn_id, session_id=session_id), internal_of(result)
    if action == "clarify":
        payload = result.clarify.model_dump(mode="json")
        payload["status"] = "pending"
        return "clarification", payload, internal_of(result)
    if action in _REJECTION_ACTIONS:
        return "rejection", result.rejection.model_dump(mode="json"), internal_of(result)
    if action == "error":
        # §3.3 无 error 消息类型：error 终态落 note（业务化文案，不带技术细节，B26）
        return "note", {"kind": "system", "text": "本次查询处理失败，请重试"}, internal_of(result)
    raise ValueError(f"未知终态 action：{action}")


def cancelled_message() -> tuple[str, dict]:
    return "note", {"kind": "cancelled", "text": "已取消"}


# ---- 多轮口径摘要（FR-10） ----
def build_conversation_summary(answer_payloads: list[dict], *, max_rounds: int = 5) -> str:
    """最近 N 条 answer 消息的 caliber.detail → 口径摘要文本（conversation_summary 通道）。"""
    lines: list[str] = []
    for p in answer_payloads[-max_rounds:]:
        d = (p.get("caliber") or {}).get("detail") or {}
        parts: list[str] = []
        if d.get("metrics"):
            parts.append("指标 " + "、".join(str(m) for m in d["metrics"]))
        if d.get("dimensions"):
            parts.append("维度 " + "、".join(str(x) for x in d["dimensions"]))
        tr = d.get("time_range")
        if isinstance(tr, dict) and (tr.get("start") or tr.get("end")):
            parts.append(f"时间 {tr.get('start') or ''}~{tr.get('end') or ''}")
        elif isinstance(tr, str) and tr:
            parts.append(f"时间 {tr}")
        if d.get("filters"):
            parts.append("筛选 " + "、".join(str(f) for f in d["filters"]))
        if d.get("comparison"):
            parts.append(f"对比 {d['comparison']}")
        if parts:
            lines.append("；".join(parts))
    return " || ".join(lines)


# ---- 报表继承口径（FR-15） ----
def inherited_summary_text(query_spec: dict) -> str:
    """inherited_spec（QuerySpec JSON）→ 拼入会话首问 conversation_summary 的口径摘要文本。"""
    if not isinstance(query_spec, dict):
        return ""
    parts: list[str] = []
    metrics = query_spec.get("metrics") or []
    if metrics:
        names = [m.get("name") or m.get("label") or str(m) if isinstance(m, dict) else str(m) for m in metrics]
        parts.append("指标 " + "、".join(str(n) for n in names if n))
    dims = query_spec.get("dimensions") or []
    if dims:
        names = [d.get("name") or str(d) if isinstance(d, dict) else str(d) for d in dims]
        parts.append("维度 " + "、".join(str(n) for n in names if n))
    tr = query_spec.get("time_range")
    if isinstance(tr, dict) and (tr.get("start") or tr.get("end") or tr.get("label")):
        label = tr.get("label") or f"{tr.get('start') or ''}~{tr.get('end') or ''}"
        parts.append(f"时间 {label}")
    comp = query_spec.get("comparison")
    if comp:
        mode = comp.get("mode") if isinstance(comp, dict) else comp
        parts.append(f"对比 {mode}")
    if not parts:
        return ""
    return "【继承口径】" + "；".join(parts)


# ---- 澄清确认拼接（FR-4② / AC-6） ----
def compose_clarified_question(original_question: str, clarify_payload: dict, selection: dict) -> str:
    """按 selection.type（option/time_preset/custom）拼 clarified_question。"""
    stype = selection.get("type")
    value = selection.get("value")
    if stype == "custom":
        text = str(value or "").strip()
        if not text:
            raise ValueError("custom 补充说明不能为空")
        return text
    if stype == "option":
        label = _option_label(clarify_payload.get("options") or [], value)
        return f"{original_question}（{label}）"
    if stype == "time_preset":
        if isinstance(value, dict) and (value.get("start") or value.get("end")):
            rng = f"{value.get('start') or ''} 至 {value.get('end') or ''}"
            return f"{original_question}（时间：{rng}）"
        label = _option_label(clarify_payload.get("options") or [], value)
        return f"{original_question}（时间：{label}）"
    raise ValueError(f"未知 selection.type：{stype}")


def _option_label(options: list, value: Any) -> str:
    for opt in options:
        if isinstance(opt, dict) and opt.get("value") == value:
            return str(opt.get("label") or value)
    return str(value)
