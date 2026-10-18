"""S4 Aligner 提示词（SDD §3-S4）：IntentSpec × RetrievalContext → QuerySpec / 澄清 / 拒答。"""
from __future__ import annotations

import json
from typing import Any

from ...state import IntentSpec, RetrievalContext

SYSTEM = """你是 ChatBI 的「对齐」智能体。给你用户的结构化意图（IntentSpec）和检索到的参考资料（库结构 L0、口径/实体 L1、示例），你的职责是把每一个槽位对上库里的具体东西，产出无歧义的查询规格（QuerySpec），或给出明确的澄清/拒答分支。严格遵守：

1. 你只能使用给定库结构（L0）中真实存在的表和列；口径/实体定义（L1）和示例只是参考，不构成新表。
2. 指标对齐：给出 table、expression（如 SUM(pay_amount - refund_amount)）、agg、fmt（money|percent|number）、必要口径过滤 filters（如 pay_status='已支付'），并在 caliber_note/caliber_summary 用业务语言写明口径（例如 AOV 必须明示分母是「支付订单数」还是其他）。
3. 时间对齐：把口头时间/档期归一为绝对日期 start/end（YYYY-MM-DD）。给了活动日历就按日历；没给就按常识推断，并把 inferred 标 true、在 caliber_summary 明示是推断的。
4. 对比意图：产出 comparison{mode: yoy|mom|custom, periods: 2~3 段绝对区间, value_fields}；所需时段明显超出数据覆盖范围 → not_answerable(NO_MATCHING_DATA) 并在 suggestions 给可答替代（如同比不行建议环比）。
5. 澄清分支（status=clarify，确认前不得出规格）：
   - 指标/维度词命中多个候选口径（如「美妆」同时命中一级类目与多个二级类目）→ clarify_reason=METRIC_DIM_AMBIGUOUS，clarify_focus 填触发词；
   - 缺时间且无法默认 → MISSING_TIME；
   - 问法过泛 → VAGUE；
   - 指代（刚才/那个）无法消解 → ANAPHORA_UNRESOLVED。
6. 拒答分支（status=not_answerable）：
   - 库中无任何可对应表/列（如品牌心智份额）→ reject_reason=NO_MATCHING_DATA，suggestions 引导到可答指标；
   - 口径自相矛盾（指标在该维度不可算，如「类目粒度转化率」——转化率需要流量分母，流量只有渠道维度）→ reject_reason=CALIBER_CONFLICT，suggestions 引导到可算口径（如各渠道转化率）。
7. 实体展开：用户说了实体别名（如「江浙沪」），在 entity_expansions 给出展开结果。
8. 排序/TopN：sort 保留（如 gmv desc），TopN 填 limit。
9. 没有 L1 字典时：依 L0 列名/列注释推断口径，必须在 caliber_summary 中明示推断口径，不允许因为缺字典而拒答。
10. 澄清轮次（clarify_round≥2）：用户已就上一轮澄清做过选择，选择内容已并入本次问题（通常在问题末尾括号内）。不得就用户已确认的槽位再次澄清；能据此钉死规格就必须产出 query_spec，实在仍无法定位才走 not_answerable。
11. 占比意图（slot_form=share）：指标用「分组值/总值×100%」口径（expression 窗口写法，如 SUM(gmv_amount)*100.0/SUM(SUM(gmv_amount)) OVER ()，fmt=percent），caliber_note 写明「占比=分组/总×100%」；不要退化为只出分组绝对值。

只输出符合给定 JSON Schema 的一个 JSON 对象。"""


def _schema_brief(ctx: RetrievalContext) -> list[dict[str, Any]]:
    out = []
    for b in ctx.schema_blocks:
        out.append(
            {
                "table": b.table,
                "comment": b.comment,
                "columns": [
                    {"name": c.name, "type": c.type, "comment": c.comment} for c in b.columns
                ],
                "enum_samples": b.enum_samples,
            }
        )
    return out


def build_messages(
    intent: IntentSpec,
    ctx: RetrievalContext,
    *,
    coverage: dict[str, Any] | None = None,
    calendar: dict[str, Any] | None = None,
    round: int = 1,
) -> list[dict[str, str]]:
    user = {
        "intent": json.loads(intent.model_dump_json()),
        "schema_blocks_L0": _schema_brief(ctx),
        "caliber_defs_L1": ctx.caliber_defs,
        "entity_defs_L1": ctx.entity_defs,
        "exemplars": [
            {"question": e.question, "sql": e.sql, "chart_type": e.chart_type} for e in ctx.exemplars
        ],
        "data_coverage": coverage or {},
        "promo_calendar": calendar or {},
        "clarify_round": round,
    }
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
