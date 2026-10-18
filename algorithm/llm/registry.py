"""模型档配置（SDD §5/§8.1）：Understand/Writer=fast，Aligner/Coder=strong，缺档回落 LLM_MODEL。"""
from __future__ import annotations

from ..config import Settings

TIER_FAST = "fast"
TIER_STRONG = "strong"

NODE_TIERS: dict[str, str] = {
    "understand": TIER_FAST,
    "writer": TIER_FAST,
    "aligner": TIER_STRONG,
    "coder": TIER_STRONG,
}


def tier_for(node: str) -> str:
    return NODE_TIERS[node]


def resolve_model(settings: Settings, node: str) -> str | None:
    """节点 → 档位 → 具体模型；未配档位回落全局默认模型。"""
    tier = tier_for(node)
    if tier == TIER_FAST:
        return settings.llm_model_fast or settings.llm_model
    return settings.llm_model_strong or settings.llm_model
