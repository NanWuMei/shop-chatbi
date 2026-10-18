"""app schema 五表的 SQLAlchemy2 模型（SDD-后端 §4.1 / FR-9 / FR-12）。

- 表名不写死 schema 前缀：APP 引擎连接参数 search_path=<app schema>（集成测试可换独立 schema）。
- exemplar / meta_schema_cache 含 vector 列，不走 ORM，建表语句在 storage/ddl.py。
- owner_id 固定 'default'（单用户，字段预留，无 RBAC）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)  # 首问原文
    owner_id: Mapped[str] = mapped_column(Text, nullable=False, default="default", server_default="default")
    inherited_spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 报表 continue-session 继承的 QuerySpec
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_question_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class MessageModel(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 会话内递增（FR-9）
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # user/clarification/answer/rejection/note（§3.3）
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)  # 终态切片，绝不含 sql/trace/query_spec
    internal: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 仅服务端：{sql, trace, query_spec} 三键（OQ-3）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ReportModel(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("owner_id", "title", name="uq_reports_owner_title"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False, default="default", server_default="default")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 来源 turn（uuid 字符串）
    question: Mapped[str] = mapped_column(Text, nullable=False)  # 报表原问题
    caliber: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    query_spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 供 recalibrate/refresh（仅服务端）
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)  # 仅服务端
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {insight, chart, table, comparison}
    data_time_range: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    queried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
