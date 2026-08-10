from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import Database
from ..models import (
    Conversation,
    CustomerChannelIdentity,
    CustomerMemory,
    SalesLead,
    utcnow,
)


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


class SalesMemoryStore:
    """Reads and writes only human-confirmed customer sales memory."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def resolve_customer_id(session: Session, conversation: Conversation) -> str | None:
        identity = session.scalar(
            select(CustomerChannelIdentity).where(
                CustomerChannelIdentity.channel == conversation.channel,
                CustomerChannelIdentity.external_customer_id == conversation.customer_id,
            )
        )
        if identity and identity.customer_id:
            return identity.customer_id
        lead = session.scalar(
            select(SalesLead).where(SalesLead.conversation_id == conversation.id)
        )
        return lead.customer_id if lead else None

    def read(self, conversation_id: int, *, limit: int = 5) -> dict[str, Any]:
        with self.database.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise LookupError("会话不存在")
            customer_id = self.resolve_customer_id(session, conversation)
            predicate = CustomerMemory.conversation_id == conversation_id
            if customer_id:
                predicate = or_(
                    CustomerMemory.conversation_id == conversation_id,
                    CustomerMemory.customer_id == customer_id,
                )
            rows = list(
                session.scalars(
                    select(CustomerMemory)
                    .where(predicate)
                    .order_by(CustomerMemory.updated_at.desc())
                    .limit(max(1, min(limit, 20)))
                )
            )
            memories = [self.to_dict(row) for row in rows]
            return {
                "customer_id": customer_id,
                "memories": memories,
                "memory_count": len(memories),
                "latest_version": max((row.version for row in rows), default=0),
            }

    @staticmethod
    def to_dict(row: CustomerMemory) -> dict[str, Any]:
        return {
            "id": row.id,
            "customer_id": row.customer_id,
            "conversation_id": row.conversation_id,
            "source_analysis_id": row.source_analysis_id,
            "customer_background": row.customer_background,
            "requirements": _load_json(row.requirements_json, []),
            "communication_summary": row.communication_summary,
            "latest_analysis": _load_json(row.latest_analysis_json, {}),
            "follow_up_status": row.follow_up_status,
            "version": row.version,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    def upsert_in_session(
        self,
        session: Session,
        *,
        conversation_id: int,
        customer_id: str,
        analysis_id: str,
        analysis: dict[str, Any],
    ) -> CustomerMemory:
        row = session.scalar(
            select(CustomerMemory).where(
                CustomerMemory.conversation_id == conversation_id
            )
        )
        if row is None:
            row = CustomerMemory(
                id=f"customer-memory-{uuid4()}",
                conversation_id=conversation_id,
                customer_id=customer_id,
                version=1,
            )
            session.add(row)
        else:
            row.version += 1
            row.customer_id = customer_id
        row.source_analysis_id = analysis_id
        row.customer_background = str(analysis.get("customer_profile") or "")
        row.requirements_json = json.dumps(
            analysis.get("need_signals") or [], ensure_ascii=False
        )
        row.communication_summary = (
            f"策略：{analysis.get('sales_strategy') or ''}\n"
            f"下一步：{analysis.get('next_action') or ''}"
        ).strip()
        row.latest_analysis_json = json.dumps(analysis, ensure_ascii=False)
        row.follow_up_status = str(analysis.get("stage") or "待跟进")
        row.updated_at = utcnow()
        session.flush()
        return row
