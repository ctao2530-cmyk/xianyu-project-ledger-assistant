from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import (
    Conversation,
    Draft,
    Message,
    SellerReplySample,
)
from backend.app.services.actions import HumanActions
from backend.app.services.style_learning import StyleLearningService


class RecordingAdapter:
    connected = True

    async def send_text(self, conversation_id, receiver_id, text, client_message_id):
        return None


def build_message(database: Database, *, external_id: str, status: str = "drafted") -> int:
    with database.session() as session:
        conversation = Conversation(
            external_id=f"conversation-{external_id}",
            customer_id="buyer-1",
            customer_name="客户",
            unread_count=1,
        )
        message = Message(
            external_id=external_id,
            conversation=conversation,
            sender_id="buyer-1",
            sender_name="客户",
            direction="inbound",
            message_type="text",
            content="这个网页多少钱？",
            status=status,
            received_at=datetime.now(timezone.utc),
        )
        session.add(message)
        session.commit()
        return message.id


@pytest.mark.asyncio
async def test_human_sent_reply_becomes_masked_local_style_context(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'style.db'}")
    database.create_all()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'style.db'}",
        style_context_examples=8,
        style_context_max_chars=1200,
    )
    service = StyleLearningService(database, settings)
    service.bootstrap()
    message_id = build_message(database, external_id="incoming-human")
    actions = HumanActions(database, RecordingAdapter(), service)  # type: ignore[arg-type]

    await actions.confirm_send(
        message_id,
        "可以，价格 500 元，明天下午交；微信 abc12345，资料发我看看再确认。",
    )

    with database.session() as session:
        conversation_id = session.get(Message, message_id).conversation_id  # type: ignore[union-attr]
    context = service.build_context(conversation_id)
    assert context.enabled is True
    assert context.sample_count == 1
    assert len(context.examples) == 1
    assert "500" not in context.examples[0]
    assert "abc12345" not in context.examples[0]
    assert "<金额>" in context.examples[0]
    assert "<联系方式>" in context.examples[0]
    assert context.traits


@pytest.mark.asyncio
async def test_automatic_reply_is_never_learned_as_seller_style(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'automatic-style.db'}")
    database.create_all()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'automatic-style.db'}",
    )
    service = StyleLearningService(database, settings)
    service.bootstrap()
    message_id = build_message(database, external_id="incoming-auto")
    actions = HumanActions(database, RecordingAdapter(), service)  # type: ignore[arg-type]

    await actions.auto_send(message_id, "请把需求和参考资料发来，我看完再回复你。")

    snapshot = service.snapshot()
    assert snapshot.sample_count == 0
    with database.session() as session:
        sample = session.scalar(select(SellerReplySample))
        assert sample is not None
        assert sample.source == "automatic"
        assert sample.included is False


def test_drafts_are_not_style_samples_and_profile_can_pause_and_reset(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'style-control.db'}")
    database.create_all()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'style-control.db'}",
    )
    service = StyleLearningService(database, settings)
    service.bootstrap()
    message_id = build_message(database, external_id="incoming-draft")
    with database.session() as session:
        session.add(
            Draft(
                message_id=message_id,
                style="简洁直接",
                content="这是未采用的 AI 草稿，不能成为卖家风格。",
            )
        )
        session.commit()

    assert service.snapshot().sample_count == 0
    assert service.set_enabled(False).enabled is False

    with database.session() as session:
        conversation = session.get(Message, message_id).conversation  # type: ignore[union-attr]
        outbound = Message(
            external_id="synced-outbound-disabled",
            conversation=conversation,
            sender_id="self",
            sender_name="我",
            direction="outbound",
            message_type="text",
            content="暂停期间发送的内容不应被采集。",
            status="sent",
            received_at=datetime.now(timezone.utc),
        )
        session.add(outbound)
        session.commit()
    assert service.capture_synced_outbound() == 0
    assert service.set_enabled(True).enabled is True
    assert service.snapshot().sample_count == 0
    assert service.reset().sample_count == 0
    assert service.capture_synced_outbound() == 0
    with database.session() as session:
        count = session.scalar(select(func.count()).select_from(SellerReplySample))
        assert count == 0
