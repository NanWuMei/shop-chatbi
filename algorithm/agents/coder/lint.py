"""S5 lint 技术校验（SDD §3-S5，spec FR-10）：纯规则，不调 LLM。

五规则：
① 表白名单 ∈ 本次 L0（CTE 名视为派生表，不算白名单外）；
② 仅单条 SELECT（禁多语句/DDL/DML/写操作/注释夹带）；
③ 列归属校验（限定列 ∈ 归属表列；非限定列 ∈ 作用域任一表列）；
④ LIMIT 缺失注入默认值、超限压到上限（默认 500 / 硬顶 1000，参数可注入）；
⑤ GROUP BY 不得使用字符串常量（sqlglot 语法放行但 Postgres 运行时 SyntaxError；整数位次合法）。

另校验 lineage 表/列 ⊆ L0（TR-9.5）。不通过回结构化 lint 错误。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import sqlglot
from sqlglot import exp

from ...state import Lineage, SchemaBlock

_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Merge,
    exp.Grant,
    exp.Commit,
)


@dataclass
class LintResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    sql: str = ""  # ok 时为修正后（可能注入/压限 LIMIT）的 SQL
    limit_applied: Optional[int] = None


def lint_sql(
    sql: str,
    blocks: Sequence[SchemaBlock],
    *,
    lineage: Optional[Lineage] = None,
    default_limit: int = 500,
    max_limit: int = 1000,
) -> LintResult:
    errors: list[str] = []
    tables: dict[str, set[str]] = {b.table: set(b.column_names()) for b in blocks}

    if "--" in sql or "/*" in sql:
        errors.append("不允许包含 SQL 注释")

    if "`" in sql:  # 实测 LLM 写 MySQL 反引号别名，sqlglot/PG 均不认；给可行动的报错而不是裸解析错误
        errors.append("禁止用反引号（`）引用标识符/别名：Postgres 只认双引号（如 \"新客GMV占比\"），别名建议用简洁英文")

    try:
        statements = [s for s in sqlglot.parse(sql) if s is not None]
    except Exception as e:
        return LintResult(ok=False, errors=[f"SQL 解析失败：{e}"], sql=sql)
    if len(statements) != 1:
        return LintResult(ok=False, errors=["只允许单条 SELECT 语句（禁止多语句）"], sql=sql)

    root = statements[0]

    # 规则②：仅 SELECT（含 CTE / UNION ALL 对比写法）
    if not isinstance(root, (exp.Select, exp.Union)):
        return LintResult(ok=False, errors=["只允许 SELECT 查询（禁止写操作/DDL/DML）"], sql=sql)
    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            return LintResult(ok=False, errors=[f"禁止的语句类型：{type(node).__name__}"], sql=sql)

    # CTE 派生表及其输出列
    cte_outputs: dict[str, set[str]] = {}
    for cte in root.find_all(exp.CTE):
        name = cte.alias
        if not name:
            continue
        cols: set[str] = set()
        sub = cte.this
        if isinstance(sub, exp.Select):
            for s in sub.expressions:
                cols.add(s.alias_or_name)
        cte_outputs[name] = cols

    # FROM/JOIN 子查询派生表别名同 CTE 处理（实测 LLM 会写 (SELECT ...) d1 再引 d1.xxx）
    for sub in root.find_all(exp.Subquery):
        alias = sub.alias
        if not alias or alias in cte_outputs:
            continue
        inner = sub.this
        if isinstance(inner, exp.Select):
            cols = {s.alias_or_name for s in inner.expressions}
            cols.discard("*")  # SELECT * 无法穷举输出列，留空集跳过列归属检查
            cte_outputs[alias] = cols

    # 规则①：表白名单
    alias_to_table: dict[str, str] = {}
    for t in root.find_all(exp.Table):
        name = t.name
        if t.alias:
            alias_to_table[t.alias] = name  # 先登记别名：CTE 引用（FROM payers p）也要可用
        if name in cte_outputs:
            continue
        if name not in tables:
            errors.append(f"表 {name} 不在本次数据库表白名单内")

    # 规则③：列归属
    in_scope_real = [n for n in (t.name for t in root.find_all(exp.Table)) if n in tables]
    # SELECT 显式别名（仅 AS 命名；ORDER BY/GROUP BY/HAVING 可引用，不算表列）
    output_aliases: set[str] = set()
    for sel in root.find_all(exp.Select):
        for s in sel.expressions:
            if isinstance(s, exp.Alias) and s.alias:
                output_aliases.add(s.alias)
    seen_col_errors: set[str] = set()

    def col_err(msg: str) -> None:
        if msg not in seen_col_errors:
            seen_col_errors.add(msg)
            errors.append(msg)

    for col in root.find_all(exp.Column):
        cname = col.name
        if not cname or cname == "*":
            continue
        if cname in output_aliases:
            continue
        qualifier = col.table
        if qualifier:
            target = alias_to_table.get(qualifier, qualifier)
            if target in cte_outputs:
                if cte_outputs[target] and cname not in cte_outputs[target]:
                    col_err(f"列 {qualifier}.{cname} 不在派生表 {target} 的输出列内")
            elif target in tables:
                if cname not in tables[target]:
                    col_err(f"列 {qualifier}.{cname} 不存在于表 {target}")
            else:
                col_err(f"引用了未知表/别名 {qualifier}")
        else:
            pool: set[str] = set()
            for tn in in_scope_real:
                pool |= tables[tn]
            for cols in cte_outputs.values():
                pool |= cols
            if pool and cname not in pool:
                col_err(f"列 {cname} 在查询涉及的表中不存在")

    # 规则⑤：GROUP BY 字符串常量（实测 LLM 会写 GROUP BY '今年618'，PG 运行时才炸；整数位次 GROUP BY 1 合法放行）
    group_by_str_const = False
    for grp in root.find_all(exp.Group):
        for g in grp.expressions:
            if isinstance(g, exp.Literal) and g.is_string:
                group_by_str_const = True
                break
        if group_by_str_const:
            break
    if group_by_str_const:
        errors.append("GROUP BY 不得使用字符串常量（应按列或 CASE 表达式分组，如 GROUP BY period_key）")

    # 规则④：LIMIT 注入/压限
    limit_applied: Optional[int] = None
    limit_node = root.args.get("limit")
    if limit_node is None:
        root.set("limit", exp.Limit(expression=exp.Literal.number(default_limit)))
        limit_applied = default_limit
    else:
        try:
            current = int(limit_node.expression.name)
            if current > max_limit:
                limit_node.set("expression", exp.Literal.number(max_limit))
                limit_applied = max_limit
            else:
                limit_applied = current
        except (ValueError, AttributeError):
            errors.append("LIMIT 取值非法")

    # lineage ⊆ L0（表/列名宽容剥 schema/限定前缀：LLM 实测会写 dw.fact_order、fact_order.channel_id）
    if lineage is not None:
        for tn in lineage.tables:
            if tn.split(".")[-1] not in tables:
                errors.append(f"lineage 表 {tn} 不在 L0 内")
        for cn in lineage.columns:
            col = cn.split(".")[-1]
            hit = any(col in cols for cols in tables.values())
            if not hit:
                errors.append(f"lineage 列 {cn} 不在 L0 内")

    if errors:
        return LintResult(ok=False, errors=errors, sql=sql)
    return LintResult(ok=True, errors=[], sql=root.sql(), limit_applied=limit_applied)
