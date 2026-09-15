from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from PIL import Image
import pytest
from sqlalchemy import select

from backend.app.adapters import (
    AdapterAccessVerificationError,
    AdapterDisconnectedError,
    LoginExpiredError,
)
from backend.app.channels.base import ChannelMedia, ChannelMediaContent, ChannelMessage
from backend.app.customer_image_api import customer_image_router
from backend.app.database import Database
from backend.app.models import (
    Conversation,
    CustomerImageArchive,
    CustomerImageHistoryRecoveryRun,
    Message,
)
from backend.app.services.customer_images import CustomerImageArchiveService, CustomerImageError
from backend.app.services.event_hub import EventHub
from backend.app.services.notifier import MacOSNotifier
from backend.app.services.processor import MessageProcessor


def original_jpeg() -> bytes:
    image = Image.new("RGB", (96, 64), (109, 78, 230))
    exif = Image.Exif()
    exif[0x010E] = "keep this original metadata"
    output = BytesIO()
    image.save(output, format="JPEG", quality=91, exif=exif)
    return output.getvalue()


def create_image_message(database: Database, *, suffix: str = "one") -> tuple[int, int]:
    with database.session() as session:
        conversation = Conversation(
            channel="xianyu",
            external_id=f"conversation-{suffix}",
            customer_id=f"customer-{suffix}",
            customer_name=f"客户 {suffix}",
        )
        message = Message(
            channel="xianyu",
            platform_message_id=f"platform-image-{suffix}",
            external_id=f"image-{suffix}",
            conversation=conversation,
            sender_id=f"customer-{suffix}",
            sender_name=f"客户 {suffix}",
            direction="inbound",
            message_type="image",
            content="[图片]",
            status="new",
            received_at=datetime(2026, 8, 17, 6, 32, tzinfo=timezone.utc),
        )
        session.add(message)
        session.commit()
        return conversation.id, message.id


def build_service(tmp_path: Path) -> tuple[Database, CustomerImageArchiveService, int, int]:
    database = Database(f"sqlite:///{tmp_path / 'data' / 'images.db'}")
    database.create_all()
    conversation_id, message_id = create_image_message(database)
    return database, CustomerImageArchiveService(database, tmp_path), conversation_id, message_id


@pytest.mark.asyncio
async def test_text_ingest_publishes_body_free_context_event_after_commit_without_ai(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'data' / 'context-event.db'}")
    database.create_all()
    hub = EventHub()
    subscription = hub.subscribe()

    class Queue:
        calls = 0

        async def enqueue(self, *_args, **_kwargs):
            self.calls += 1

    queue = Queue()
    processor = MessageProcessor(
        database,
        object(),
        queue,  # type: ignore[arg-type]
        MacOSNotifier(False),
        history_limit=20,
        reply_drafts_enabled=False,
        event_hub=hub,
    )
    event = ChannelMessage(
        channel="wechat",
        external_id="context-event-text",
        platform_message_id="context-event-text",
        conversation_id="context-event-conversation",
        sender_id="context-event-customer",
        sender_name="事件客户",
        content="这段正文不得进入事件载荷",
        message_type="text",
        received_at=datetime.now(timezone.utc),
    )

    message_id = await processor.process(event, source="wecom_callback")
    published = await asyncio.wait_for(subscription.queue.get(), timeout=1)
    assert published == {
        "type": "customer_context_updated",
        "conversation_id": published["conversation_id"],
        "message_id": message_id,
        "channel": "wechat",
        "direction": "inbound",
    }
    assert "content" not in published
    assert "正文" not in str(published)
    assert queue.calls == 0
    with database.session() as session:
        persisted = session.get(Message, message_id)
        assert persisted is not None
        assert persisted.conversation_id == published["conversation_id"]
        assert persisted.content == "这段正文不得进入事件载荷"


def test_original_bytes_and_exif_are_preserved_in_image_only_tree(tmp_path: Path) -> None:
    database, service, _conversation_id, message_id = build_service(tmp_path)
    payload = original_jpeg()

    view = service.store_original(
        message_id,
        0,
        data=payload,
        content_type="image/jpeg",
        original_name="customer-original.jpg",
        capture_source="test",
    )
    path, mime, name = service.content_file(view["id"])

    assert mime == "image/jpeg"
    assert name == "customer-original.jpg"
    assert path.read_bytes() == payload
    assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(payload).hexdigest()
    with Image.open(path) as stored:
        assert stored.getexif()[0x010E] == "keep this original metadata"
    assert oct(service.root.stat().st_mode & 0o777) == "0o700"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert all(file.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".avif", ".heic", ".heif"} for file in service.root.rglob("*") if file.is_file())
    with database.session() as session:
        row = session.scalar(select(CustomerImageArchive))
        assert row is not None and row.integrity_verified is True


@pytest.mark.asyncio
async def test_platform_replay_is_idempotent_and_does_not_duplicate_files(tmp_path: Path) -> None:
    database, service, _conversation_id, message_id = build_service(tmp_path)
    payload = original_jpeg()
    event = ChannelMessage(
        channel="xianyu",
        external_id="image-one",
        platform_message_id="platform-image-one",
        conversation_id="conversation-one",
        sender_id="customer-one",
        sender_name="客户 one",
        content="[图片]",
        message_type="image",
        received_at=datetime(2026, 8, 17, 6, 32, tzinfo=timezone.utc),
        media=(ChannelMedia("remote_url", "https://img.alicdn.com/original.jpg"),),
    )

    async def fetch(_media: ChannelMedia) -> ChannelMediaContent:
        return ChannelMediaContent(payload, "image/jpeg", "original.jpg")

    first = await service.capture_message(event, message_id, fetch, capture_source="live")
    second = await service.capture_message(event, message_id, fetch, capture_source="live")

    assert first == {"stored": 1, "failed": 0}
    assert second == {"stored": 1, "failed": 0}
    with database.session() as session:
        assert len(list(session.scalars(select(CustomerImageArchive)))) == 1
    assert len([path for path in service.root.rglob("*") if path.is_file()]) == 1


@pytest.mark.asyncio
async def test_archive_failure_never_rolls_back_message_ingestion(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'data' / 'pipeline.db'}")
    database.create_all()
    service = CustomerImageArchiveService(database, tmp_path)

    class Queue:
        async def enqueue(self, *_args, **_kwargs):
            raise AssertionError("paused AI queue must not run")

    async def fail(_media: ChannelMedia) -> ChannelMediaContent:
        raise RuntimeError("signed url expired and must not leak")

    processor = MessageProcessor(
        database,
        object(),  # WeChat images skip Xianyu context hydration.
        Queue(),  # type: ignore[arg-type]
        MacOSNotifier(False),
        history_limit=20,
        reply_drafts_enabled=False,
        customer_images=service,
        media_fetchers={"wechat": fail},
    )
    event = ChannelMessage(
        channel="wechat",
        external_id="wechat:image-failure",
        platform_message_id="image-failure",
        conversation_id="wechat:kf:customer",
        sender_id="customer",
        sender_name="微信客户",
        content="[客户发送了图片]",
        message_type="image",
        received_at=datetime.now(timezone.utc),
        media=(ChannelMedia("wecom_media_id", "private-media-id"),),
    )

    message_id = await processor.process(event, source="wecom_callback")
    await service.drain_pending()
    await processor.stop()
    with database.session() as session:
        message = session.get(Message, message_id)
        row = session.scalar(select(CustomerImageArchive))
        assert message is not None and message.content == "[客户发送了图片]"
        assert row is not None and row.capture_status == "failed"
        assert row.error_code == "remote_fetch_failed"
        assert "private-media-id" not in " ".join(str(value) for value in row.__dict__.values())


@pytest.mark.asyncio
async def test_inbound_processor_archives_original_bytes_without_running_ai(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'data' / 'pipeline-success.db'}")
    database.create_all()
    service = CustomerImageArchiveService(database, tmp_path)
    payload = original_jpeg()

    class Queue:
        async def enqueue(self, *_args, **_kwargs):
            raise AssertionError("customer image archiving must not run AI")

    async def fetch(_media: ChannelMedia) -> ChannelMediaContent:
        return ChannelMediaContent(payload, "image/jpeg", "customer-original.jpg")

    processor = MessageProcessor(
        database,
        object(),  # WeChat images do not hydrate Xianyu context.
        Queue(),  # type: ignore[arg-type]
        MacOSNotifier(False),
        history_limit=20,
        reply_drafts_enabled=False,
        customer_images=service,
        media_fetchers={"wechat": fetch},
    )
    event = ChannelMessage(
        channel="wechat",
        external_id="wechat:image-success",
        platform_message_id="image-success",
        conversation_id="wechat:kf:customer-success",
        sender_id="customer-success",
        sender_name="微信客户",
        content="[客户发送了图片]",
        message_type="image",
        received_at=datetime.now(timezone.utc),
        media=(ChannelMedia("wecom_media_id", "ephemeral-media-id"),),
    )

    message_id = await processor.process(event, source="wecom_callback")
    await service.drain_pending()
    await processor.stop()
    with database.session() as session:
        message = session.get(Message, message_id)
        row = session.scalar(select(CustomerImageArchive))
        assert message is not None and message.direction == "inbound"
        assert row is not None and row.capture_status == "stored"
        archive_id = row.id
    path, mime_type, original_name = service.content_file(archive_id)
    assert path.read_bytes() == payload
    assert mime_type == "image/jpeg"
    assert original_name == "customer-original.jpg"


def test_shared_original_survives_one_local_copy_deletion(tmp_path: Path) -> None:
    database, service, _conversation_id, first_message_id = build_service(tmp_path)
    _second_conversation_id, second_message_id = create_image_message(database, suffix="two")
    payload = original_jpeg()
    first = service.store_original(first_message_id, 0, data=payload, content_type="image/jpeg", original_name="one.jpg", capture_source="test")
    second = service.store_original(second_message_id, 0, data=payload, content_type="image/jpeg", original_name="two.jpg", capture_source="test")
    first_path = service.content_file(first["id"])[0]
    assert first_path == service.content_file(second["id"])[0]

    service.delete_local_copy(first["id"])

    assert first_path.is_file()
    assert service.content_file(second["id"])[0].read_bytes() == payload
    assert service.list_images()["total"] == 1


@pytest.mark.asyncio
async def test_interrupted_pending_capture_is_visible_and_can_resume(tmp_path: Path) -> None:
    database, service, _conversation_id, message_id = build_service(tmp_path)
    pending = service._ensure_row(message_id, 0, capture_source="history_import")

    status = service.status()
    attention = service.attention_items()

    assert pending.capture_status == "pending"
    assert status["attention_count"] == 1
    assert status["pending_count"] == 1
    assert status["failed_count"] == 0
    assert attention[0]["status"] == "pending"
    assert attention[0]["error_code"] == "capture_interrupted"

    event = ChannelMessage(
        channel="xianyu",
        external_id="image-one",
        platform_message_id="platform-image-one",
        conversation_id="conversation-one",
        sender_id="customer-one",
        sender_name="客户 one",
        content="[图片]",
        message_type="image",
        received_at=datetime(2026, 8, 17, 6, 32, tzinfo=timezone.utc),
        media=(ChannelMedia("remote_url", "https://img.alicdn.com/original.jpg"),),
    )

    async def fetch(_media: ChannelMedia) -> ChannelMediaContent:
        return ChannelMediaContent(original_jpeg(), "image/jpeg", "original.jpg")

    result = await service.capture_message(
        event,
        message_id,
        fetch,
        capture_source="history_import",
    )

    assert result == {"stored": 1, "failed": 0}
    assert service.status()["attention_count"] == 0
    assert service.attention_items() == []
    with database.session() as session:
        row = session.get(CustomerImageArchive, pending.id)
        assert row is not None and row.capture_status == "stored"


@pytest.mark.asyncio
async def test_api_never_exposes_storage_path_or_digest(tmp_path: Path) -> None:
    database, service, conversation_id, message_id = build_service(tmp_path)
    payload = original_jpeg()
    view = service.store_original(message_id, 0, data=payload, content_type="image/jpeg", original_name="safe.jpg", capture_source="test")
    runtime = SimpleNamespace(customer_images=service)
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(customer_image_router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8877") as client:
        listing = await client.get("/api/customer-images")
        body = listing.json()
        assert listing.status_code == 200
        assert body["total"] == 1
        serialized = listing.text
        assert "storage_path" not in serialized
        assert "sha256" not in serialized
        assert str(service.root) not in serialized
        assert body["items"][0]["conversation_id"] == conversation_id

        content = await client.get(view["content_url"])
        assert content.status_code == 200
        assert content.content == payload
        assert content.headers["cache-control"] == "private, no-store"

        download = await client.get(view["download_url"])
        assert download.status_code == 200
        assert download.content == payload
        assert download.headers["content-disposition"].startswith("attachment;")

        denied = await client.post(f"/api/customer-images/{view['id']}/delete", json={"confirmed": False})
        assert denied.status_code == 400
        deleted = await client.post(f"/api/customer-images/{view['id']}/delete", json={"confirmed": True})
        assert deleted.status_code == 204
        assert service.list_images()["total"] == 0

        removed_upload = await client.post(
            f"/api/customer-images/messages/{message_id}/upload"
        )
        assert removed_upload.status_code == 404


def test_original_store_rejects_non_inbound_and_oversized_files(tmp_path: Path) -> None:
    database, service, _conversation_id, message_id = build_service(tmp_path)
    with pytest.raises(CustomerImageError, match="25 MB"):
        service.store_original(
            message_id,
            0,
            data=b"x" * (service.MAX_IMAGE_BYTES + 1),
            content_type="image/jpeg",
            original_name="too-large.jpg",
            capture_source="test",
        )

    with database.session() as session:
        message = session.get(Message, message_id)
        assert message is not None
        message.direction = "outbound"
        session.commit()
    with pytest.raises(CustomerImageError, match="客户图片消息"):
        service.store_original(
            message_id,
            0,
            data=original_jpeg(),
            content_type="image/jpeg",
            original_name="outbound.jpg",
            capture_source="test",
        )


def test_heic_header_only_is_never_accepted_as_a_complete_image(tmp_path: Path) -> None:
    _database, service, _conversation_id, message_id = build_service(tmp_path)
    payload = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1"

    with pytest.raises(CustomerImageError) as error:
        service.store_original(message_id, 0, data=payload, content_type="image/heic", original_name="../../private\r\noriginal.heic", capture_source="test")
    assert error.value.code in {"image_corrupt", "image_decoder_unavailable"}
    assert not list(service.root.rglob("*.heic"))


@pytest.mark.asyncio
async def test_history_recovery_is_serial_idempotent_and_only_replays_existing_placeholders(tmp_path: Path) -> None:
    _database, service, _conversation_id, message_id = build_service(tmp_path)
    payload = original_jpeg()
    matching = ChannelMessage(
        channel="xianyu",
        external_id="image-one",
        platform_message_id="platform-image-one",
        conversation_id="conversation-one",
        sender_id="customer-one",
        sender_name="客户 one",
        content="[图片]",
        message_type="image",
        received_at=datetime(2026, 8, 17, 6, 32, tzinfo=timezone.utc),
        media=(ChannelMedia("remote_url", "https://img.alicdn.com/original.jpg"),),
    )
    unrelated = ChannelMessage(
        channel="xianyu",
        external_id="unrelated-image",
        platform_message_id="unrelated-platform-image",
        conversation_id="conversation-one",
        sender_id="customer-one",
        sender_name="客户 one",
        content="[图片]",
        message_type="image",
        received_at=datetime(2026, 8, 17, 6, 33, tzinfo=timezone.utc),
        media=(ChannelMedia("remote_url", "https://img.alicdn.com/unrelated.jpg"),),
    )

    class Adapter:
        calls = 0

        async def fetch_recent_messages(self, _conversation_id: str, limit: int):
            assert limit == 200
            self.calls += 1
            await asyncio.sleep(0.01)
            return [unrelated, matching]

    class Processor:
        processed: list[str] = []

        async def process(self, event: ChannelMessage, *, source: str):
            assert source == "image_history"
            self.processed.append(event.external_id)

            async def fetch(_media: ChannelMedia) -> ChannelMediaContent:
                return ChannelMediaContent(payload, "image/jpeg", "original.jpg")

            await service.capture_message(event, message_id, fetch, capture_source=source)

    adapter = Adapter()
    processor = Processor()
    first, second = await asyncio.gather(
        service.recover_xianyu_history("history-request-123", adapter, processor),
        service.recover_xianyu_history("history-request-123", adapter, processor),
    )

    assert first == second
    assert first["stored_count"] == 1
    assert adapter.calls == 1
    assert processor.processed == ["image-one"]
    with _database.session() as session:
        receipt = session.get(CustomerImageHistoryRecoveryRun, "history-request-123")
        assert receipt is not None and receipt.status == "completed"

    # A fresh service instance simulates a process restart: the persisted
    # request receipt must prevent a second platform history read.
    restarted = CustomerImageArchiveService(_database, tmp_path)
    third = await restarted.recover_xianyu_history(
        "history-request-123", adapter, processor
    )
    assert third == first
    assert adapter.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (LoginExpiredError("login"), "xianyu_login_required"),
        (
            AdapterAccessVerificationError("verify"),
            "xianyu_verification_required",
        ),
        (AdapterDisconnectedError("offline"), "xianyu_disconnected"),
    ],
)
async def test_history_recovery_stops_on_auth_or_connection_failure(
    tmp_path: Path,
    failure: Exception,
    expected_code: str,
) -> None:
    database, service, _conversation_id, _message_id = build_service(tmp_path)
    create_image_message(database, suffix="second")

    class Adapter:
        calls: list[tuple[str, int]] = []

        async def fetch_recent_messages(self, conversation_id: str, limit: int):
            self.calls.append((conversation_id, limit))
            raise failure

    class Processor:
        async def process(self, *_args, **_kwargs):
            raise AssertionError("熔断后不得处理历史图片")

    adapter = Adapter()
    result = await service.recover_xianyu_history(
        f"history-fuse-{expected_code}", adapter, Processor()
    )
    assert result["conversation_count"] == 2
    assert result["checked_conversation_count"] == 1
    assert result["stored_count"] == 0
    assert result["failed_count"] == 1
    assert result["failed_conversations"][0]["error_code"] == expected_code
    assert result["stopped_early"] is True
    assert len(adapter.calls) == 1
    assert adapter.calls[0][1] == 200


@pytest.mark.asyncio
async def test_history_recovery_reports_partial_success_and_continues_safe_failures(
    tmp_path: Path,
) -> None:
    database, service, _conversation_id, first_message_id = build_service(tmp_path)
    _second_conversation_id, second_message_id = create_image_message(
        database, suffix="second"
    )
    payload = original_jpeg()
    messages = {
        "conversation-one": (
            first_message_id,
            ChannelMessage(
                channel="xianyu",
                external_id="image-one",
                platform_message_id="platform-image-one",
                conversation_id="conversation-one",
                sender_id="customer-one",
                sender_name="客户 one",
                content="[图片]",
                message_type="image",
                received_at=datetime(2026, 8, 17, 6, 32, tzinfo=timezone.utc),
                media=(ChannelMedia("remote_url", "https://img.alicdn.com/one.jpg"),),
            ),
        ),
        "conversation-second": (
            second_message_id,
            ChannelMessage(
                channel="xianyu",
                external_id="image-second",
                platform_message_id="platform-image-second",
                conversation_id="conversation-second",
                sender_id="customer-second",
                sender_name="客户 second",
                content="[图片]",
                message_type="image",
                received_at=datetime(2026, 8, 17, 6, 33, tzinfo=timezone.utc),
                media=(
                    ChannelMedia("remote_url", "https://img.alicdn.com/second.jpg"),
                ),
            ),
        ),
    }

    class Adapter:
        calls: list[str] = []

        async def fetch_recent_messages(self, conversation_id: str, limit: int):
            assert limit == 200
            self.calls.append(conversation_id)
            if len(self.calls) == 1:
                raise RuntimeError("one conversation failed safely")
            return [messages[conversation_id][1]]

    class Processor:
        processed: list[str] = []

        async def process(self, event: ChannelMessage, *, source: str):
            self.processed.append(event.platform_message_id)

            async def fetch(_media: ChannelMedia) -> ChannelMediaContent:
                return ChannelMediaContent(payload, "image/jpeg", "original.jpg")

            await service.capture_message(
                event,
                messages[event.conversation_id][0],
                fetch,
                capture_source=source,
            )

    adapter = Adapter()
    processor = Processor()
    result = await service.recover_xianyu_history(
        "history-partial-success", adapter, processor
    )
    assert result["conversation_count"] == 2
    assert result["checked_conversation_count"] == 2
    assert result["stored_count"] == 1
    assert result["unmatched_count"] == 1
    assert result["failed_count"] == 1
    assert result["failed_conversations"][0]["error_code"] == "history_fetch_failed"
    assert result["stopped_early"] is False
    assert len(processor.processed) == 1
