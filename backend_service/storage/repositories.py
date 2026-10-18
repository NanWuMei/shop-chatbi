"""app schema 仓储（SDD-后端 §4.2 / FR-9 / FR-11 / FR-12）。

- 仓储持有 sessionmaker，公开方法各自开显式事务（写方法单事务，失败整体回滚）；
- 返回纯 dict（uuid → str、datetime → ISO-8601），不向路由层泄漏 ORM 对象；
- 不做业务判断（NFR-1：storage 不感知 ChainResult 之外的业务语义）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .models import MessageModel, ReportModel, SessionModel


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _session_to_dict(m: SessionModel) -> dict:
    return {
        "id": str(m.id),
        "title": m.title,
        "owner_id": m.owner_id,
        "inherited_spec": m.inherited_spec,
        "message_count": m.message_count,
        "last_question_at": _iso(m.last_question_at),
        "created_at": _iso(m.created_at),
        "updated_at": _iso(m.updated_at),
    }


def _message_to_dict(m: MessageModel) -> dict:
    return {
        "id": str(m.id),
        "session_id": str(m.session_id),
        "seq": m.seq,
        "type": m.type,
        "payload": m.payload,
        "internal": m.internal,
        "created_at": _iso(m.created_at),
    }


def _report_to_dict(m: ReportModel) -> dict:
    return {
        "id": str(m.id),
        "owner_id": m.owner_id,
        "title": m.title,
        "session_id": str(m.session_id) if m.session_id else None,
        "source_turn_id": m.source_turn_id,
        "question": m.question,
        "caliber": m.caliber,
        "query_spec": m.query_spec,
        "sql": m.sql,
        "snapshot": m.snapshot,
        "data_time_range": m.data_time_range,
        "queried_at": _iso(m.queried_at),
        "created_at": _iso(m.created_at),
        "updated_at": _iso(m.updated_at),
    }


class SessionRepo:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def create(self, *, title: str, session_id: Optional[str] = None, inherited_spec: Optional[dict] = None) -> dict:
        with self._sf() as s, s.begin():
            m = SessionModel(title=title, inherited_spec=inherited_spec)
            if session_id:
                m.id = uuid.UUID(session_id)
            s.add(m)
            s.flush()
            return _session_to_dict(m)

    def get(self, session_id: str) -> Optional[dict]:
        with self._sf() as s:
            m = s.get(SessionModel, uuid.UUID(session_id))
            return _session_to_dict(m) if m else None

    def list(self, *, offset: int = 0, limit: int = 50) -> list[dict]:
        stmt = (
            select(SessionModel)
            .order_by(SessionModel.last_question_at.desc().nulls_last(), SessionModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        with self._sf() as s:
            return [_session_to_dict(m) for m in s.scalars(stmt)]

    def delete(self, session_id: str) -> bool:
        """删除会话；messages 级联删除（FK ondelete=CASCADE）。"""
        with self._sf() as s, s.begin():
            m = s.get(SessionModel, uuid.UUID(session_id))
            if m is None:
                return False
            s.delete(m)
            return True


class MessageRepo:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def append(
        self,
        session_id: str,
        *,
        type: str,
        payload: dict,
        internal: Optional[dict] = None,
        touch_question: bool = False,
    ) -> dict:
        """追加一条消息：会话内 seq 递增 + message_count 递增；user 消息同时更新 last_question_at。单事务。"""
        with self._sf() as s, s.begin():
            sid = uuid.UUID(session_id)
            session = s.get(SessionModel, sid)
            if session is None:
                raise ValueError(f"会话不存在：{session_id}")
            seq = (s.scalar(select(func.max(MessageModel.seq)).where(MessageModel.session_id == sid)) or 0) + 1
            m = MessageModel(session_id=sid, seq=seq, type=type, payload=payload, internal=internal)
            s.add(m)
            session.message_count = (session.message_count or 0) + 1
            if touch_question:
                session.last_question_at = datetime.now(timezone.utc)
            s.flush()
            return _message_to_dict(m)

    def list_by_session(self, session_id: str) -> list[dict]:
        stmt = select(MessageModel).where(MessageModel.session_id == uuid.UUID(session_id)).order_by(MessageModel.seq)
        with self._sf() as s:
            return [_message_to_dict(m) for m in s.scalars(stmt)]

    def count_by_session(self, session_id: str) -> int:
        stmt = select(func.count()).select_from(MessageModel).where(MessageModel.session_id == uuid.UUID(session_id))
        with self._sf() as s:
            return int(s.scalar(stmt) or 0)

    def find_answer_by_turn(self, turn_id: str) -> Optional[dict]:
        """按 payload.turn_id 反查已落库 answer 消息（报表保存/	recalibrate 的唯一依据，FR-12）。"""
        stmt = (
            select(MessageModel)
            .where(MessageModel.type == "answer", MessageModel.payload["turn_id"].astext == turn_id)
            .order_by(MessageModel.created_at.desc())
            .limit(1)
        )
        with self._sf() as s:
            m = s.scalars(stmt).first()
            return _message_to_dict(m) if m else None

    def find_clarification(self, clarify_id: str) -> Optional[dict]:
        stmt = (
            select(MessageModel)
            .where(MessageModel.type == "clarification", MessageModel.payload["clarify_id"].astext == clarify_id)
            .order_by(MessageModel.created_at.desc())
            .limit(1)
        )
        with self._sf() as s:
            m = s.scalars(stmt).first()
            return _message_to_dict(m) if m else None

    def update_clarification_status(self, clarify_id: str, status: str) -> bool:
        """澄清票据状态终态化（pending → confirmed/cancelled，FR-4②/AC-6）。"""
        with self._sf() as s, s.begin():
            found = s.scalars(
                select(MessageModel)
                .where(MessageModel.type == "clarification", MessageModel.payload["clarify_id"].astext == clarify_id)
                .order_by(MessageModel.created_at.desc())
                .limit(1)
            ).first()
            if found is None:
                return False
            payload = dict(found.payload or {})
            payload["status"] = status
            found.payload = payload
            return True


class ReportRepo:
    # 保存必需字段（缺一整体回滚，FR-12/AC-9）；query_spec/sql 允许为 null
    _REQUIRED_FIELDS = ("title", "question", "caliber", "snapshot", "queried_at")

    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def get(self, report_id: str) -> Optional[dict]:
        with self._sf() as s:
            m = s.get(ReportModel, uuid.UUID(report_id))
            return _report_to_dict(m) if m else None

    def find_by_title(self, owner_id: str, title: str) -> Optional[dict]:
        stmt = select(ReportModel).where(ReportModel.owner_id == owner_id, ReportModel.title == title).limit(1)
        with self._sf() as s:
            m = s.scalars(stmt).first()
            return _report_to_dict(m) if m else None

    def insert(self, owner_id: str, fields: dict) -> dict:
        """新存报表：单事务；必需字段缺失抛 ValueError → 整体回滚无残留（AC-9）。"""
        missing = [k for k in self._REQUIRED_FIELDS if not fields.get(k)]
        if missing:
            raise ValueError(f"报表字段缺失，整体回滚：{','.join(missing)}")
        with self._sf() as s, s.begin():
            m = ReportModel(
                owner_id=owner_id,
                title=fields["title"],
                session_id=uuid.UUID(fields["session_id"]) if fields.get("session_id") else None,
                source_turn_id=fields.get("source_turn_id"),
                question=fields["question"],
                caliber=fields.get("caliber"),
                query_spec=fields.get("query_spec"),
                sql=fields.get("sql"),
                snapshot=fields.get("snapshot"),
                data_time_range=fields.get("data_time_range"),
                queried_at=fields.get("queried_at"),
            )
            s.add(m)
            s.flush()
            return _report_to_dict(m)

    def overwrite(self, report_id: str, fields: dict) -> dict:
        """同名覆盖：同事务整包更新快照/caliber/query_spec/sql/data_time_range，id 不变（FR-12）。"""
        missing = [k for k in self._REQUIRED_FIELDS if not fields.get(k)]
        if missing:
            raise ValueError(f"报表字段缺失，整体回滚：{','.join(missing)}")
        with self._sf() as s, s.begin():
            m = s.get(ReportModel, uuid.UUID(report_id))
            if m is None:
                raise ValueError(f"报表不存在：{report_id}")
            m.title = fields["title"]
            m.session_id = uuid.UUID(fields["session_id"]) if fields.get("session_id") else m.session_id
            m.source_turn_id = fields.get("source_turn_id") or m.source_turn_id
            m.question = fields["question"]
            m.caliber = fields.get("caliber")
            m.query_spec = fields.get("query_spec")
            m.sql = fields.get("sql")
            m.snapshot = fields.get("snapshot")
            m.data_time_range = fields.get("data_time_range")
            m.queried_at = fields.get("queried_at")
            s.flush()
            return _report_to_dict(m)

    def list(self, owner_id: str, *, q: Optional[str] = None, offset: int = 0, limit: int = 50) -> list[dict]:
        stmt = select(ReportModel).where(ReportModel.owner_id == owner_id)
        if q:
            stmt = stmt.where(ReportModel.title.ilike(f"%{q}%"))
        stmt = stmt.order_by(ReportModel.created_at.desc()).offset(offset).limit(limit)
        with self._sf() as s:
            return [_report_to_dict(m) for m in s.scalars(stmt)]

    def rename(self, report_id: str, title: str) -> Optional[dict]:
        with self._sf() as s, s.begin():
            m = s.get(ReportModel, uuid.UUID(report_id))
            if m is None:
                return None
            m.title = title
            s.flush()
            return _report_to_dict(m)

    def delete(self, report_id: str) -> bool:
        with self._sf() as s, s.begin():
            m = s.get(ReportModel, uuid.UUID(report_id))
            if m is None:
                return False
            s.delete(m)
            return True
