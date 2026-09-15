from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from backend.app.adapters import (
    AdapterAccessVerificationError,
    AdapterDisconnectedError,
    AdapterError,
    IncomingMessage,
    ItemInfo,
    LoginExpiredError,
)
from backend.app.api import router
from backend.app.channels.base import ChannelMedia, ChannelMediaContent
from backend.app.database import Database
from backend.app.models import (
    AIGenerationTask,
    Conversation,
    ConversationHistoryImportRequest,
    CustomerImageArchive,
    Draft,
    Item,
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
        self.full_history_calls = 0
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

    async def fetch_all_messages(
        self,
        conversation_id: str,
        *,
        page_size: int = 100,
        max_messages: int = 5000,
    ):
        self.full_history_calls += 1
        assert page_size == 100
        assert max_messages == 5000
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
async def test_sync_never_requests_remote_item_even_without_local_metadata(tmp_path) -> None:
    service, database, adapter, queue = build_service(tmp_path)

    async def forbidden_item(_item_id: str):
        adapter.item_calls += 1
        raise AdapterAccessVerificationError("private platform verification response")

    adapter.fetch_item = forbidden_item  # type: ignore[method-assign]

    preview = await service.preview(
        external_conversation_id="conversation-history",
        message_limit=100,
    )

    assert preview["item"] is None
    assert preview["item_warning"] is None
    result = await service.commit(
        request_id="history_without_product_lookup",
        preview_token=preview["token"],
    )
    assert result["imported_count"] == 1
    assert adapter.item_calls == 0
    assert queue.calls == []
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Item)) == 0
        message = session.scalar(select(Message))
        assert message.source_item_external_id == "item-1"


@pytest.mark.asyncio
async def test_sync_uses_local_item_without_overwriting_newer_metadata(tmp_path) -> None:
    service, database, adapter, _queue = build_service(tmp_path)
    with database.session() as session:
        session.add(Item(external_id="item-1", title="本地商品", price="¥90"))
        session.commit()
    preview = await service.preview(external_conversation_id="conversation-history")
    assert preview["item"]["title"] == "本地商品"
    assert adapter.item_calls == 0
    with database.session() as session:
        item = session.scalar(select(Item))
        item.title = "预览之后更新的商品"
        item.price = "¥110"
        session.commit()
    result = await service.commit(
        request_id="history_local_product_metadata",
        preview_token=preview["token"],
    )
    with database.session() as session:
        conversation = session.get(Conversation, result["conversation_id"])
        assert conversation.item.title == "预览之后更新的商品"
        assert conversation.item.price == "¥110"


@pytest.mark.asyncio
async def test_missing_product_does_not_clear_existing_conversation_link(tmp_path) -> None:
    service, database, _adapter, _queue = build_service(tmp_path)
    with database.session() as session:
        item = Item(external_id="old-item", title="原有商品")
        session.add(item)
        conversation = Conversation(
            external_id="conversation-history", customer_id="buyer-1",
            customer_name="历史客户", item=item, unread_count=4,
        )
        session.add(conversation)
        session.commit()
    preview = await service.preview(external_conversation_id="conversation-history")
    result = await service.commit(
        request_id="history_preserve_existing_link", preview_token=preview["token"],
    )
    with database.session() as session:
        conversation = session.get(Conversation, result["conversation_id"])
        assert conversation.item.external_id == "old-item"
        assert conversation.unread_count == 4
        assert session.scalar(select(Message)).source_item_external_id == "item-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["search", "recent", "full", "page"])
@pytest.mark.parametrize("failure,code,status", [
    (LoginExpiredError, "xianyu_login_required", 401),
    (AdapterAccessVerificationError, "xianyu_verification_required", 409),
    (AdapterDisconnectedError, "xianyu_listener_unavailable", 409),
    (TimeoutError, "xianyu_history_timeout", 504),
    (httpx.ReadTimeout, "xianyu_history_timeout", 504),
    (ConnectionError, "xianyu_history_network_error", 503),
    (httpx.ConnectError, "xianyu_history_network_error", 503),
])
async def test_sync_errors_are_sanitized_and_do_not_retry_or_create_previews(
    tmp_path, entry, failure, code, status,
) -> None:
    service, database, adapter, queue = build_service(tmp_path)
    calls = []

    async def rejected(*_args, **_kwargs):
        calls.append(True)
        raise failure("private-response-secret")

    adapter.fetch_recent_conversation_messages = rejected
    adapter.fetch_recent_messages = rejected
    adapter.fetch_all_messages = rejected
    adapter.fetch_messages_page = rejected
    service.customer_images._cipher = Fernet(Fernet.generate_key())
    with pytest.raises(ConversationHistoryImportError) as result:
        if entry == "search":
            await service.search()
        else:
            await service.preview(
                external_conversation_id="conversation-history",
                full_history=entry == "full", paged=entry == "page",
            )
    assert result.value.code == code
    assert result.value.status_code == status
    assert "private-response-secret" not in result.value.safe_message
    assert len(calls) == 1
    assert service._previews == {}
    assert adapter.item_calls == 0
    assert queue.calls == []
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert session.scalar(select(func.count()).select_from(ConversationHistoryImportRequest)) == 0


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
async def test_full_history_preview_uses_explicit_full_reader_for_more_than_200_messages(tmp_path) -> None:
    messages = [
        history_message(f"message-{index:03d}", minutes=260 - index)
        for index in range(260)
    ]
    service, database, adapter, _queue = build_service(tmp_path, messages)

    preview = await service.preview(
        external_conversation_id="conversation-history",
        full_history=True,
    )

    assert preview["history_scope"] == "full"
    assert preview["platform_message_count"] == 260
    assert preview["new_count"] == 260
    assert adapter.full_history_calls == 1
    assert adapter.history_calls == 0
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.asyncio
async def test_incomplete_full_history_never_creates_a_committable_preview(tmp_path) -> None:
    service, database, adapter, _queue = build_service(tmp_path)

    async def interrupted_history(
        _conversation_id: str,
        *,
        page_size: int = 100,
        max_messages: int = 5000,
    ):
        raise AdapterError("分页游标异常")

    adapter.fetch_all_messages = interrupted_history  # type: ignore[method-assign]

    with pytest.raises(ConversationHistoryImportError) as unavailable:
        await service.preview(
            external_conversation_id="conversation-history",
            full_history=True,
        )

    assert unavailable.value.code == "xianyu_history_unavailable"
    assert service._previews == {}
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0


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
        assert conversation.item is None
        assert all(row.source_item_external_id == "item-1" for row in rows)
        assert session.scalar(select(func.count()).select_from(Item)) == 0


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


@pytest.mark.parametrize("failure,code,status", [
    (LoginExpiredError, "xianyu_login_required", 401),
    (AdapterAccessVerificationError, "xianyu_verification_required", 409),
    (httpx.ReadTimeout, "xianyu_history_timeout", 504),
    (httpx.ConnectError, "xianyu_history_network_error", 503),
])
def test_sync_api_returns_actionable_errors_without_private_details(tmp_path, failure, code, status):
    service, _database, adapter, _queue = build_service(tmp_path)

    async def rejected(*_args):
        raise failure("private-response-secret")

    adapter.fetch_recent_messages = rejected
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(conversation_history_import=service)
    with TestClient(app) as client:
        response = client.post(
            "/api/conversations/history-import/preview",
            headers={"X-Yuda-Desktop": "1"},
            json={"external_conversation_id": "conversation-history", "history_scope": "recent"},
        )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert "private-response-secret" not in response.text
    assert "token" not in response.json()


def test_sync_api_preview_confirm_replay_and_readback_without_product_api(tmp_path):
    messages = [
        history_message("api-text", minutes=2),
        history_message("api-image", with_media=True, message_type="image"),
    ]
    service, database, adapter, queue = build_service(tmp_path, messages)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(conversation_history_import=service, database=database)
    with TestClient(app) as client:
        preview = client.post(
            "/api/conversations/history-import/preview",
            headers={"X-Yuda-Desktop": "1"},
            json={"external_conversation_id": "conversation-history", "history_scope": "recent", "message_limit": 100},
        )
        assert preview.status_code == 200
        assert preview.json()["item_warning"] is None
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(Message)) == 0
        payload = {"request_id": "api_message_sync_001", "preview_token": preview.json()["token"], "mark_latest_pending": False}
        receipt = client.post("/api/conversations/history-import/commit", headers={"X-Yuda-Desktop": "1"}, json=payload)
        assert receipt.status_code == 200
        assert receipt.json()["imported_count"] == 2
        assert receipt.json()["image_stored_count"] == 1
        repeated = client.post("/api/conversations/history-import/commit", headers={"X-Yuda-Desktop": "1"}, json=payload)
        assert repeated.status_code == 200
        assert repeated.json()["idempotent"] is True
        listing = client.get("/api/conversations?channel=xianyu").json()
        assert len(listing) == 1
        assert datetime.fromisoformat(listing[0]["last_message_at"].replace("Z", "+00:00")) == messages[-1].received_at
    assert adapter.item_calls == 0
    assert adapter.media_calls == 1
    assert queue.calls == []
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 2
        assert session.scalar(select(func.count()).select_from(CustomerImageArchive)) == 1


def test_conversation_messages_can_page_back_through_all_local_history(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'conversation-pages.db'}")
    database.create_all()
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with database.session() as session:
        conversation = Conversation(
            channel="xianyu",
            external_id="conversation-pages",
            customer_id="buyer-pages",
            customer_name="分页客户",
            unread_count=0,
        )
        session.add(conversation)
        session.flush()
        for index in range(250):
            session.add(
                Message(
                    channel="xianyu",
                    platform_message_id=f"page-message-{index:03d}",
                    external_id=f"page-message-{index:03d}",
                    conversation_id=conversation.id,
                    sender_id="buyer-pages",
                    sender_name="分页客户",
                    direction="inbound",
                    message_type="text",
                    content=f"历史消息 {index:03d}",
                    status="history",
                    risk_flags_json="[]",
                    received_at=started_at + timedelta(minutes=index),
                )
            )
        session.commit()
        conversation_id = conversation.id

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(database=database)
    client = TestClient(app)

    detail = client.get(f"/api/conversations/{conversation_id}")
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 100
    assert detail.json()["has_older_messages"] is True
    first_anchor = detail.json()["messages"][0]["id"]

    second = client.get(
        f"/api/conversations/{conversation_id}/messages",
        params={"before_message_id": first_anchor, "limit": 100},
    )
    assert second.status_code == 200
    assert len(second.json()["messages"]) == 100
    assert second.json()["has_more"] is True
    assert second.json()["messages"][0]["content"] == "历史消息 050"

    third = client.get(
        f"/api/conversations/{conversation_id}/messages",
        params={
            "before_message_id": second.json()["messages"][0]["id"],
            "limit": 100,
        },
    )
    assert third.status_code == 200
    assert len(third.json()["messages"]) == 50
    assert third.json()["has_more"] is False
    assert third.json()["messages"][0]["content"] == "历史消息 000"
