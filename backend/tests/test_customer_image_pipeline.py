from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO

import httpx
from fastapi import FastAPI
from PIL import Image
import pytest
from sqlalchemy import select

from backend.app.adapters import AdapterAccessVerificationError
from backend.app.channels.base import ChannelMedia, ChannelMediaContent, ChannelMessage
from backend.app.customer_image_api import customer_image_router
from backend.app.customer_media_models import CustomerImageCaptureJob
from backend.app.models import CustomerImageArchive, Message
from backend.app.services.customer_images import CustomerImageArchiveService, CustomerImageError
from backend.app.services.event_hub import EventHub
from backend.app.services.image_codec import validate_image, ImageCodecError
from backend.app.services.repository import ingest_message
from backend.tests.test_customer_images import build_service, original_jpeg, create_image_message


def event(*, count=1, suffix="one", channel="xianyu"):
    return ChannelMessage(channel=channel, external_id=f"image-{suffix}", platform_message_id=f"platform-image-{suffix}", conversation_id=f"conversation-{suffix}", sender_id=f"customer-{suffix}", sender_name="synthetic", content="[图片]", message_type="image", received_at=datetime.now(timezone.utc), media=tuple(ChannelMedia("remote_url", f"https://images.example.test/{index}.jpg", media_index=index) for index in range(count)))


@pytest.mark.asyncio
async def test_duplicate_provider_indices_and_mixed_media_remain_three_images(tmp_path):
    _, service, _, message_id = build_service(tmp_path)
    incoming = event(count=3)
    incoming.message_type = "text"
    incoming.media = tuple(ChannelMedia("remote_url", str(i), media_index=value) for i, value in enumerate([1, 1, 2]))
    async def fetch(_):
        return ChannelMediaContent(original_jpeg(), "image/jpeg")
    assert await service.capture_message(incoming, message_id, fetch, capture_source="live") == {"stored": 3, "failed": 0}
    assert {row["media_index"] for row in service.list_images()["items"]} == {0, 1, 2}


@pytest.mark.asyncio
async def test_history_page_continuation_is_bound_and_persisted_across_restart(tmp_path):
    from backend.tests.test_conversation_history_import import build_service as build_history, history_message
    from backend.app.services.conversation_history_import import ConversationHistoryImportService, ConversationHistoryImportError
    service, db, adapter, queue = build_history(tmp_path)
    calls = []
    async def page(conversation_id, *, page_size, cursor):
        calls.append(cursor)
        return [history_message("page-1" if cursor is None else "page-2", conversation_id=conversation_id, message_type="image", with_media=True)], "next-123" if cursor is None else None, cursor is None
    adapter.fetch_messages_page = page
    preview = await service.preview(external_conversation_id="conversation-history", message_limit=200, paged=True)
    result = await service.commit(request_id="synthetic-page-1", preview_token=preview["token"])
    assert result["has_more"] and result["image_stored_count"] == 1
    restarted = ConversationHistoryImportService(db, adapter, queue, customer_images=CustomerImageArchiveService(db, tmp_path))
    receipt = await restarted.commit(request_id="synthetic-page-1", preview_token=preview["token"])
    assert receipt["next_continuation_token"] == result["next_continuation_token"]
    with pytest.raises(ConversationHistoryImportError) as denied:
        await restarted.preview(external_conversation_id="other-customer", message_limit=200, paged=True, continuation_token=receipt["next_continuation_token"])
    assert denied.value.code == "history_cursor_invalid" and calls == [None]
    final = await restarted.preview(external_conversation_id="conversation-history", message_limit=200, paged=True, continuation_token=receipt["next_continuation_token"])
    assert final["history_complete"] and not final["has_more"]
    assert calls == [None, "next-123"]


def test_real_heif_codec_preserves_original(tmp_path):
    heif = pytest.importorskip("pillow_heif", reason="HEIF acceptance requires the declared optional native decoder in an isolated target")
    heif.register_heif_opener()
    _, service, _, message_id = build_service(tmp_path)
    output = BytesIO()
    Image.new("RGB", (30, 20), "green").save(output, format="HEIF")
    payload = output.getvalue()
    row = service.store_original(message_id, 0, data=payload, content_type="image/heic", original_name="synthetic.heic", capture_source="test")
    original, mime, _ = service.content_file(row["id"])
    assert original.read_bytes() == payload and mime == "image/heic"
    preview, _, _ = service.preview_file(row["id"])
    with Image.open(preview) as decoded:
        assert decoded.size == (30, 20)


@pytest.mark.asyncio
async def test_each_image_failure_visible_and_replay_does_not_duplicate(tmp_path):
    db, service, _, message_id = build_service(tmp_path)
    async def fetch(media):
        if media.media_index == 1:
            raise TimeoutError()
        return ChannelMediaContent(original_jpeg(), "image/jpeg", "synthetic.jpg")
    result = await service.capture_message(event(count=3), message_id, fetch, capture_source="live")
    assert result == {"stored": 2, "failed": 1}
    assert service.status()["stored_count"] == 2
    assert service.status()["failed_count"] == 1
    assert [row["media_index"] for row in service.attention_items()] == [1]
    await service.capture_message(event(count=3), message_id, fetch, capture_source="live")
    with db.session() as session:
        assert len(list(session.scalars(select(CustomerImageCaptureJob)))) == 3
        assert len(list(session.scalars(select(CustomerImageArchive)))) == 3


@pytest.mark.asyncio
async def test_queue_is_in_message_transaction_and_survives_restart(tmp_path):
    db, service, _, _ = build_service(tmp_path)
    incoming = event(suffix="durable", channel="wechat")
    with db.session() as session:
        result = ingest_message(session, incoming, [], None, on_media_persist=service.persist_message_jobs)
        job = session.scalar(select(CustomerImageCaptureJob))
        assert job is not None and "https:" not in job.encrypted_media
        assert session.get(Message, result.message_id)
    restarted = CustomerImageArchiveService(db, tmp_path)
    async def fetch(media):
        assert media.locator.endswith("/0.jpg")
        return ChannelMediaContent(original_jpeg(), "image/jpeg")
    restarted.media_fetchers = {"wechat": fetch}
    await restarted.drain_pending()
    with db.session() as session:
        job = session.scalar(select(CustomerImageCaptureJob))
        assert job.status == "completed" and job.encrypted_media == ""


@pytest.mark.asyncio
async def test_lost_key_is_reported_and_invalid_key_does_not_drop_new_text(tmp_path):
    db, service, _, message_id = build_service(tmp_path)
    service.enqueue_message(event(), message_id, capture_source="live")
    key = service.temp_root.parent / "customer-image-key"
    key.unlink()
    restarted = CustomerImageArchiveService(db, tmp_path)
    async def no_remote(_):
        raise AssertionError("lost-key work must not make a remote request")
    restarted.media_fetchers = {"xianyu": no_remote}
    await restarted.drain_pending()
    assert restarted.attention_items()[0]["error_code"] == "media_key_unavailable"
    key.chmod(0o644)
    disabled = CustomerImageArchiveService(db, tmp_path)
    incoming = event(suffix="safe-text")
    incoming.content = "synthetic text with attached image"
    with db.session() as session:
        result = ingest_message(session, incoming, [], None, on_media_persist=disabled.persist_message_jobs)
        assert session.get(Message, result.message_id).content == incoming.content
        row = session.scalar(select(CustomerImageArchive).where(CustomerImageArchive.message_id == result.message_id))
        assert row.error_code == "media_key_unavailable"


@pytest.mark.asyncio
async def test_context_hydration_uses_same_durable_image_queue(tmp_path):
    from backend.app.services.repository import hydrate_conversation_context
    db, service, _, _ = build_service(tmp_path)
    history = event(suffix="old")
    history.conversation_id = "conversation-one"
    with db.session() as session:
        assert hydrate_conversation_context(session, event(), [history], None, on_media_persist=service.persist_message_jobs)
        message = session.scalar(select(Message).where(Message.platform_message_id == "platform-image-old"))
        assert message is not None
        row = session.scalar(select(CustomerImageArchive).where(CustomerImageArchive.message_id == message.id))
        assert row and session.get(CustomerImageCaptureJob, row.id)


@pytest.mark.asyncio
async def test_hydration_can_supply_late_reference_for_current_image(tmp_path):
    from backend.app.services.repository import hydrate_conversation_context
    db, service, _, message_id = build_service(tmp_path)
    missing = event()
    missing.media = ()
    assert await service.capture_message(missing, message_id, None, capture_source="live") == {"stored": 0, "failed": 1}
    with db.session() as session:
        hydrate_conversation_context(session, missing, [event()], None, on_media_persist=service.persist_message_jobs)
    async def fetch(_):
        return ChannelMediaContent(original_jpeg(), "image/jpeg")
    service.media_fetchers = {"xianyu": fetch}
    await service.drain_pending()
    assert service.status()["stored_count"] == 1
    assert service.status()["attention_count"] == 0


@pytest.mark.asyncio
async def test_lease_timeout_recovers_and_retry_budget_is_bounded(tmp_path):
    db, service, _, message_id = build_service(tmp_path)
    service.enqueue_message(event(), message_id, capture_source="live")
    calls = 0
    async def fetch(_):
        nonlocal calls
        calls += 1
        raise TimeoutError()
    service.media_fetchers = {"xianyu": fetch}
    with db.session() as session:
        job = session.scalar(select(CustomerImageCaptureJob))
        job.status, job.lease_until = "running", datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    for _ in range(5):
        with db.session() as session:
            job = session.scalar(select(CustomerImageCaptureJob))
            job.next_attempt_at = None
            session.commit()
        await service.drain_pending()
    assert calls == 3
    with db.session() as session:
        assert session.scalar(select(CustomerImageCaptureJob)).status == "failed"


@pytest.mark.asyncio
async def test_access_verification_stops_remaining_remote_requests(tmp_path):
    db, service, _, message_id = build_service(tmp_path)
    calls = []
    async def fetch(media):
        calls.append(media.media_index)
        raise AdapterAccessVerificationError("synthetic verification")
    assert await service.capture_message(event(count=3), message_id, fetch, capture_source="live") == {"stored": 0, "failed": 3}
    await service.drain_pending()
    assert calls == [0]
    with db.session() as session:
        assert {job.status for job in session.scalars(select(CustomerImageCaptureJob))} == {"blocked"}


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt_after_original_commit", [False, True])
async def test_manual_success_reopens_live_channel_without_retrying_unselected_history(tmp_path, interrupt_after_original_commit):
    db, service, _, first_id = build_service(tmp_path)
    _, unselected_id = create_image_message(db, suffix="unselected")
    _, new_id = create_image_message(db, suffix="new-live")
    calls = []
    async def verification(media):
        calls.append("challenge")
        raise AdapterAccessVerificationError("synthetic challenge")
    service.enqueue_message(event(suffix="unselected"), unselected_id, capture_source="live")
    await service.capture_message(event(), first_id, verification, capture_source="live")
    async def recovered(media):
        calls.append("success")
        return ChannelMediaContent(original_jpeg(), "image/jpeg")
    if interrupt_after_original_commit:
        service.enqueue_message(event(), first_id, capture_source="history_import")
        with db.session() as session:
            row = session.scalar(select(CustomerImageArchive).where(CustomerImageArchive.message_id == first_id))
            job = session.get(CustomerImageCaptureJob, row.id)
            job.status = "running"
            job.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        content = await recovered(event().media[0])
        service.store_original(first_id, 0, data=content.data, content_type=content.mime_type, original_name=None, capture_source="history_import")
    else:
        assert await service.capture_message(event(), first_id, recovered, capture_source="history_import") == {"stored": 1, "failed": 0}
    # Recovery is durable, but does not turn the unselected old job into work.
    restarted = CustomerImageArchiveService(db, tmp_path)
    await restarted.drain_pending()
    await restarted.capture_message(event(suffix="new-live"), new_id, recovered, capture_source="live")
    await restarted.capture_message(event(suffix="unselected"), unselected_id, recovered, capture_source="live")
    await restarted.drain_pending()
    with db.session() as session:
        unselected = session.scalar(select(CustomerImageArchive).where(CustomerImageArchive.message_id == unselected_id))
        job = session.get(CustomerImageCaptureJob, unselected.id)
        new_image = session.scalar(select(CustomerImageArchive).where(CustomerImageArchive.message_id == new_id))
        assert job.status == "failed" and job.attempt_count == 0
        assert unselected.capture_status == "failed"
        assert new_image.capture_status == "stored"
    assert calls == ["challenge", "success", "success"]


@pytest.mark.asyncio
async def test_history_import_does_not_rearm_each_message_after_verification(tmp_path):
    from backend.tests.test_conversation_history_import import build_service as build_history, history_message
    service, db, adapter, _ = build_history(tmp_path, [history_message(f"history-image-{i}", message_type="image", with_media=True) for i in range(3)])
    calls = 0
    async def fetch(_):
        nonlocal calls
        calls += 1
        raise AdapterAccessVerificationError("synthetic challenge")
    adapter.fetch_media = fetch
    preview = await service.preview(external_conversation_id="conversation-history")
    result = await service.commit(request_id="history-block-scope", preview_token=preview["token"])
    assert calls == 1
    assert result["image_failed_count"] == 3
    with db.session() as session:
        assert len(list(session.scalars(select(Message)))) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content_type", [(401, "application/json"), (403, "text/plain"), (429, "text/plain"), (200, "text/html")])
async def test_real_adapter_classifies_access_failures_before_image_decode(status, content_type):
    from backend.app.adapters.xianyu import XianyuAdapter
    from backend.app.adapters import LoginExpiredError
    from backend.app.config import Settings
    from pydantic import SecretStr
    adapter = XianyuAdapter(Settings(_env_file=None, xianyu_cookie=SecretStr("unb=synthetic; _m_h5_tk=synthetic_suffix")))
    await adapter.http.aclose()
    adapter.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, content=b"synthetic challenge", headers={"content-type": content_type})))
    try:
        with pytest.raises((AdapterAccessVerificationError, LoginExpiredError)):
            await adapter.fetch_media(ChannelMedia("remote_url", "https://img.alicdn.com/synthetic.jpg"))
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_media_replay_cannot_switch_message_conversation(tmp_path):
    _, service, _, message_id = build_service(tmp_path)
    incoming = event()
    incoming.conversation_id = "different-customer"
    with pytest.raises(CustomerImageError) as error:
        service.enqueue_message(incoming, message_id, capture_source="live")
    assert error.value.code == "image_source_identity_conflict"


@pytest.mark.asyncio
async def test_remote_download_stops_at_byte_limit():
    from backend.app.adapters.xianyu import XianyuAdapter
    from backend.app.channels.base import ChannelMediaTooLargeError
    from backend.app.config import Settings
    from pydantic import SecretStr
    class Body(httpx.AsyncByteStream):
        count = 0
        closed = False
        async def __aiter__(self):
            for _ in range(20):
                self.count += 1
                yield b"x" * (2 * 1024 * 1024)
        async def aclose(self):
            self.closed = True
    body = Body()
    adapter = XianyuAdapter(Settings(_env_file=None, xianyu_cookie=SecretStr("unb=synthetic; _m_h5_tk=synthetic_suffix")))
    await adapter.http.aclose()
    adapter.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=body, headers={"content-type": "image/jpeg"})))
    try:
        with pytest.raises(ChannelMediaTooLargeError):
            await adapter.fetch_media(ChannelMedia("remote_url", "https://img.alicdn.com/synthetic.jpg"))
        assert body.count == 13 and body.closed
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_deleted_original_is_not_restored_by_replay_or_direct_write(tmp_path):
    _, service, _, message_id = build_service(tmp_path)
    async def fetch(_):
        return ChannelMediaContent(original_jpeg(), "image/jpeg")
    await service.capture_message(event(), message_id, fetch, capture_source="live")
    image_id = service.list_images()["items"][0]["id"]
    service.delete_local_copy(image_id)
    await service.capture_message(event(), message_id, fetch, capture_source="live")
    assert service.list_images()["items"] == []
    with pytest.raises(CustomerImageError, match="已删除"):
        service.store_original(message_id, 0, data=original_jpeg(), content_type="image/jpeg", original_name=None, capture_source="test")
    assert not list(service.root.rglob("*.jpg"))


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "AVIF"])
def test_real_codec_and_separate_preview_preserve_original_hash(tmp_path, image_format):
    _, service, _, message_id = build_service(tmp_path)
    output = BytesIO()
    Image.new("RGB", (34, 28), "blue").save(output, format=image_format)
    payload = output.getvalue()
    view = service.store_original(message_id, 0, data=payload, content_type=None, original_name=f"test.{image_format.lower()}", capture_source="test")
    original, _, _ = service.content_file(view["id"])
    preview, mime, _ = service.preview_file(view["id"])
    assert original.read_bytes() == payload
    assert preview.parent == service.preview_root and service.root not in preview.parents
    assert mime == "image/png"
    with Image.open(preview) as image:
        image.load()
        assert image.size == (34, 28)


@pytest.mark.asyncio
async def test_search_is_global_and_preview_has_real_bytes(tmp_path):
    from types import SimpleNamespace
    db, service, _, first = build_service(tmp_path)
    _, second = create_image_message(db, suffix="needle")
    for message_id, name in [(first, "one.jpg"), (second, "needle.jpg")]:
        service.store_original(message_id, 0, data=original_jpeg(), content_type="image/jpeg", original_name=name, capture_source="test")
    app = FastAPI()
    app.state.runtime = SimpleNamespace(customer_images=service)
    app.include_router(customer_image_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8877") as client:
        response = await client.get("/api/customer-images", params={"search": "needle", "limit": 1})
        assert response.json()["total"] == 1
        image = response.json()["items"][0]
        preview = await client.get(image["preview_url"])
        assert preview.headers["content-type"] == "image/png"
        with Image.open(BytesIO(preview.content)) as decoded:
            decoded.load()
            assert decoded.size == (96, 64)


@pytest.mark.asyncio
async def test_capture_emits_committed_status_without_private_payload(tmp_path):
    _, service, _, message_id = build_service(tmp_path)
    hub = EventHub()
    subscription = hub.subscribe()
    service.event_hub = hub
    async def fetch(_):
        return ChannelMediaContent(original_jpeg(), "image/jpeg")
    await service.capture_message(event(), message_id, fetch, capture_source="live")
    notice = await asyncio.wait_for(subscription.queue.get(), timeout=1)
    assert notice["type"] == "customer_image_updated" and notice["status"] == "stored"
    assert not ({"locator", "content", "customer_name"} & notice.keys())
    service.content_file(notice["image_id"])
