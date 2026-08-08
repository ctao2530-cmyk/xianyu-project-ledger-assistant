from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.adapters import IncomingMessage, ItemInfo
from backend.app.database import Database
from backend.app.models import Conversation, Message
from backend.app.services.repository import hydrate_conversation_context, ingest_message


def make_event() -> IncomingMessage:
    return IncomingMessage(
        external_id="message-1",
        conversation_id="conversation-1",
        sender_id="buyer-1",
        sender_name="客户甲",
        content="预算 500 元，明天能交付吗？",
        message_type="text",
        received_at=datetime.now(timezone.utc),
        item_id="item-1",
    )


def test_ingest_is_idempotent_and_stores_risks(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_all()
    item = ItemInfo("item-1", "企业官网制作", "¥999", "响应式网站", {})

    with database.session() as session:
        first = ingest_message(session, make_event(), [], item)
    with database.session() as session:
        second = ingest_message(session, make_event(), [], item)

    assert first.is_new is True
    assert second.is_new is False
    with database.session() as session:
        assert len(list(session.scalars(select(Message)))) == 1
        conversation = session.scalar(select(Conversation))
        assert conversation is not None
        assert conversation.unread_count == 1
        message = session.scalar(select(Message))
        assert "报价需确认" in message.risk_flags_json
        assert "交付时间需确认" in message.risk_flags_json


def test_context_hydration_updates_item_and_history_without_incrementing_unread(
    tmp_path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'hydrate.db'}")
    database.create_all()
    current = make_event()
    previous = IncomingMessage(
        external_id="message-history",
        conversation_id=current.conversation_id,
        sender_id="seller-1",
        sender_name="卖家",
        content="可以，请发一下参考网站",
        message_type="text",
        received_at=datetime.now(timezone.utc),
        direction="outbound",
    )
    item = ItemInfo("item-1", "企业官网制作", "¥999", "响应式网站", {})

    with database.session() as session:
        ingest_message(session, current, [], None)
    with database.session() as session:
        assert hydrate_conversation_context(session, current, [previous], item)

    with database.session() as session:
        conversation = session.scalar(select(Conversation))
        assert conversation is not None
        assert conversation.unread_count == 1
        assert conversation.item is not None
        assert conversation.item.title == "企业官网制作"
        messages = list(session.scalars(select(Message).order_by(Message.id)))
        assert [message.external_id for message in messages] == [
            "message-1",
            "message-history",
        ]
