"""S5 Coder 生成输出 schema（SDD §3-S5）：sql + lineage（表/列/口径/exemplar_ids）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ...state import Lineage


class CoderOutput(BaseModel):
    sql: str
    lineage: Lineage = Field(default_factory=Lineage)


__all__ = ["CoderOutput", "Lineage"]
