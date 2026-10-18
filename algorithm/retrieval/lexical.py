"""关键词检索通道（SDD §5：总有，兜底）。

对指标/维度/时间词与 schema 块名/注释、L1 资源文本做匹配打分排序；
不做事后比对、不作授权——只给 S4/S5 提供上下文。
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from ..state import SchemaBlock


def keywords_of(*parts: Iterable[str | None]) -> list[str]:
    """从 IntentSpec 各槽位收集非空关键词（保持原序去重）。"""
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for w in part:
            if w and w not in seen:
                seen.add(w)
                out.append(w)
    return out


def score_block(block: SchemaBlock, keywords: Sequence[str]) -> float:
    """按表名/注释/列名/列注释/枚举采样命中次数打分。"""
    if not keywords:
        return 0.0
    haystacks: list[str] = [block.table, block.comment]
    for c in block.columns:
        haystacks.extend([c.name, c.comment])
    for values in block.enum_samples.values():
        haystacks.extend(values)
    text = "\n".join(h for h in haystacks if h)
    return float(sum(text.count(k) for k in keywords))


def rank_blocks(blocks: Sequence[SchemaBlock], keywords: Sequence[str]) -> list[SchemaBlock]:
    """按相关度排序（稳定：同分保持原序）；六表规模下全量返回，供 S4/S5/lint 使用。"""
    scored = [(score_block(b, keywords), i, b) for i, b in enumerate(blocks)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [b for _, _, b in scored]


def match_resource_items(
    items: Sequence[dict[str, Any]], keywords: Sequence[str], *, top_k: int = 5
) -> list[dict[str, Any]]:
    """对 L1 资源条目（metrics/entities 字典）按文本命中打分，返回 top_k。"""
    if not items:
        return []
    if not keywords:
        return list(items)[:top_k]
    scored = []
    for i, item in enumerate(items):
        text = " ".join(str(v) for v in item.values())
        s = float(sum(text.count(k) for k in keywords))
        if s > 0:
            scored.append((s, i, item))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [it for _, _, it in scored[:top_k]]
