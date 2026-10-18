"""S4 Aligner 对齐输出 schema（SDD §3-S4）：规格钉死 / 四澄清码 / 两拒答码的结构化分支。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ...state import ClarifyReasonCode, QuerySpec


class AlignerOutput(BaseModel):
    """LLM 对齐结果：status 决定节点路由。

    - ok：query_spec 必填（Coder 直接可用）；
    - clarify：clarify_reason 四码之一 + clarify_focus（触发词，如「美妆」）；
    - not_answerable：reject_reason ∈ {NO_MATCHING_DATA, CALIBER_CONFLICT}。
    """

    status: Literal["ok", "clarify", "not_answerable"] = "ok"
    query_spec: Optional[QuerySpec] = None
    clarify_reason: Optional[ClarifyReasonCode] = None
    clarify_focus: Optional[str] = None
    clarify_title: Optional[str] = None
    reject_reason: Optional[Literal["NO_MATCHING_DATA", "CALIBER_CONFLICT"]] = None
    reject_text: Optional[str] = None
    suggestions: list[dict[str, str]] = Field(default_factory=list)


__all__ = ["AlignerOutput", "QuerySpec"]
