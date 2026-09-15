from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from backend.app.adapters import IncomingMessage
from backend.app.database import Database
from backend.app.models import Message
from backend.app.services.processor import MessageProcessor


class ReconcileAdapter:
    connected = True

    def __init__(self, events: list[IncomingMessage]) -> None:
        self.events = events

    async def fetch_recent_conversation_messages(
        self, _limit: int
    ) -> list[IncomingMessage]:
        return self.events

    async def fetch_recent_messages(
        self, _conversation_id: str, _limit: int
    ) -> list[IncomingMessage]:
        return []

    async def fetch_item(self, _item_id: str):
        return None


class RecordingQueue:
    def __init__(self) -> None:
        self.message_ids: list[int] = []
        self.queued = asyncio.Event()

    async def enqueue(self, message_id: int, *, automatic: bool):
        assert automatic is True
        self.message_ids.append(message_id)
        self.queued.set()
        return None


class RecordingNotifier:
    def __init__(self) -> None:
        self.count = 0

    async def notify(self, _title: str, _message: str, _subtitle: str = "") -> None:
        self.count += 1


class RecordingSalesScheduler:
    def __init__(self) -> None:
        self.message_ids: list[int] = []

    def schedule(self, message_id: int) -> None:
        self.message_ids.append(message_id)


def event(external_id: str, received_at: datetime) -> IncomingMessage:
    return IncomingMessage(
        external_id=external_id,
        conversation_id=f"conversation-{external_id}",
        sender_id=f"buyer-{external_id}",
        sender_name="测试客户",
        content="测试消息",
        message_type="text",
        received_at=received_at,
    )


def conversation_event(
    external_id: str, conversation_id: str, content: str, received_at: datetime
) -> IncomingMessage:
    return IncomingMessage(
        external_id=external_id,
        conversation_id=conversation_id,
        sender_id=f"buyer-{conversation_id}",
        sender_name="测试客户",
        content=content,
        message_type="text",
        received_at=received_at,
    )


@pytest.mark.asyncio
async def test_reconcile_only_recovers_recent_inbound_messages_without_legacy_ai(
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    adapter = ReconcileAdapter(
        [
            event("recent", now - timedelta(minutes=5)),
            event("old", now - timedelta(hours=3)),
        ]
    )
    database = Database(f"sqlite:///{tmp_path / 'reconcile.db'}")
    database.create_all()
    queue = RecordingQueue()
    notifier = RecordingNotifier()
    processor = MessageProcessor(
        database,
        adapter,  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        history_limit=20,
    )

    recovered = await processor.reconcile_recent_conversations(50, 60)

    assert recovered == 1
    assert queue.message_ids == []
    assert notifier.count == 1
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 1
        assert session.scalar(
            select(Message.external_id).where(Message.external_id == "recent")
        ) == "recent"


@pytest.mark.asyncio
async def test_slow_remote_context_does_not_block_message_ingestion(tmp_path) -> None:
    class SlowAdapter(ReconcileAdapter):
        async def fetch_recent_messages(
            self, _conversation_id: str, _limit: int
        ) -> list[IncomingMessage]:
            await asyncio.sleep(10)
            return []

    now = datetime.now(timezone.utc)
    adapter = SlowAdapter([])
    database = Database(f"sqlite:///{tmp_path / 'fast-ingest.db'}")
    database.create_all()
    queue = RecordingQueue()
    notifier = RecordingNotifier()
    processor = MessageProcessor(
        database,
        adapter,  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        history_limit=20,
        context_hydration_timeout_seconds=0.01,
    )

    await asyncio.wait_for(processor.process(event("fast", now)), timeout=0.2)

    assert queue.message_ids == []
    assert notifier.count == 1
    await processor.stop()


@pytest.mark.asyncio
async def test_burst_messages_stay_persisted_without_legacy_draft_generation(
    tmp_path,
) -> None:
    now = datetime.now(timezone.utc)
    database = Database(f"sqlite:///{tmp_path / 'coalesce.db'}")
    database.create_all()
    queue = RecordingQueue()
    notifier = RecordingNotifier()
    processor = MessageProcessor(
        database,
        ReconcileAdapter([]),  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        history_limit=20,
    )

    await processor.process(conversation_event("burst-1", "same", "你好", now))
    await processor.process(
        conversation_event("burst-2", "same", "网页制作多少钱", now)
    )
    assert queue.message_ids == []
    with database.session() as session:
        rows = list(session.scalars(select(Message).order_by(Message.id.asc())))
        assert len(rows) == 2
        assert [row.status for row in rows] == ["new", "new"]
    await processor.stop()


@pytest.mark.asyncio
async def test_different_conversations_do_not_enqueue_legacy_drafts(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    database = Database(f"sqlite:///{tmp_path / 'coalesce-independent.db'}")
    database.create_all()
    queue = RecordingQueue()
    notifier = RecordingNotifier()
    processor = MessageProcessor(
        database,
        ReconcileAdapter([]),  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
        history_limit=20,
    )

    await processor.process(conversation_event("a-1", "a", "消息 A", now))
    await processor.process(conversation_event("b-1", "b", "消息 B", now))
    await asyncio.sleep(0.05)

    assert queue.message_ids == []
    await processor.stop()


@pytest.mark.asyncio
async def test_inbound_messages_do_not_schedule_retired_sales_analysis(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    database = Database(f"sqlite:///{tmp_path / 'sales-schedule.db'}")
    database.create_all()
    queue = RecordingQueue()
    sales = RecordingSalesScheduler()
    processor = MessageProcessor(
        database,
        ReconcileAdapter([]),  # type: ignore[arg-type]
        queue,  # type: ignore[arg-type]
        RecordingNotifier(),  # type: ignore[arg-type]
        history_limit=20,
    )

    await processor.process(conversation_event("sales-1", "sales", "先问一下", now))
    await processor.process(
        conversation_event("sales-2", "sales", "我想做订单系统", now)
    )
    await asyncio.sleep(0.06)

    assert queue.message_ids == []
    assert sales.message_ids == []
    await processor.stop()
