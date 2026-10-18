"""S5 Coder 提示词（SDD §3-S5）：QuerySpec + L0/L1/示例上下文 → 单条 SELECT。

示例只作写法参考，示例中的表不构成授权；lint 白名单按本次 L0 校验。
"""
from __future__ import annotations

import json
from typing import Any

from ...state import QuerySpec, RetrievalContext

SYSTEM = """你是 ChatBI 的「SQL 生成」智能体。给你一份无歧义的查询规格（QuerySpec）和库结构上下文（L0），把规格翻译成一条 SQL。严格遵守：

1. 只输出一条 SELECT 查询：禁止多语句、禁止任何写操作/DDL/DML、禁止注释。
2. 只能使用给定库结构（L0）中真实存在的表和列；示例（exemplars）只是写法参考，示例里出现的表不等于可用。
3. 严格按 QuerySpec 的指标表达式、维度、时间区间、口径过滤、排序、limit 生成；不要自由发挥加约束。
4. 对比模式（comparison）：生成一条带 period_key 的多时段聚合 SQL（UNION ALL 或按时段分组），每段绝对区间用 WHERE 条件区分，period_key 用 periods[].label 的字面值。
5. 趋势类（grain=day）：按日期列分组出日粒度行。
6. 不带 LIMIT 或 LIMIT 超过上限都可以——技术校验会自动修正，但你应尽量贴近规格。
7. lineage 如实填写：实际引用的表、列、口径说明、参考过的 exemplar_ids。lineage 的 tables/columns 只写 L0 中的表名/列名本身，不带 schema 前缀（不写 dw.）、不带表限定（写 channel_id 而不是 fact_order.channel_id）。
8. SQL 文本必须语法合法：关键字与标识符之间保留空白（禁止出现「)SELECT」「pJOIN」这类粘连），用空格或换行分隔均可。
9. CASE WHEN 派生的维度取值必须业务可读（如「新客」「老客」），不得用 是/否、true/false、0/1 这类裸布尔字面。GROUP BY 按列或表达式分组，不得按字符串常量分组。
10. 标识符/别名引用只用双引号，禁止 MySQL 反引号（`）；输出别名尽量简洁，用英文（如 new_customer_share）或双引号中文。

只输出符合给定 JSON Schema 的一个 JSON 对象。"""

RETRY_HINT = "\n\n上一次生成的 SQL 未通过技术校验，请逐条修正后重新生成：\n{errors}"


def _schema_brief(ctx: RetrievalContext) -> list[dict[str, Any]]:
    return [
        {
            "table": b.table,
            "comment": b.comment,
            "columns": [{"name": c.name, "type": c.type, "comment": c.comment} for c in b.columns],
        }
        for b in ctx.schema_blocks
    ]


def build_messages(
    spec: QuerySpec,
    ctx: RetrievalContext,
    *,
    lint_errors: list[str] | None = None,
) -> list[dict[str, str]]:
    user = {
        "query_spec": json.loads(spec.model_dump_json()),
        "schema_blocks_L0": _schema_brief(ctx),
        "caliber_defs_L1": ctx.caliber_defs,
        "exemplars": [
            {"question": e.question, "sql": e.sql, "chart_type": e.chart_type} for e in ctx.exemplars
        ],
    }
    system = SYSTEM
    if lint_errors:
        system = system + RETRY_HINT.format(errors="\n".join(f"- {e}" for e in lint_errors))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
