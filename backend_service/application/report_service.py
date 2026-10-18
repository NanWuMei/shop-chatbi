"""report_service（FR-12 ~ FR-15 / AC-9 ~ AC-12）：报表沉淀、直读快照、刷新与继承会话。

- 保存只认服务端已落库的 answer 消息（按 payload.turn_id 反查，不信任前端自报内容）；
- 打开/列表/改名/删除只读快照，绝不调 run_chain、不连 analytics（AC-10 spy 实证）；
- 刷新取存的 query_spec 调算法 S5 刷新入口（start_at="S5"），同步返回终态同构体，
  不落新消息、不改写报表快照（FR-14）；
- continue-session 新建会话写 inherited_spec，继承口径经 conversation_summary 到达算法（FR-15）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from ..errors import (
    AppError,
    name_conflict,
    not_found,
    report_not_saveable,
    validation_error,
)
from . import mappers

OWNER_ID = "default"  # 单用户（Business 约束）


class ReportService:
    def __init__(
        self,
        *,
        config: Any,
        chain_runner: Callable[..., Any],
        deps: Any,
        report_repo: Any,
        message_repo: Any,
        session_repo: Any,
    ) -> None:
        self._config = config
        self._chain_runner = chain_runner
        self._deps = deps
        self._report_repo = report_repo
        self._message_repo = message_repo
        self._session_repo = session_repo

    # ---------- 保存（FR-12） ----------
    async def save(self, *, turn_id: str, title: str, overwrite: bool = False) -> tuple[dict, bool]:
        title = (title or "").strip()
        if not title:
            raise validation_error("报表名称不能为空")
        msg = await asyncio.to_thread(self._message_repo.find_answer_by_turn, turn_id)
        if msg is None or msg.get("type") != "answer":
            raise report_not_saveable()
        payload = msg.get("payload") or {}
        rows = ((payload.get("table") or {}).get("rows")) or []
        if not rows:
            raise report_not_saveable("空结果不可保存为报表")
        internal = msg.get("internal") or {}
        queried_at = payload.get("queried_at")
        if isinstance(queried_at, str):
            # payload 时间是 utc_now_iso() 的 "Z" 结尾 ISO 串；列类型 DateTime(timezone=True)，
            # 必须转 aware datetime 再落库（插入后立即序列化 ORM 对象，拿到的还是未转换的原始值）
            queried_at = datetime.fromisoformat(queried_at)
        fields = {
            "title": title,
            "session_id": msg.get("session_id"),
            "source_turn_id": turn_id,
            "question": payload.get("question") or "",
            "caliber": payload.get("caliber"),
            "query_spec": internal.get("query_spec"),
            "sql": internal.get("sql"),
            "snapshot": {
                "insight": payload.get("insight"),
                "chart": payload.get("chart"),
                "table": payload.get("table"),
                "comparison": payload.get("comparison"),
            },
            "data_time_range": payload.get("data_time_range"),
            "queried_at": queried_at,
        }
        existing = await asyncio.to_thread(self._report_repo.find_by_title, OWNER_ID, title)
        if existing is not None and not overwrite:
            raise name_conflict({"id": existing["id"], "title": existing["title"]})
        if existing is not None:
            rep = await asyncio.to_thread(self._report_repo.overwrite, existing["id"], fields)
            return rep, False
        rep = await asyncio.to_thread(self._report_repo.insert, OWNER_ID, fields)
        return rep, True

    # ---------- 列表/详情（FR-13，只读快照） ----------
    async def list(self, *, q: Optional[str] = None, offset: int = 0, limit: int = 50) -> list[dict]:
        items = await asyncio.to_thread(
            self._report_repo.list, OWNER_ID, q=(q or None) or None, offset=offset, limit=limit
        )
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "caliber_summary": (r.get("caliber") or {}).get("summary") or "",
                "data_time_range": r.get("data_time_range"),
                "queried_at": r.get("queried_at"),
                "created_at": r.get("created_at"),
            }
            for r in items
        ]

    async def get(self, report_id: str) -> dict:
        rep = await asyncio.to_thread(self._report_repo.get, report_id)
        if rep is None:
            raise not_found("报表不存在")
        return {
            "id": rep["id"],
            "title": rep["title"],
            "question": rep["question"],
            "caliber": rep.get("caliber"),
            "snapshot": rep.get("snapshot"),
            "data_time_range": rep.get("data_time_range"),
            "queried_at": rep.get("queried_at"),
            "created_at": rep.get("created_at"),
            "updated_at": rep.get("updated_at"),
        }

    # ---------- 改名/删除（FR-13） ----------
    async def rename(self, report_id: str, title: str) -> dict:
        title = (title or "").strip()
        if not title:
            raise validation_error("报表名称不能为空")
        rep = await asyncio.to_thread(self._report_repo.get, report_id)
        if rep is None:
            raise not_found("报表不存在")
        other = await asyncio.to_thread(self._report_repo.find_by_title, OWNER_ID, title)
        if other is not None and other["id"] != report_id:
            raise name_conflict({"id": other["id"], "title": other["title"]})
        updated = await asyncio.to_thread(self._report_repo.rename, report_id, title)
        return {"id": updated["id"], "title": updated["title"]}

    async def delete(self, report_id: str) -> bool:
        return await asyncio.to_thread(self._report_repo.delete, report_id)

    # ---------- 刷新（FR-14 / AC-11）：S5 刷新入口，无副作用 ----------
    async def refresh(self, report_id: str) -> dict:
        rep = await asyncio.to_thread(self._report_repo.get, report_id)
        if rep is None:
            raise not_found("报表不存在")
        qspec = rep.get("query_spec")
        if not qspec:
            raise report_not_saveable("该报表缺少可重新取数的查询口径")
        result = await self._chain_runner(
            query_spec=qspec,
            start_at="S5",  # 从 gen_sql 起跑，不重走 S1~S4、不重新澄清（接缝节第 5 点）
            deps=self._deps,
            thread_id=None,
            checkpointer=None,
            conversation_summary="",
        )
        return self._refresh_response(result, rep)

    def _refresh_response(self, result: Any, rep: dict) -> dict:
        action = mappers.action_name(result)
        if action == "answer":
            answer = result.answer
            return {
                "action": "answer",
                "question": rep.get("question") or "",
                "table": answer.table.model_dump(mode="json"),
                "chart": answer.chart.model_dump(mode="json") if answer.chart is not None else None,
                "insight": answer.insight,
                "caliber": answer.caliber.model_dump(mode="json"),
                "comparison": answer.comparison.model_dump(mode="json") if answer.comparison is not None else None,
                "data_time_range": mappers.derive_data_time_range(result),
                "queried_at": mappers.utc_now_iso(),  # 本次刷新时间，仅响应（FR-14）
                "saveable": bool(answer.table.rows),
            }
        if action in ("query_gen_failed", "query_failed", "not_answerable"):
            rej = result.rejection.model_dump(mode="json")
            return {"action": action, **rej}
        if action == "error":
            err = result.error.model_dump(mode="json")
            return {"action": "error", **err}
        raise ValueError(f"刷新入口不支持终态 action：{action}")

    # ---------- 继承会话（FR-15 / AC-12） ----------
    async def continue_session(self, report_id: str) -> dict:
        rep = await asyncio.to_thread(self._report_repo.get, report_id)
        if rep is None:
            raise not_found("报表不存在")
        session = await asyncio.to_thread(
            self._session_repo.create,
            title=rep.get("question") or rep["title"],
            inherited_spec=rep.get("query_spec"),  # inherited_spec = 报表 query_spec
        )
        return {"session_id": session["id"]}
