"""MockQueryRunner：按场景脚本返回行，支持超时/抛错/0 行；记录执行 SQL 与次数。"""
from __future__ import annotations

from typing import Any

from ...protocols import QueryTimeoutError
from ...state import QueryResult


class MockQueryRunner:
    """script: {"columns": [...], "rows": [...], "truncated": bool}
    或 {"error": Exception} / {"timeout": True} / {"empty": True}。"""

    def __init__(self, script: dict[str, Any] | None = None):
        self._script = script or {"columns": [], "rows": []}
        self.executed_sql: list[str] = []

    @property
    def call_count(self) -> int:
        return len(self.executed_sql)

    def set_script(self, script: dict[str, Any]) -> None:
        self._script = script

    async def run(self, sql: str) -> QueryResult:
        self.executed_sql.append(sql)
        s = self._script
        if s.get("timeout"):
            raise QueryTimeoutError("mock 查询超时")
        if "error" in s:
            err = s["error"]
            raise err if isinstance(err, Exception) else RuntimeError(str(err))
        if s.get("empty"):
            return QueryResult(columns=s.get("columns", []), rows=[], row_count=0, truncated=False)
        rows = [dict(r) for r in s.get("rows", [])]
        return QueryResult(
            columns=list(s.get("columns", [])),
            rows=rows,
            row_count=len(rows),
            truncated=bool(s.get("truncated", False)),
        )
