from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.database import Database
from backend.app.models import Conversation, Message
from backend.app.services.actions import ActionConflictError, HumanActions


class RecordingAdapter:
    connected = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, str]] = []

    async def send_text(self, conversation_id, receiver_id, text, client_message_id):
        self.sent.append((conversation_id, receiver_id, text, client_message_id))


@pytest.mark.asyncio
async def test_human_send_cannot_repeat(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'actions.db'}")
    database.create_all()
    with database.session() as session:
        conversation = Conversation(
            external_id="cid-1",
            customer_id="buyer-1",
            customer_name="客户",
            unread_count=1,
        )
        session.add(conversation)
        session.flush()
        message = Message(
            external_id="incoming-1",
            conversation=conversation,
            sender_id="buyer-1",
            sender_name="客户",
            direction="inbound",
            content="你好",
            status="drafted",
            received_at=datetime.now(timezone.utc),
        )
        session.add(message)
        session.commit()
        message_id = message.id

    adapter = RecordingAdapter()
    actions = HumanActions(database, adapter)  # type: ignore[arg-type]
    await actions.confirm_send(message_id, "您好，请发一下需求和截止时间。")

    with pytest.raises(ActionConflictError):
        await actions.confirm_send(message_id, "重复发送")
    assert len(adapter.sent) == 1
