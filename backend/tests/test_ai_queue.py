from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.app.ai import AIInput, AIProvider, AIResult, ProviderHealth
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import AIGenerationTask, Conversation, Message
from backend.app.services.ai_queue import AIJobQueue
from backend.app.services.event_hub import EventHub
from backend.app.services.reply_strategy import ReplyStrategyService
from backend.app.services.style_learning import StyleLearningService


class RecordingProvider(AIProvider):
    name = "test_provider"

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.payloads: list[AIInput] = []
        self.model_selections = []
        self.active = 0
        self.max_active = 0
        self.active_groups: dict[str, int] = {}
        self.same_conversation_overlap = False

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        self.health = ProviderHealth(status="connected")
        return self.health

    async def generate(
        self, payload: AIInput, *, task_key: str, model_selection=None
    ) -> AIResult:
        marker = payload.customer_message
        self.payloads.append(payload)
        self.model_selections.append(model_selection)
        group = marker[0]
        self.calls.append(marker)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.active_groups[group] = self.active_groups.get(group, 0) + 1
        if self.active_groups[group] > 1:
            self.same_conversation_overlap = True
        await asyncio.sleep(0.06)
        self.active_groups[group] -= 1
        self.active -= 1
        return AIResult(
            direct="可以，请把具体需求、截止时间和参考资料发来，我先确认工作范围。",
            friendly="您好，可以先说下想实现的功能，并附上截止时间和参考案例，我帮您看看。",
            conversion="您把需求文档、期望时间和参考资料发我，确认范围后我们再继续沟通。",
            risk_level="low",
            risk_reasons=[],
            needs_human_confirmation=True,
        )


def add_message(database: Database, conversation_key: str, content: str) -> int:
    with database.session() as session:
        conversation = session.scalar(
            select(Conversation).where(Conversation.external_id == conversation_key)
        )
        if not conversation:
            conversation = Conversation(
                external_id=conversation_key,
                customer_id=f"buyer-{conversation_key}",
                customer_name=conversation_key,
            )
            session.add(conversation)
            session.flush()
        message = Message(
            external_id=f"message-{conversation_key}-{content}",
            conversation=conversation,
            sender_id=conversation.customer_id,
            sender_name=conversation.customer_name,
            direction="inbound",
            content=content,
            status="new",
            received_at=datetime.now(timezone.utc),
        )
        session.add(message)
        session.commit()
        return message.id


async def wait_until_complete(database: Database, expected: int) -> None:
    for _ in range(100):
        with database.session() as session:
            completed = len(
                list(
                    session.scalars(
                        select(AIGenerationTask).where(AIGenerationTask.status == "completed")
                    )
                )
            )
        if completed == expected:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("AI tasks did not complete")


@pytest.mark.asyncio
async def test_queue_deduplicates_and_limits_concurrency(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'queue.db'}")
    database.create_all()
    a1 = add_message(database, "A", "A1 客户需求")
    a2 = add_message(database, "A", "A2 客户补充")
    b1 = add_message(database, "B", "B1 另一客户")
    provider = RecordingProvider()
    settings = Settings(_env_file=None, codex_max_concurrency=2)
    queue = AIJobQueue(database, provider, settings)
    await queue.start()
    try:
        first = await queue.enqueue(a1, automatic=True)
        duplicate = await queue.enqueue(a1, automatic=True)
        await queue.enqueue(a2, automatic=True)
        await queue.enqueue(b1, automatic=True)
        await wait_until_complete(database, 3)
    finally:
        await queue.stop()

    assert first is not None and duplicate is not None
    assert first.id == duplicate.id
    assert provider.calls.count("A1 客户需求") == 1
    assert provider.calls.index("A1 客户需求") < provider.calls.index("A2 客户补充")
    assert provider.max_active == 2
    assert provider.same_conversation_overlap is False


@pytest.mark.asyncio
async def test_automatic_live_reply_has_priority_over_manual_regeneration(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'priority.db'}")
    database.create_all()
    manual_message = add_message(database, "manual", "M 手动重新生成")
    live_message = add_message(database, "live", "L 实时客户消息")
    provider = RecordingProvider()
    queue = AIJobQueue(
        database,
        provider,
        Settings(_env_file=None, codex_max_concurrency=1),
    )

    await queue.enqueue(manual_message, automatic=False)
    await queue.enqueue(live_message, automatic=True)
    await queue.start()
    try:
        await wait_until_complete(database, 2)
    finally:
        await queue.stop()

    assert provider.calls == ["L 实时客户消息", "M 手动重新生成"]


@pytest.mark.asyncio
async def test_running_task_is_recovered_after_restart(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'recovery.db'}")
    database.create_all()
    message_id = add_message(database, "R", "R1 恢复任务")
    provider = RecordingProvider()
    settings = Settings(_env_file=None, codex_max_concurrency=1)
    queue = AIJobQueue(database, provider, settings)

    task = await queue.enqueue(message_id, automatic=True)
    assert task is not None
    with database.session() as session:
        stored = session.get(AIGenerationTask, task.id)
        assert stored is not None
        stored.status = "running"
        session.commit()

    await queue.start()
    try:
        await wait_until_complete(database, 1)
    finally:
        await queue.stop()

    assert provider.calls == ["R1 恢复任务"]


@pytest.mark.asyncio
async def test_successful_unattended_callback_publishes_sent_event_without_draft_popup(
    tmp_path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'auto-event.db'}")
    database.create_all()
    message_id = add_message(database, "E", "E1 普通咨询")
    provider = RecordingProvider()
    event_hub = EventHub()
    subscription = event_hub.subscribe()
    completed: list[int] = []

    async def auto_send(completed_message_id: int) -> str:
        completed.append(completed_message_id)
        return "sent"

    queue = AIJobQueue(
        database,
        provider,
        Settings(_env_file=None, codex_max_concurrency=1),
        event_hub,
        on_completed=auto_send,
    )
    await queue.start()
    try:
        await queue.enqueue(message_id, automatic=True)
        event = await asyncio.wait_for(subscription.queue.get(), timeout=2)
    finally:
        await queue.stop()

    assert completed == [message_id]
    assert event["type"] == "auto_reply_sent"
    assert event["auto_reply_status"] == "sent"
    assert event["message_id"] == message_id
    assert event_hub.subscribe().replay == []


@pytest.mark.asyncio
async def test_queue_passes_local_seller_style_to_provider_and_reply_event(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'style-queue.db'}")
    database.create_all()
    with database.session() as session:
        conversation = Conversation(
            external_id="style-conversation",
            customer_id="style-buyer",
            customer_name="风格客户",
        )
        session.add(
            Message(
                external_id="synced-human-reply",
                conversation=conversation,
                sender_id="self",
                sender_name="我",
                direction="outbound",
                message_type="text",
                content="可以，先把需求和参考资料发我，我看完再回复你。",
                status="sent",
                received_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    message_id = add_message(database, "style-conversation", "S1 这个页面怎么做")
    settings = Settings(
        _env_file=None,
        codex_max_concurrency=1,
        style_context_examples=4,
    )
    style_learning = StyleLearningService(database, settings)
    style_learning.bootstrap()
    provider = RecordingProvider()
    event_hub = EventHub()
    subscription = event_hub.subscribe()
    queue = AIJobQueue(
        database,
        provider,
        settings,
        event_hub=event_hub,
        style_learning=style_learning,
    )

    await queue.start()
    try:
        await queue.enqueue(message_id, automatic=True)
        event = await asyncio.wait_for(subscription.queue.get(), timeout=2)
    finally:
        await queue.stop()

    payload = provider.payloads[0]
    assert payload.seller_style is not None
    assert payload.seller_style.sample_count == 1
    assert payload.seller_style.examples == [
        "可以，先把需求和参考资料发我，我看完再回复你。"
    ]
    assert event["style_learning_enabled"] is True
    assert event["style_sample_count"] == 1
    assert event["style_traits"]


@pytest.mark.asyncio
async def test_local_risk_escalates_reply_to_quality_model(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'risk-route.db'}")
    database.create_all()
    message_id = add_message(database, "risk", "R1 明天交付要多少钱")
    with database.session() as session:
        message = session.get(Message, message_id)
        assert message is not None
        message.risk_flags_json = '["报价需确认", "交付时间需确认"]'
        session.commit()

    settings = Settings(
        _env_file=None,
        codex_max_concurrency=1,
        reply_speed_mode="fast",
        reply_fast_model="gpt-5.4-mini",
        reply_quality_model="gpt-5.6-sol",
    )
    strategy = ReplyStrategyService(database, settings, "codex_cli")
    provider = RecordingProvider()
    event_hub = EventHub()
    subscription = event_hub.subscribe()
    queue = AIJobQueue(
        database,
        provider,
        settings,
        event_hub=event_hub,
        reply_strategy=strategy,
    )

    await queue.start()
    try:
        await queue.enqueue(message_id, automatic=True)
        event = await asyncio.wait_for(subscription.queue.get(), timeout=2)
    finally:
        await queue.stop()

    assert provider.model_selections[0].model == "gpt-5.6-sol"
    assert provider.model_selections[0].reasoning_effort == "high"
    assert event["reply_mode"] == "quality"
    assert event["risk_escalated_model"] is True
