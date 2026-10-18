"""S8 Writer 提示词（SDD §3-S8）。

只给真实行 + 口径 + ChartSpec + 代码算好的对比值 + 风格示例；
禁止建议/归因/预测；空结果固定语义。Writer 拿不到 SQL、拿不到库。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml

from ...state import Caliber, ChartSpec, ComparisonResult, TableData

SYSTEM = """你是 ChatBI 的「解读」智能体。给你本次查询的真实结果行、口径说明、图表形态和（如有）代码算好的对比变化值，输出严格一句中文解读。严格遵守：

1. 严格一句中文，不超过 60 字。
2. 句中每个数字都必须出自给定的真实行、对比变化值或给定的占比百分比（share_percentages），不得编造、不得推算新数字。
3. 只陈述事实（谁最高、占比多少、同比升/降几个点、是否超过阈值），不解释原因。
4. 禁止出现建议（建议/应该/可以优化）、归因（因为/由于/原因是）、预测（预计/将会/可能涨到）措辞。
5. 对比类只陈述方向与幅度（如「GMV 同比增长 18.3%」）。
6. 参照风格示例的句式，但示例里没有数字可用。
7. 占比形态：若给定 share_percentages（代码算好的各组占比），直接引用其中的百分比陈述各组占比（如「老客占 74.5%、新客占 25.5%」）。

只输出符合给定 JSON Schema 的一个 JSON 对象。"""

_STYLE_EXAMPLES_PATH = Path(__file__).resolve().parent / "style_examples.yaml"


def load_style_examples() -> list[str]:
    try:
        data = yaml.safe_load(_STYLE_EXAMPLES_PATH.read_text(encoding="utf-8"))
        return [str(x) for x in (data or {}).get("examples", [])]
    except Exception:
        return []


def build_messages(
    table: TableData,
    caliber: Caliber,
    chart: Optional[ChartSpec],
    comparison: Optional[ComparisonResult],
    *,
    share_percentages: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    user: dict[str, Any] = {
        "columns": [c.model_dump() for c in table.columns],
        "rows": table.rows[:50],
        "caliber": caliber.model_dump(),
        "chart": chart.model_dump() if chart else None,
        "comparison": comparison.model_dump() if comparison else None,
        "share_percentages": share_percentages,  # 代码算好的各组占比（无则 null）
        "style_examples": load_style_examples(),
    }
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
    ]
