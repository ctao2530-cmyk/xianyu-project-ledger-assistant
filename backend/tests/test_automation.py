from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.api import router
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import (
    AIGenerationTask,
    AutomationState,
    Conversation,
    Draft,
    Message,
    OperationLog,
    utcnow,
)
from backend.app.rate_limit import SlidingWindowRateLimiter
from backend.app.services.actions import HumanActions
from backend.app.services.automation import AutoReplyService
from backend.app.services.status import RuntimeStatus


SAFE_REPLY = "您好，可以把具体需求和参考资料发来，我先了解内容，再为您说明合适的处理方案。"


class RecordingAdapter:
    connected = True

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, str, str]] = []

    async def send_text(self, conversation_id, receiver_id, text, client_message_id):
        if self.fail:
            raise RuntimeError("test failure")
        self.sent.append((conversation_id, receiver_id, text, client_message_id))


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str | None]] = []

    async def notify(self, title: str, message: str, subtitle: str | None = None) -> None:
        self.messages.append((title, message, subtitle))


def add_completed_message(
    database: Database,
    *,
    conversation_key: str,
    external_id: str,
    content: str = "你好，想了解一下你提供的服务",
    risk_level: str = "low",
    received_at: datetime | None = None,
) -> int:
    with database.session() as session:
        conversation = session.scalar(
            select(Conversation).where(Conversation.external_id == conversation_key)
        )
        if conversation is None:
            conversation = Conversation(
                external_id=conversation_key,
                customer_id=f"buyer-{conversation_key}",
                customer_name=f"客户-{conversation_key}",
            )
            session.add(conversation)
            session.flush()
        message = Message(
            external_id=external_id,
            conversation=conversation,
            sender_id=conversation.customer_id,
            sender_name=conversation.customer_name,
            direction="inbound",
            message_type="text",
            content=content,
            status="drafted",
            received_at=received_at or datetime.now(timezone.utc),
        )
        session.add(message)
        session.flush()
        session.add(
            Draft(
                message_id=message.id,
                style="简洁直接",
                content=SAFE_REPLY,
                risk_flags_json="[]",
            )
        )
        session.add(
            AIGenerationTask(
                message_id=message.id,
                conversation_id=conversation.id,
                trigger_key=f"task-{external_id}",
                provider="test",
                status="completed",
                risk_level=risk_level,
                risk_reasons_json="[]" if risk_level == "low" else '["报价需确认"]',
                needs_human_confirmation=True,
            )
        )
        session.commit()
        return message.id


def build_service(
    database: Database,
    adapter: RecordingAdapter,
    *,
    max_failures: int = 3,
    send_limiter: SlidingWindowRateLimiter | None = None,
) -> tuple[AutoReplyService, RecordingNotifier]:
    notifier = RecordingNotifier()
    settings = Settings(
        _env_file=None,
        auto_reply_debounce_seconds=0,
        auto_reply_conversation_cooldown_seconds=0,
        auto_reply_max_failures=max_failures,
        auto_reply_daily_limit=20,
    )
    actions = HumanActions(database, adapter)  # type: ignore[arg-type]
    service = AutoReplyService(
        database,
        actions,
        notifier,  # type: ignore[arg-type]
        settings,
        RuntimeStatus(listener="connected"),
        send_limiter=send_limiter,
    )
    return service, notifier


@pytest.mark.asyncio
async def test_unattended_switch_defaults_off_and_low_risk_send_is_idempotent(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'automation.db'}")
    database.create_all()
    message_id = add_completed_message(
        database, conversation_key="safe", external_id="safe-1"
    )
    adapter = RecordingAdapter()
    service, notifier = build_service(database, adapter)

    assert service.snapshot().enabled is False
    assert await service.handle_completed(message_id) == "disabled"
    await service.enable(60)
    assert await service.handle_completed(message_id) == "sent"
    assert await service.handle_completed(message_id) == "stale"
    assert len(adapter.sent) == 1
    assert any(message[0] == "鱼答已自动回复" for message in notifier.messages)

    with database.session() as session:
        message = session.get(Message, message_id)
        assert message is not None and message.status == "sent"
        assert session.scalar(
            select(OperationLog.id).where(
                OperationLog.message_id == message_id,
                OperationLog.action == "auto_reply_sent",
            )
        ) is not None


@pytest.mark.asyncio
async def test_high_risk_and_stale_messages_never_auto_send(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'blocked.db'}")
    database.create_all()
    risky = add_completed_message(
        database,
        conversation_key="risk",
        external_id="risk-1",
        content="这个多少钱，可以便宜吗",
        risk_level="high",
    )
    earlier = add_completed_message(
        database,
        conversation_key="stale",
        external_id="stale-1",
        received_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    add_completed_message(
        database,
        conversation_key="stale",
        external_id="stale-2",
        received_at=datetime.now(timezone.utc),
    )
    adapter = RecordingAdapter()
    service, _notifier = build_service(database, adapter)
    await service.enable(60)

    assert await service.handle_completed(risky) == "blocked_risk"
    assert await service.handle_completed(earlier) == "stale"
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_repeated_send_failures_trip_fail_closed_switch(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'failures.db'}")
    database.create_all()
    first = add_completed_message(
        database, conversation_key="failure-a", external_id="failure-1"
    )
    second = add_completed_message(
        database, conversation_key="failure-b", external_id="failure-2"
    )
    adapter = RecordingAdapter(fail=True)
    service, _notifier = build_service(database, adapter, max_failures=2)
    await service.enable(60)

    assert await service.handle_completed(first) == "failed"
    assert service.snapshot().enabled is True
    assert await service.handle_completed(second) == "failed"
    snapshot = service.snapshot()
    assert snapshot.enabled is False
    assert snapshot.disabled_reason == "连续发送失败，已自动熔断"


@pytest.mark.asyncio
async def test_unattended_replies_share_global_send_rate_limit(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'rate-limit.db'}")
    database.create_all()
    first = add_completed_message(
        database, conversation_key="rate-a", external_id="rate-1"
    )
    second = add_completed_message(
        database, conversation_key="rate-b", external_id="rate-2"
    )
    adapter = RecordingAdapter()
    service, _notifier = build_service(
        database,
        adapter,
        send_limiter=SlidingWindowRateLimiter(limit=1),
    )
    await service.enable(60)

    assert await service.handle_completed(first) == "sent"
    assert await service.handle_completed(second) == "rate_limited"
    assert len(adapter.sent) == 1


def test_expired_authorization_is_disabled_without_sending(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'expired.db'}")
    database.create_all()
    adapter = RecordingAdapter()
    service, _notifier = build_service(database, adapter)
    with database.session() as session:
        session.add(
            AutomationState(
                id=1,
                enabled=True,
                enabled_at=utcnow() - timedelta(hours=2),
                enabled_until=utcnow() - timedelta(minutes=1),
            )
        )
        session.commit()

    snapshot = service.snapshot()
    assert snapshot.enabled is False
    assert snapshot.disabled_reason == "授权时间已结束"


def test_automation_api_requires_local_confirmation_and_can_disable(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'api.db'}")
    database.create_all()
    service, _notifier = build_service(database, RecordingAdapter())
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        automation=service,
        status=RuntimeStatus(listener="connected"),
        ai=SimpleNamespace(status="connected"),
    )
    app.include_router(router)
    client = TestClient(app)

    missing_confirmation = client.post(
        "/api/automation",
        headers={"X-Yuda-Desktop": "1"},
        json={"enabled": True, "duration_minutes": 60},
    )
    assert missing_confirmation.status_code == 400

    enabled = client.post(
        "/api/automation",
        headers={"X-Yuda-Desktop": "1"},
        json={
            "enabled": True,
            "duration_minutes": 60,
            "confirmation": "我确认开启无人值守自动回复",
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    disabled = client.post(
        "/api/automation",
        headers={"X-Yuda-Desktop": "1"},
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
