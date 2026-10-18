"""TR-3.1：守卫拒绝多语句/非 SELECT（纯函数，不触库）+ 截断判定用伪造游标。"""
import asyncio

import pytest

from backend_service.data.query_runner import PgQueryRunner, SqlGuardError, validate_single_select
from algorithm.protocols import QueryTimeoutError


# ---- 单条 SELECT 守卫（离线纯函数） ----
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select channel, sum(gmv) from dw.fact_order_item group by 1 order by 2 desc limit 10",
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t",  # CTE 仍是只读 SELECT
        "SELECT * FROM t WHERE a IN (SELECT b FROM u)",  # 子查询
        "SELECT '今年' AS period_key, 1 AS v UNION ALL SELECT '去年', 2 LIMIT 500",  # UNION 组合只读 SELECT（对齐算法 §S5 对比 SQL）
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t UNION ALL SELECT 2",  # CTE + UNION
    ],
)
def test_guard_accepts_single_select(sql):
    validate_single_select(sql)  # 不抛即通过


@pytest.mark.parametrize(
    "sql",
    [
        "",  # 空语句
        "SELECT 1; SELECT 2",  # 多语句
        "SELECT 1; DROP TABLE t",  # 夹带写
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "DROP TABLE t",
        "CREATE TABLE t (a int)",
        "ALTER TABLE t ADD COLUMN b int",
        "TRUNCATE TABLE t",
        "GRANT SELECT ON t TO ro",
        "COMMIT",
        "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",  # 数据修改 CTE（树内写操作）
        "  /* 注释 */  ",  # 无语句
    ],
)
def test_guard_rejects(sql):
    with pytest.raises(SqlGuardError):
        validate_single_select(sql)


def test_guard_rejects_unparseable():
    with pytest.raises(SqlGuardError):
        validate_single_select("SELEC ???FROM")


# ---- 截断判定：伪造游标结果（不触库） ----
class _Col:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeCursor:
    """与真实 AnalyticsEngine 的 dict_row 行为一致：fetchmany 返回 dict 行。"""

    def __init__(self, rows: list[dict], description_names: list[str]) -> None:
        self._rows = rows
        self.description = [_Col(n) for n in description_names] if description_names is not None else None
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def fetchmany(self, n: int) -> list[dict]:
        return self._rows[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeAnalytics:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.connect_count = 0

    def connect(self) -> FakeConn:
        self.connect_count += 1
        return FakeConn(self._cursor)


def _runner_with_rows(rows: list[dict], *, row_limit_max: int = 1000) -> tuple[PgQueryRunner, FakeAnalytics]:
    cur = FakeCursor(rows, ["channel", "gmv"])
    analytics = FakeAnalytics(cur)
    return PgQueryRunner(analytics, row_limit_max=row_limit_max), analytics


def test_truncation_when_more_than_limit():
    rows = [{"channel": f"c{i}", "gmv": i} for i in range(1001)]  # max+1 行
    runner, analytics = _runner_with_rows(rows, row_limit_max=1000)
    result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(runner.run("SELECT channel, gmv FROM t"))
    assert result.truncated is True
    assert result.row_count == 1000
    assert result.columns == ["channel", "gmv"]
    assert analytics.connect_count == 1


def test_no_truncation_at_exact_limit():
    rows = [{"channel": f"c{i}", "gmv": i} for i in range(1000)]
    runner, _ = _runner_with_rows(rows, row_limit_max=1000)
    result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(runner.run("SELECT channel, gmv FROM t"))
    assert result.truncated is False
    assert result.row_count == 1000


def test_rows_keep_real_values():
    """回归：dict_row 连接行已是 dict，值必须原样保留（曾误按 tuple 重打包成 {列名: 列名}）。"""
    rows = [{"channel": "抖音", "gmv": 123}, {"channel": "天猫", "gmv": 45}]
    runner, _ = _runner_with_rows(rows)
    result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(runner.run("SELECT channel, gmv FROM t"))
    assert result.rows == [{"channel": "抖音", "gmv": 123}, {"channel": "天猫", "gmv": 45}]


def test_guard_runs_before_connect():
    """守卫拒绝的语句不触库（连接计数 0）。"""
    runner, analytics = _runner_with_rows([{"channel": "a", "gmv": 1}])
    loop = asyncio.get_event_loop_policy().new_event_loop()
    with pytest.raises(SqlGuardError):
        loop.run_until_complete(runner.run("DELETE FROM t"))
    assert analytics.connect_count == 0


def test_cancel_check_short_circuits():
    rows = [{"c": "a"}]
    cur = FakeCursor(rows, ["c"])
    runner = PgQueryRunner(FakeAnalytics(cur), row_limit_max=10, cancel_check=lambda: True)
    loop = asyncio.get_event_loop_policy().new_event_loop()
    with pytest.raises(asyncio.CancelledError):
        loop.run_until_complete(runner.run("SELECT c FROM t"))


def test_psycopg_query_canceled_maps_to_timeout():
    """statement_timeout 触发的 QueryCanceled 归一为 QueryTimeoutError（离线用假连接注入）。"""
    import psycopg

    class CanceledCursor:
        def __enter__(self):
            raise psycopg.errors.QueryCanceled()

        def __exit__(self, *exc):
            return False

    class CanceledConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return CanceledCursor()

    class CanceledAnalytics:
        def connect(self):
            return CanceledConn()

    runner = PgQueryRunner(CanceledAnalytics(), row_limit_max=10)
    loop = asyncio.get_event_loop_policy().new_event_loop()
    with pytest.raises(QueryTimeoutError):
        loop.run_until_complete(runner.run("SELECT 1"))
