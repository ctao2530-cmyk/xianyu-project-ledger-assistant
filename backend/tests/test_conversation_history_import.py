from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from backend.app.adapters import IncomingMessage, ItemInfo
from backend.app.api import router
from backend.app.channels.base import ChannelMedia, ChannelMediaContent
from backend.app.database import Database
from backend.app.models import (
    AIGenerationTask,
    Conversation,
    ConversationHistoryImportRequest,
    CustomerImageArchive,
    Draft,
    Message,
)
from backend.app.services.conversation_history_import import (
    ConversationHistoryImportError,
    ConversationHistoryImportService,
)
from backend.app.services.customer_images import CustomerImageArchiveService


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), (101, 68, 244)).save(output, format="PNG")
    return output.getvalue()


class HistoryAdapterStub:
    connected = True
    own_user_id = "seller-1"

    def __init__(self, messages: list[IncomingMessage]) -> None:
        self.messages = messages
        self.search_calls = 0
        self.history_calls = 0
        self.item_calls = 0
        self.media_calls = 0
        self.fail_media: set[str] = set()

    async def fetch_recent_conversation_messages(self, _limit: int):
        self.search_calls += 1
        latest: dict[str, IncomingMessage] = {}
        for message in self.messages:
            current = latest.get(message.conversation_id)
            if current is None or message.received_at > current.received_at:
                latest[message.conversation_id] = message
        return list(latest.values())

    async def fetch_recent_messages(self, conversation_id: str, _limit: int):
        self.history_calls += 1
        return [
            message for message in self.messages if message.conversation_id == conversation_id
        ]

    async def fetch_item(self, item_id: str):
        self.item_calls += 1
        return ItemInfo(
            external_id=item_id,
            title="技术实现服务",
            price="¥99",
            description="商品说明",
            raw={"secret": "must-not-be-persisted"},
        )

    async def fetch_media(self, media: ChannelMedia):
        self.media_calls += 1
        if media.locator in self.fail_media:
            raise RuntimeError("private signed media failure")
        return ChannelMediaContent(image_bytes(), "image/png", "customer-original.png")


class QueueStub:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []

    async def enqueue(self, message_id: int, *, automatic: bool):
        self.calls.append((message_id, automatic))
        return SimpleNamespace(id=73)


def history_message(
    external_id: str,
    *,
    conversation_id: str = "conversation-history",
    direction: str = "inbound",
    minutes: int = 0,
    message_type: str = "text",
    with_media: bool = False,
) -> IncomingMessage:
    return IncomingMessage(
        external_id=external_id,
        platform_message_id=external_id,
        conversation_id=conversation_id,
        sender_id="buyer-1" if direction == "inbound" else "seller-1",
        sender_name="历史客户" if direction == "inbound" else "店主",
        content=("[暂不支持的历史消息类型]" if message_type == "unsupported" else f"消息 {external_id}"),
        message_type=message_type,
        received_at=datetime.now(timezone.utc) - timedelta(minutes=minutes),
        item_id="item-1",
        direction=direction,
        media=(ChannelMedia("remote_url", external_id),) if with_media else (),
    )


def build_service(tmp_path, messages: list[IncomingMessage] | None = None):
    database = Database(f"sqlite:///{tmp_path / 'history-import.db'}")
    database.create_all()
    adapter = HistoryAdapterStub(messages or [history_message("message-1")])
    queue = QueueStub()
    customer_images = CustomerImageArchiveService(database, tmp_path)
    return (
        ConversationHistoryImportService(
            database,
            adapter,  # type: ignore[arg-type]
            queue,  # type: ignore[arg-type]
            customer_images=customer_images,
            token_ttl_seconds=30,
        ),
        database,
        adapter,
        queue,
    )


@pytest.mark.asyncio
async def test_confirmed_history_import_archives_only_inbound_images_and_keeps_partial_failures(tmp_path) -> None:
    messages = [
        history_message("image-ok", message_type="image", with_media=True, minutes=3),
        history_message("image-outbound", direction="outbound", message_type="image", with_media=True, minutes=2),
        history_message("image-fail", message_type="image", with_media=True),
    ]
    service, database, adapter, _queue = build_service(tmp_path, messages)
    adapter.fail_media.add("image-fail")
    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )

    result = await service.commit(
        request_id="history_request_images",
        preview_token=preview["token"],
    )
    repeated = await service.commit(
        request_id="history_request_images",
        preview_token=preview["token"],
    )

    assert result["imported_count"] == 3
    assert result["image_candidate_count"] == 2
    assert result["image_stored_count"] == 1
    assert result["image_failed_count"] == 1
    assert repeated["idempotent"] is True
    assert adapter.media_calls == 2
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 3
        archives = list(session.scalars(select(CustomerImageArchive)))
        assert sorted(row.capture_status for row in archives) == ["failed", "stored"]
        request = session.get(ConversationHistoryImportRequest, "history_request_images")
        assert request is not None and '"image_stored_count": 1' in request.result_json


@pytest.mark.asyncio
async def test_item_timeout_degrades_preview_without_blocking_import(tmp_path) -> None:
    service, _database, adapter, _queue = build_service(tmp_path)

    async def slow_item(_item_id: str):
        await __import__("asyncio").sleep(0.05)
        raise AssertionError("wait_for should cancel the optional item request")

    adapter.fetch_item = slow_item  # type: ignore[method-assign]
    service.item_timeout_seconds = 0.01

    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )

    assert preview["item"] is None
    assert preview["item_warning"] == "商品信息读取超时，但不影响核对和导入本次会话"


@pytest.mark.asyncio
async def test_history_timeout_is_explicit_and_writes_nothing(tmp_path) -> None:
    service, database, adapter, _queue = build_service(tmp_path)

    async def slow_history(_conversation_id: str, _limit: int):
        await __import__("asyncio").sleep(0.05)
        return []

    adapter.fetch_recent_messages = slow_history  # type: ignore[method-assign]
    service.history_timeout_seconds = 0.01

    with pytest.raises(ConversationHistoryImportError) as timeout:
        await service.preview(
            external_conversation_id="conversation-history",
            message_limit=100,
        )
    assert timeout.value.code == "xianyu_history_timeout"
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert session.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.asyncio
async def test_search_and_preview_are_read_only(tmp_path) -> None:
    service, database, adapter, _queue = build_service(
        tmp_path,
        [history_message("message-1", minutes=3), history_message("message-2")],
    )

    search = await service.search(query="历史客户", days=30, limit=20)
    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )

    assert len(search) == 1
    assert search[0]["existing_conversation_id"] is None
    assert preview["new_count"] == 2
    assert preview["existing_count"] == 0
    assert adapter.search_calls == 1
    assert adapter.history_calls == 1
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(func.count()).select_from(ConversationHistoryImportRequest)) == 0


@pytest.mark.asyncio
async def test_commit_imports_history_without_unread_ai_or_drafts(tmp_path) -> None:
    service, database, _adapter, queue = build_service(
        tmp_path,
        [
            history_message("message-1", minutes=5),
            history_message("message-2", direction="outbound", minutes=2),
            history_message("message-3"),
        ],
    )
    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )

    result = await service.commit(
        request_id="history_request_001",
        preview_token=preview["token"],
    )

    assert result["imported_count"] == 3
    assert result["pending_message_id"] is None
    assert result["draft_task_queued"] is False
    assert queue.calls == []
    with database.session() as session:
        conversation = session.get(Conversation, result["conversation_id"])
        assert conversation is not None
        assert conversation.unread_count == 0
        rows = list(session.scalars(select(Message).order_by(Message.received_at)))
        assert [row.status for row in rows] == ["history", "sent", "history"]
        assert session.scalar(select(func.count()).select_from(AIGenerationTask)) == 0
        assert session.scalar(select(func.count()).select_from(Draft)) == 0
        assert conversation.item is not None
        assert conversation.item.raw_json is None


@pytest.mark.asyncio
async def test_existing_messages_are_deduplicated_and_request_is_idempotent(tmp_path) -> None:
    service, database, _adapter, _queue = build_service(
        tmp_path,
        [history_message("message-1", minutes=2), history_message("message-2")],
    )
    first_preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )
    first = await service.commit(
        request_id="history_request_002",
        preview_token=first_preview["token"],
    )
    repeat = await service.commit(
        request_id="history_request_002",
        preview_token=first_preview["token"],
    )
    second_preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )
    second = await service.commit(
        request_id="history_request_003",
        preview_token=second_preview["token"],
    )

    assert first["imported_count"] == 2
    assert repeat["idempotent"] is True
    assert second["imported_count"] == 0
    assert second["existing_count"] == 2
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 2


@pytest.mark.asyncio
async def test_request_conflict_and_expired_preview_are_rejected(tmp_path) -> None:
    service, _database, _adapter, _queue = build_service(tmp_path)
    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )
    await service.commit(
        request_id="history_request_004",
        preview_token=preview["token"],
    )

    with pytest.raises(ConversationHistoryImportError) as conflict:
        await service.commit(
            request_id="history_request_004",
            preview_token="different-preview-token-value",
        )
    assert conflict.value.code == "request_conflict"

    with pytest.raises(ConversationHistoryImportError) as expired:
        await service.commit(
            request_id="history_request_005",
            preview_token="missing-preview-token-value",
        )
    assert expired.value.code == "preview_expired"


@pytest.mark.asyncio
async def test_cross_conversation_platform_identity_conflict_is_rejected(tmp_path) -> None:
    service, database, _adapter, _queue = build_service(tmp_path)
    with database.session() as session:
        other = Conversation(
            channel="xianyu",
            external_id="another-conversation",
            customer_id="another-buyer",
            customer_name="另一位客户",
            unread_count=0,
        )
        session.add(other)
        session.flush()
        session.add(
            Message(
                channel="xianyu",
                platform_message_id="message-1",
                external_id="stored-message-1",
                conversation_id=other.id,
                sender_id="another-buyer",
                sender_name="另一位客户",
                direction="inbound",
                message_type="text",
                content="已有消息",
                status="history",
                risk_flags_json="[]",
            )
        )
        session.commit()

    with pytest.raises(ConversationHistoryImportError) as conflict:
        await service.preview(
            external_conversation_id="conversation-history",
            message_limit=100,
        )
    assert conflict.value.code == "message_identity_conflict"


@pytest.mark.asyncio
async def test_unsupported_message_uses_safe_placeholder(tmp_path) -> None:
    service, database, _adapter, _queue = build_service(
        tmp_path,
        [history_message("attachment-1", message_type="unsupported")],
    )
    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )
    result = await service.commit(
        request_id="history_request_006",
        preview_token=preview["token"],
    )

    assert preview["unsupported_count"] == 1
    assert preview["messages"][0]["content"] == "[暂不支持的历史消息，已保留安全占位]"
    with database.session() as session:
        row = session.get(Message, result["pending_message_id"] or 1)
        assert row is not None
        assert row.content == "[暂不支持的历史消息，已保留安全占位]"


@pytest.mark.asyncio
async def test_optional_pending_marks_only_latest_inbound_and_queues_once(tmp_path) -> None:
    service, database, _adapter, queue = build_service(
        tmp_path,
        [
            history_message("inbound-1", minutes=4),
            history_message("outbound-1", direction="outbound", minutes=2),
            history_message("inbound-2"),
        ],
    )
    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )
    result = await service.commit(
        request_id="history_request_007",
        preview_token=preview["token"],
        mark_latest_pending=True,
    )
    repeat = await service.commit(
        request_id="history_request_007",
        preview_token=preview["token"],
        mark_latest_pending=True,
    )

    assert result["draft_task_queued"] is True
    assert repeat["idempotent"] is True
    assert queue.calls == [(result["pending_message_id"], True)]
    with database.session() as session:
        pending = session.get(Message, result["pending_message_id"])
        assert pending is not None and pending.external_id == "inbound-2"
        assert pending.status == "new"
        conversation = session.get(Conversation, result["conversation_id"])
        assert conversation is not None and conversation.unread_count == 0


@pytest.mark.asyncio
async def test_paused_reply_drafts_keep_pending_fact_without_queueing_model_work(tmp_path) -> None:
    service, database, _adapter, queue = build_service(
        tmp_path,
        [history_message("paused-inbound")],
    )
    service.draft_generation_enabled = False
    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )

    result = await service.commit(
        request_id="history_request_paused_drafts",
        preview_token=preview["token"],
        mark_latest_pending=True,
    )

    assert result["pending_message_id"] is not None
    assert result["draft_task_queued"] is False
    assert result["draft_task_id"] is None
    assert queue.calls == []
    with database.session() as session:
        pending = session.get(Message, result["pending_message_id"])
        assert pending is not None and pending.status == "new"


def test_history_import_api_requires_local_header_and_never_commits_on_preview() -> None:
    class ServiceStub:
        async def search(self, **_kwargs):
            return []

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(conversation_history_import=ServiceStub())
    client = TestClient(app)
    payload = {"query": "", "days": 30, "limit": 20}

    denied = client.post("/api/conversations/history-import/search", json=payload)
    allowed = client.post(
        "/api/conversations/history-import/search",
        json=payload,
        headers={"X-Yuda-Desktop": "1"},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json() == []
