"""QueryRunner（FR-19 / AC-14）：实现算法 QueryRunner 协议，执行层最后兜底。

- 执行前守卫：sqlglot 解析，仅允许单条只读 SELECT（含 UNION/UNION ALL 组合，对齐 SDD-算法应用 §S5 对比 SQL）；拒绝多语句/写操作（不做业务改写）；
- 运行时：statement_timeout 由 analytics 连接参数生效；取 ROW_LIMIT_MAX+1 行判截断回传 truncated；
- 归一：超时 → QueryTimeoutError（算法归一 QUERY_TIMEOUT）；其余执行异常原样上抛（算法归一 QUERY_ERROR）；
- 取消协作（FR-8）：执行前查 cancel 标志，已取消则抛 CancelledError，由服务层收 cancelled 终态。
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

import psycopg
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from algorithm.protocols import QueryTimeoutError
from algorithm.state import QueryResult

# 任何写操作/DDL/事务控制的 AST 节点类型（树内出现即拒绝）
_WRITE_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Merge,
    exp.TruncateTable,
    exp.Grant,
    exp.Command,
    exp.Commit,
    exp.Rollback,
)


class SqlGuardError(ValueError):
    """执行前守卫拒绝（多语句/非 SELECT/写操作/解析失败）。"""


def validate_single_select(sql: str) -> None:
    """单条只读 SELECT 守卫（纯函数，离线可测，不触库）。

    顶层允许 Select 或 Union（UNION/UNION ALL 组合的只读 SELECT，对齐 SDD-算法应用 §S5）；
    树内任何写操作/DDL/事务控制节点仍拒。
    """
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as e:
        raise SqlGuardError("SQL 解析失败，仅允许单条 SELECT 查询") from e
    if len(statements) != 1:
        raise SqlGuardError("仅允许单条 SELECT 查询语句")
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise SqlGuardError("仅允许 SELECT 查询")
    for node in stmt.walk():
        if isinstance(node, _WRITE_NODE_TYPES):
            raise SqlGuardError("仅允许只读 SELECT 查询")


class PgQueryRunner:
    """psycopg 裸连接实现；不解析、不改写业务 SQL 文本（TR-3.3）。"""

    def __init__(
        self,
        analytics,  # AnalyticsEngine 或同形 connect() 的替身
        *,
        row_limit_max: int = 1000,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._analytics = analytics
        self._row_limit_max = row_limit_max
        self._cancel_check = cancel_check

    async def run(self, sql: str) -> QueryResult:
        validate_single_select(sql)
        if self._cancel_check is not None and self._cancel_check():
            raise asyncio.CancelledError()
        try:
            return await asyncio.to_thread(self._run_sync, sql)
        except psycopg.errors.QueryCanceled as e:  # statement_timeout 触发（SQLSTATE 57014）
            raise QueryTimeoutError(str(e)) from e

    def _run_sync(self, sql: str) -> QueryResult:
        if self._cancel_check is not None and self._cancel_check():
            raise asyncio.CancelledError()
        with self._analytics.connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            if cur.description is None:
                raise SqlGuardError("语句未返回结果集，仅允许 SELECT 查询")
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(self._row_limit_max + 1)  # 多取 1 行判截断（FR-19）
        truncated = len(rows) > self._row_limit_max
        rows = rows[: self._row_limit_max]
        return QueryResult(
            columns=columns,
            rows=[dict(r) for r in rows],  # dict_row 连接：行已是 dict（ChainResult 契约）
            row_count=min(len(rows), self._row_limit_max),
            truncated=truncated,
        )
