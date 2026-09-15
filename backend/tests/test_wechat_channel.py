from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from backend.app.ai import AIInput, AIProvider, AIResult, ProviderHealth
from backend.app.api import router as api_router
from backend.app.channels.base import ChannelSenderRegistry
from backend.app.channels.wechat import (
    WeChatAdapter,
    WechatMockProvider,
    WechatSender,
    WechatWebhookPayload,
)
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.models import AIGenerationTask, Conversation, Draft, Message
from backend.app.services.actions import HumanActions
from backend.app.services.ai_queue import AIJobQueue
from backend.app.services.notifier import MacOSNotifier
from backend.app.services.processor import MessageProcessor
from backend.app.wechat_api import wechat_router


class WechatTestProvider(AIProvider):
    name = "wechat_test"

    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[AIInput] = []

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        return ProviderHealth(status="connected")

    async def generate(
        self, payload: AIInput, *, task_key: str, model_selection=None
    ) -> AIResult:
        self.payloads.append(payload)
        return AIResult(
            direct="可以做，请把小程序功能、页面数量、截止时间和参考案例发来，我先确认范围。",
            friendly="您好，可以先详细说下小程序用途、所需功能和期望时间，有参考案例也请一起发我。",
            conversion="没问题，您把功能清单、参考资料和截止时间发来，我梳理好范围后给您明确方案。",
            risk_level="high",
            risk_reasons=["报价需确认"],
            needs_human_confirmation=True,
        )


@pytest.mark.asyncio
async def test_wechat_adapter_normalizes_mock_payload() -> None:
    received_at = datetime(2026, 8, 4, 4, 0, tzinfo=timezone.utc)
    adapter = WeChatAdapter(
        WechatMockProvider(id_factory=lambda: "wx-message-1", clock=lambda: received_at)
    )

    message = await adapter.receive_message(
        WechatWebhookPayload(
            user_id="wx-user-1",
            nickname="微信客户甲",
            content="这个小程序多少钱",
        )
    )

    assert message.channel == "wechat"
    assert message.platform_message_id == "wx-message-1"
    assert message.external_id == "wechat:wx-message-1"
    assert message.conversation_id == "wechat:wx-user-1"
    assert message.content == "这个小程序多少钱"
    assert (await adapter.get_conversation_info(message.conversation_id)).customer_name == "微信客户甲"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_wecom_image_normalization_keeps_media_id_ephemeral() -> None:
    adapter = WeChatAdapter()
    message = await adapter.receive_wecom_message(
        {
            "msgid": "wecom-image-1",
            "external_userid": "wx-customer-image",
            "open_kfid": "wk-image",
            "send_time": 1785816000,
            "origin": 3,
            "msgtype": "image",
            "image": {"media_id": "ephemeral-media-id"},
        },
        customer_name="微信图片客户",
    )

    assert message.message_type == "image"
    assert message.direction == "inbound"
    assert len(message.media) == 1
    assert message.media[0].locator_type == "wecom_media_id"
    assert message.media[0].locator == "ephemeral-media-id"


@pytest.mark.asyncio
async def test_wechat_webhook_persists_messages_without_legacy_ai_drafts(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'wechat-pipeline.db'}")
    database.create_all()
    provider = WechatTestProvider()
    queue = AIJobQueue(
        database,
        provider,
        Settings(
            _env_file=None,
            codex_max_concurrency=1,
            codex_max_context_messages=20,
            codex_max_context_chars=12_000,
        ),
    )
    wechat_adapter = WeChatAdapter(
        WechatMockProvider(id_factory=lambda: "wx-platform-1001")
    )
    processor = MessageProcessor(
        database,
        object(),  # WeChat events deliberately skip Xianyu context hydration.
        queue,
        MacOSNotifier(False),
        history_limit=20,
        reply_drafts_enabled=False,
    )
    runtime = SimpleNamespace(
        database=database,
        wechat_adapter=wechat_adapter,
        processor=processor,
    )
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(wechat_router)
    app.include_router(api_router)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/wechat/webhook",
                json={
                    "user_id": "wx-user-1001",
                    "nickname": "微信客户",
                    "content": "这个小程序多少钱",
                },
            )
            assert response.status_code == 202
            assert response.json()["channel"] == "wechat"

            # A retry with the same platform ID is idempotent and does not create
            # hidden AI work.
            duplicate = await client.post(
                "/wechat/webhook",
                json={
                    "user_id": "wx-user-1001",
                    "nickname": "微信客户",
                    "content": "这个小程序多少钱",
                    "message_id": "wx-platform-1001",
                },
            )
            assert duplicate.status_code == 202

            conversations = await client.get("/api/conversations?channel=wechat")
            assert conversations.status_code == 200
            rows = conversations.json()
            assert len(rows) == 1
            assert rows[0]["channel"] == "wechat"
            assert rows[0]["last_message"] == "这个小程序多少钱"

            detail = await client.get(f"/api/conversations/{rows[0]['id']}")
            assert detail.status_code == 200
            body = detail.json()
            assert body["channel"] == "wechat"
            assert body["messages"][-1]["platform_message_id"] == "wx-platform-1001"
            assert body["drafts"] == []
    finally:
        await processor.stop()

    assert provider.payloads == []
    with database.session() as session:
        assert len(list(session.scalars(select(Message)))) == 1
        assert list(session.scalars(select(Draft))) == []
        assert list(session.scalars(select(AIGenerationTask))) == []


@pytest.mark.asyncio
async def test_wechat_sender_is_selected_by_human_confirmation(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'wechat-send.db'}")
    database.create_all()
    with database.session() as session:
        conversation = Conversation(
            channel="wechat",
            external_id="wechat:wx-user-send",
            customer_id="wx-user-send",
            customer_name="微信客户",
            unread_count=1,
        )
        message = Message(
            channel="wechat",
            platform_message_id="wx-inbound-send",
            external_id="wechat:wx-inbound-send",
            conversation=conversation,
            sender_id="wx-user-send",
            sender_name="微信客户",
            direction="inbound",
            content="你好",
            status="drafted",
            received_at=datetime.now(timezone.utc),
        )
        session.add(message)
        session.commit()
        message_id = message.id

    sender = WechatSender()
    actions = HumanActions(database, ChannelSenderRegistry(sender))
    await actions.confirm_send(message_id, "您好，请把具体需求和参考资料发来，我先帮您确认范围。")

    assert len(sender.sent_messages) == 1
    assert sender.sent_messages[0]["receiver_id"] == "wx-user-send"
    with database.session() as session:
        outbound = session.scalar(
            select(Message).where(Message.direction == "outbound")
        )
        assert outbound is not None
        assert outbound.channel == "wechat"
        assert outbound.external_id.startswith("wechat:local-")
