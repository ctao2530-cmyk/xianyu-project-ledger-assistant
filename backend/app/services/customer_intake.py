from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from ..database import Database
from ..ledger import LedgerService, RevisionConflict, canonical_json
from ..models import (
    BusinessCustomer,
    Conversation,
    CustomerChannelIdentity,
    LedgerMutationRequest,
    LedgerState,
    Message,
    utcnow,
)
from .customer_identity import linked_customer_ids
from .event_hub import EventHub


IMAGE_PLACEHOLDERS = {
    "[图片]",
    "图片",
    "[客户发送了图片]",
    "[客服发送了图片]",
    "[卖家发送了图片]",
    "[对方发送了图片]",
}


class CustomerIntakeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CustomerIntakeService:
    def __init__(
        self,
        database: Database,
        ledger: LedgerService,
        event_hub: EventHub,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.event_hub = event_hub

    @staticmethod
    def _source(channel: str) -> str:
        return channel if channel in {"xianyu", "wechat"} else "other"

    @staticmethod
    def _preview(value: str) -> str:
        text = " ".join(str(value or "").split())
        if text in IMAGE_PLACEHOLDERS:
            return ""
        return text[:120]

    @staticmethod
    def _revision_read_only(session) -> int:
        state = session.get(LedgerState, 1)
        return int(state.revision) if state is not None else 0

    def candidates(self) -> dict[str, Any]:
        """Return unbound conversations without mutating the ledger or database."""

        with self.database.session() as session:
            revision = self._revision_read_only(session)
            conversations = list(
                session.scalars(
                    select(Conversation).order_by(
                        Conversation.last_message_at.desc(),
                        Conversation.id.desc(),
                    )
                )
            )
            names = {
                str(value).strip().casefold()
                for value in session.scalars(select(BusinessCustomer.name)).all()
                if str(value).strip()
            }
            rows: list[dict[str, Any]] = []
            for conversation in conversations:
                if linked_customer_ids(session, conversation):
                    continue
                messages = list(
                    session.scalars(
                        select(Message)
                        .where(
                            Message.conversation_id == conversation.id,
                            Message.direction == "inbound",
                            Message.message_type == "text",
                            Message.content != "",
                        )
                        .order_by(Message.id.desc())
                        .limit(8)
                    )
                )
                preview = next(
                    (
                        cleaned
                        for message in messages
                        if (cleaned := self._preview(message.content))
                    ),
                    "",
                )
                customer_name = str(conversation.customer_name or "").strip()[:255] or "新客户"
                rows.append(
                    {
                        "conversation_id": conversation.id,
                        "channel": conversation.channel,
                        "customer_name": customer_name,
                        "customer_source": self._source(conversation.channel),
                        "last_message_at": conversation.last_message_at,
                        "last_text_preview": preview,
                        "same_name_exists": customer_name.casefold() in names,
                    }
                )
            return {"revision": revision, "candidates": rows}

    def create_customer(
        self,
        *,
        request_id: str,
        expected_revision: int,
        conversation_id: int | None,
        name: str,
        source: str,
        phone: str,
        level: str,
        current_need: str,
        price_type: str,
        price_amount: float | None,
        next_action: str,
        notes: str,
    ) -> dict[str, Any]:
        payload = {
            "operation": "customer_create",
            "conversation_id": conversation_id,
            "name": name,
            "source": source,
            "phone": phone,
            "level": level,
            "current_need": current_need,
            "price_type": price_type,
            "price_amount": price_amount,
            "next_action": next_action,
            "notes": notes,
        }
        payload_hash = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        idempotent = False
        with self.database.session() as session:
            prior = session.get(LedgerMutationRequest, request_id)
            if prior is not None:
                if prior.operation != "customer_create" or prior.payload_hash != payload_hash:
                    raise CustomerIntakeError(
                        "request_id_reused",
                        "该请求编号已用于其他客户操作，请刷新后重新确认",
                    )
                try:
                    recorded = json.loads(prior.result_json)
                except json.JSONDecodeError:
                    raise CustomerIntakeError(
                        "request_record_invalid",
                        "历史新增记录无法校验，请刷新后重试",
                    ) from None
                customer_id = str(recorded.get("customer_id") or "")
                if not customer_id or session.get(BusinessCustomer, customer_id) is None:
                    raise CustomerIntakeError(
                        "request_record_invalid",
                        "历史新增记录对应的客户已经不存在",
                    )
                if conversation_id is not None:
                    conversation = session.get(Conversation, conversation_id)
                    if conversation is None:
                        raise CustomerIntakeError("conversation_not_found", "客户会话不存在")
                    if linked_customer_ids(session, conversation) != {customer_id}:
                        raise CustomerIntakeError(
                            "conversation_relationship_changed",
                            "该会话的客户关系已经变化，请刷新后核对",
                        )
                revision, snapshot = self.ledger.get_in_session(session)
                result = {
                    "revision": revision,
                    "snapshot": snapshot,
                    "customer_id": customer_id,
                    "conversation_id": conversation_id,
                    "created": bool(recorded.get("created", True)),
                    "idempotent": True,
                }
                session.rollback()
                return result

            revision, snapshot = self.ledger.get_in_session(session)
            if revision != expected_revision:
                raise RevisionConflict(revision)

            conversation = None
            normalized_source = source
            last_contact_at = utcnow().isoformat()
            if conversation_id is not None:
                conversation = session.get(Conversation, conversation_id)
                if conversation is None:
                    raise CustomerIntakeError("conversation_not_found", "客户会话不存在")
                relationships = linked_customer_ids(session, conversation)
                if len(relationships) > 1:
                    raise CustomerIntakeError(
                        "conversation_relationship_conflict",
                        "该会话存在相互冲突的客户关系，请先核对客户资料",
                    )
                if relationships:
                    raise CustomerIntakeError(
                        "conversation_already_linked",
                        "该会话已经加入客户列表，不能重复新增",
                    )
                normalized_source = self._source(conversation.channel)
                last_contact_at = conversation.last_message_at.isoformat()

            customer_id = f"customer-{uuid4()}"
            snapshot["customers"].insert(
                0,
                {
                    "id": customer_id,
                    "name": name,
                    "source": normalized_source,
                    "phone": phone,
                    "followUpStatus": "new",
                    "lastContactAt": last_contact_at,
                    "level": level,
                    "tags": ["新客户"],
                    "currentNeed": current_need,
                    "priceType": price_type,
                    "priceAmount": price_amount,
                    "nextAction": next_action,
                    "notes": notes,
                },
            )
            new_revision, normalized = self.ledger.save_in_session(
                session,
                snapshot,
                expected_revision,
            )

            if conversation is not None:
                identity = session.scalar(
                    select(CustomerChannelIdentity).where(
                        CustomerChannelIdentity.channel == conversation.channel,
                        CustomerChannelIdentity.external_customer_id == conversation.customer_id,
                    )
                )
                if identity is None:
                    identity = CustomerChannelIdentity(
                        id=f"identity-{uuid4()}",
                        customer_id=customer_id,
                        channel=conversation.channel,
                        external_customer_id=conversation.customer_id,
                        conversation_id=conversation.id,
                        display_name=conversation.customer_name,
                    )
                    session.add(identity)
                elif identity.customer_id is not None:
                    raise CustomerIntakeError(
                        "conversation_already_linked",
                        "该渠道身份已经加入客户列表，不能重复新增",
                    )
                else:
                    identity.customer_id = customer_id
                    identity.conversation_id = conversation.id
                    identity.display_name = conversation.customer_name
                    identity.updated_at = utcnow()

            recorded = {
                "customer_id": customer_id,
                "created": True,
                "revision": new_revision,
            }
            session.add(
                LedgerMutationRequest(
                    request_id=request_id,
                    operation="customer_create",
                    payload_hash=payload_hash,
                    result_json=canonical_json(recorded),
                )
            )
            session.commit()
            result = {
                "revision": new_revision,
                "snapshot": normalized,
                "customer_id": customer_id,
                "conversation_id": conversation_id,
                "created": True,
                "idempotent": idempotent,
            }

        self.event_hub.publish_nowait(
            {"type": "ledger_updated", "revision": result["revision"], "source": "customer_create"}
        )
        self.event_hub.publish_nowait(
            {
                "type": "customer_created",
                "customer_id": result["customer_id"],
                "conversation_id": result["conversation_id"],
            }
        )
        return result
