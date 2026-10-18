"""双引擎（FR-18 / §5.1）：

- APP 引擎：SQLAlchemy2，仅 app schema 的 DML/DDL（create_all、仓储读写）；
- analytics 引擎：psycopg3 只读裸连接（search_path=dw、statement_timeout、default_transaction_read_only），
  供 QueryRunner 与 L0 SchemaProvider 消费；不提供任何写 API（NFR-1/AC-13）。
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def _to_sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def build_app_engine(app_database_url: str, *, schema: str = "app") -> Engine:
    """APP 引擎：SQLAlchemy2 + psycopg3 驱动；连接级 search_path 指向 app schema（懒连接）。

    search_path 追加 public：pgvector 扩展按初始化 SQL 驻留 public schema（FR-21），
    exemplar 的 vector 类型与 <=> 算子需在路径内才可解析；权限仍由角色控制，不受路径影响。
    """
    return create_engine(
        _to_sqlalchemy_url(app_database_url),
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={schema},public", "connect_timeout": 10},
    )


class AnalyticsEngine:
    """analytics 只读裸连接工厂（psycopg3，dict_row）。

    连接级三道兜底：search_path=dw、statement_timeout、default_transaction_read_only=on。
    懒建连：构造时不连库（TR-4.3），首次 connect 才建立。
    """

    def __init__(
        self,
        analytics_database_url: str,
        *,
        schema: str = "dw",
        statement_timeout_ms: int = 10000,
    ) -> None:
        self._conninfo = analytics_database_url
        self._options = (
            f"-c search_path={schema} "
            f"-c statement_timeout={statement_timeout_ms} "
            "-c default_transaction_read_only=on"
        )
        self.connect_count = 0

    def connect(self):
        """返回 psycopg 连接（调用方用 with 管理）；autocommit，仅读。"""
        self.connect_count += 1
        return psycopg.connect(
            self._conninfo,
            options=self._options,
            row_factory=dict_row,
            autocommit=True,
            connect_timeout=10,
        )
