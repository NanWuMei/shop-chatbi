"""S8 Writer 输出 schema（SDD §3-S8）：严格一句中文解读。"""
from __future__ import annotations

from pydantic import BaseModel


class WriterOutput(BaseModel):
    insight: str


__all__ = ["WriterOutput"]
