from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import httpx
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..adapters import (
    AdapterAccessVerificationError,
    AdapterDisconnectedError,
    AdapterError,
    LoginExpiredError,
)
from ..channels.base import ChannelMedia, ChannelMediaContent, ChannelMessage, ChannelMediaTooLargeError
from ..database import Database
from ..customer_time import utc_from_storage
from ..models import (
    Conversation,
    CustomerImageArchive,
    CustomerImageHistoryRecoveryRun,
    Message,
    Item,
    utcnow,
)
from ..customer_media_models import CustomerImageCaptureJob
from .image_codec import validate_image, compatible_preview, ImageCodecError


MediaFetcher = Callable[[ChannelMedia], Awaitable[ChannelMediaContent]]
SHANGHAI = ZoneInfo("Asia/Shanghai")


class CustomerImageError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class CustomerImageArchiveService:
    """Store customer-sent image bytes without transcoding or content analysis."""

    MAX_IMAGE_BYTES = 25 * 1024 * 1024
    MAX_HISTORY_CONVERSATIONS = 50
    ROOT_RELATIVE = Path("data/customer-images")
    TEMP_RELATIVE = Path("data/private/customer-image-tmp")
    PREVIEW_RELATIVE = Path("data/customer-image-previews")
    MAX_ATTEMPTS = 3
    FETCH_TIMEOUT_SECONDS = 20

    def __init__(self, database: Database, project_root: Path) -> None:
        self.database = database
        self.project_root = project_root.resolve()
        self.root = (self.project_root / self.ROOT_RELATIVE).resolve()
        self.temp_root = (self.project_root / self.TEMP_RELATIVE).resolve()
        self._history_recovery_lock = asyncio.Lock()
        self._capture_lock = asyncio.Lock()
        self._worker: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.media_fetchers: dict[str, MediaFetcher] = {}
        self.event_hub = None
        self.preview_root = (self.project_root / self.PREVIEW_RELATIVE).resolve()
        self._ensure_private_dir(self.root)
        self._ensure_private_dir(self.temp_root)
        self._ensure_private_dir(self.preview_root)
        key_path = self.temp_root.parent / "customer-image-key"
        self._cipher: Fernet | None = None
        try:
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(Fernet.generate_key())
                    handle.flush()
                    os.fsync(handle.fileno())
            if not key_path.is_symlink() and not key_path.stat().st_mode & 0o077:
                self._cipher = Fernet(key_path.read_bytes())
        except (OSError, ValueError):
            # Archive configuration failure is reported per image; text ingestion
            # remains available and no plaintext reference is persisted.
            pass

    @staticmethod
    def _ensure_private_dir(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)

    @staticmethod
    def _safe_name(value: str | None, suffix: str) -> str:
        raw = (value or "").replace("\\", "/")
        name = Path(raw).name.strip().replace("\x00", "")
        if not name:
            return f"customer-image{suffix}"
        name = re.sub(r"[\r\n\t]", " ", name)[:220].strip()
        return name or f"customer-image{suffix}"

    @classmethod
    def _detect_image(
        cls,
        data: bytes,
        content_type: str | None,
    ) -> tuple[str, str, int, int]:
        try:
            return validate_image(data, content_type)
        except ImageCodecError as exc:
            raise CustomerImageError(exc.code, str(exc)) from exc

    def persist_message_jobs(self, session: Session, message: Message, event: ChannelMessage, *, capture_source: str = "live") -> None:
        """Add media intent to the SAME transaction as its message; never download here."""
        if event.direction != "inbound" or not (event.media or event.message_type == "image"):
            return
        if message.channel != event.channel or message.platform_message_id != str(event.platform_message_id or event.external_id) or message.conversation.external_id != event.conversation_id:
            raise CustomerImageError("image_source_identity_conflict", "图片消息身份与原会话不一致", status_code=409)
        media_rows = event.media or (ChannelMedia("unavailable", ""),)
        use_sequence = len({media.media_index for media in media_rows}) != len(media_rows)
        for index, media in enumerate(media_rows):
            media_index = index if use_sequence else media.media_index
            row = session.scalar(select(CustomerImageArchive).where(CustomerImageArchive.message_id == message.id, CustomerImageArchive.media_index == media_index))
            if row is None:
                row = CustomerImageArchive(id=f"cimg-{uuid4()}", message_id=message.id, conversation_id=message.conversation_id, channel=message.channel, platform_message_id=message.platform_message_id, media_index=media_index, capture_status="pending", capture_source=capture_source, received_at=message.received_at)
                session.add(row)
                session.flush()
            if row.deleted_at is not None or row.capture_status in {"stored", "deleted"}:
                continue
            job = session.get(CustomerImageCaptureJob, row.id)
            payload = json.dumps({"locator_type": media.locator_type, "locator": media.locator, "media_index": media_index, "mime_type": media.mime_type, "original_name": media.original_name}, separators=(",", ":")).encode()
            encrypted = self._cipher.encrypt(payload).decode() if self._cipher else ""
            if job is None:
                source_item = session.scalar(select(Item).where(Item.external_id == event.item_id)) if event.item_id else None
                job = CustomerImageCaptureJob(archive_id=row.id, encrypted_media=encrypted, source_item_id=source_item.id if source_item else None, source_item_external_id=event.item_id)
                session.add(job)
            elif job.status not in {"completed", "deleted", "blocked"}:
                # Replays may refresh expired signed references; they do not reset retry budgets.
                job.encrypted_media = encrypted
                if job.status == "failed" and job.last_error in {"source_unavailable", "fetcher_unavailable", "media_key_unavailable"} and media.locator and self._cipher:
                    job.status, job.last_error, job.attempt_count = "pending", None, 0
                    job.next_attempt_at, job.lease_until = None, None
                    row.capture_status, row.error_code = "pending", None
            if capture_source == "history_import" and job.status not in {"completed", "deleted", "running"}:
                # Only the explicitly previewed/confirmed history scope may retry
                # exhausted or protected work; ordinary platform replays never do.
                job.status, job.attempt_count, job.last_error = "pending", 0, "manual_resume"
                job.next_attempt_at, job.lease_until = None, None
                job.encrypted_media = encrypted
                row.capture_status, row.error_code = "pending", None
            if self._cipher is None:
                row.capture_status, row.error_code = "failed", "media_key_unavailable"
                job.status, job.last_error = "failed", "media_key_unavailable"

    def enqueue_message(self, event: ChannelMessage, message_id: int, *, capture_source: str) -> None:
        with self.database.session() as session:
            message = session.get(Message, message_id)
            if message is not None:
                self.persist_message_jobs(session, message, event, capture_source=capture_source)
                session.commit()
        self.notify_committed(message_id)

    def notify_committed(self, message_id: int) -> None:
        self._wake.set()
        with self.database.session() as session:
            failed_ids = list(session.scalars(select(CustomerImageArchive.id).where(CustomerImageArchive.message_id == message_id, CustomerImageArchive.error_code == "media_key_unavailable")))
        for archive_id in failed_ids:
            self._publish_image(archive_id)

    def start(self, media_fetchers: dict[str, MediaFetcher], event_hub=None) -> None:
        self.media_fetchers = media_fetchers
        self.event_hub = event_hub
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="customer-image-capture")

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    async def _run(self) -> None:
        while True:
            try:
                await self.drain_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Persisted leases recover after interruption; no private error payload escapes.
                pass
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=2)
            except TimeoutError:
                pass

    def _publish_image(self, archive_id: str) -> None:
        if self.event_hub is None:
            return
        with self.database.session() as session:
            row = session.get(CustomerImageArchive, archive_id)
            if row:
                self.event_hub.publish_nowait({"type": "customer_image_updated", "conversation_id": row.conversation_id, "message_id": row.message_id, "image_id": row.id, "status": row.capture_status, "error_code": row.error_code})

    async def drain_pending(self, *, message_id: int | None = None, limit: int = 50) -> None:
        # A single consumer is deliberate: verification on one image stops the channel
        # before another request can start; no parallel in-flight requests escape it.
        async with self._capture_lock:
            now = utcnow()
            with self.database.session() as session:
                conditions = [CustomerImageCaptureJob.status.in_(["pending", "retry", "running"]), or_(CustomerImageCaptureJob.next_attempt_at.is_(None), CustomerImageCaptureJob.next_attempt_at <= now), or_(CustomerImageCaptureJob.lease_until.is_(None), CustomerImageCaptureJob.lease_until <= now)]
                if message_id is not None:
                    conditions.append(CustomerImageArchive.message_id == message_id)
                ids = list(session.scalars(select(CustomerImageCaptureJob.archive_id).join(CustomerImageArchive, CustomerImageArchive.id == CustomerImageCaptureJob.archive_id).where(*conditions).order_by(CustomerImageArchive.created_at, CustomerImageArchive.media_index).limit(limit)))
            for archive_id in ids:
                await self._capture_job(archive_id)

    @staticmethod
    def _release_channel_protection(session: Session, channel: str) -> None:
        # A successful explicitly confirmed image read is evidence of restored
        # access. Retire the circuit marker, not the failed work: unselected
        # historical images stay failed until the user confirms their scope.
        jobs = session.scalars(select(CustomerImageCaptureJob).join(CustomerImageArchive, CustomerImageArchive.id == CustomerImageCaptureJob.archive_id).where(CustomerImageArchive.channel == channel, CustomerImageCaptureJob.status == "blocked"))
        for job in jobs:
            job.status = "failed"
            job.next_attempt_at, job.lease_until = None, None

    async def _capture_job(self, archive_id: str) -> None:
        additional_events: list[str] = []
        with self.database.session() as session:
            job = session.get(CustomerImageCaptureJob, archive_id)
            row = session.get(CustomerImageArchive, archive_id)
            if job is None or row is None or job.status not in {"pending", "retry", "running"}:
                return
            if row.deleted_at is not None or row.capture_status == "deleted":
                job.status, job.encrypted_media = "deleted", ""
                session.commit()
                return
            if row.capture_status == "stored":
                if job.last_error == "manual_resume":
                    self._release_channel_protection(session, row.channel)
                job.status, job.encrypted_media, job.lease_until = "completed", "", None
                session.commit()
                return
            blocked = session.scalar(select(CustomerImageCaptureJob.archive_id).join(CustomerImageArchive, CustomerImageArchive.id == CustomerImageCaptureJob.archive_id).where(CustomerImageArchive.channel == row.channel, CustomerImageCaptureJob.status == "blocked").limit(1))
            if blocked and job.last_error != "manual_resume":
                job.status, job.last_error = "blocked", "channel_protection_skipped"
                row.capture_status, row.error_code = "failed", "channel_protection_skipped"
                session.commit()
                self._publish_image(archive_id)
                return
            if job.attempt_count >= self.MAX_ATTEMPTS:
                job.status, job.lease_until = "failed", None
                row.capture_status, row.error_code = "failed", "capture_attempts_exhausted"
                session.commit()
                self._publish_image(archive_id)
                return
            job.status, job.attempt_count = "running", job.attempt_count + 1
            job.lease_until = utcnow() + timedelta(seconds=self.FETCH_TIMEOUT_SECONDS + 10)
            channel, message_id, media_index, capture_source = row.channel, row.message_id, row.media_index, row.capture_source
            manual_resume = job.last_error == "manual_resume"
            encrypted = job.encrypted_media
            session.commit()
        code = None
        retry = False
        blocked = False
        try:
            if self._cipher is None:
                raise CustomerImageError("media_key_unavailable", "本地图片引用密钥不可用")
            media = ChannelMedia(**json.loads(self._cipher.decrypt(encrypted.encode())))
            fetcher = self.media_fetchers.get(channel)
            if not media.locator:
                raise CustomerImageError("source_unavailable", "平台图片引用不可用")
            if fetcher is None:
                raise CustomerImageError("fetcher_unavailable", "渠道图片下载器不可用")
            content = await asyncio.wait_for(fetcher(media), timeout=self.FETCH_TIMEOUT_SECONDS)
            self.store_original(message_id, media_index, data=content.data, content_type=content.mime_type or media.mime_type, original_name=content.original_name or media.original_name, capture_source=capture_source)
        except asyncio.CancelledError:
            with self.database.session() as session:
                job = session.get(CustomerImageCaptureJob, archive_id)
                if job:
                    job.status, job.lease_until = "retry", None
                    session.commit()
            raise
        except LoginExpiredError:
            code, blocked = "channel_login_required", True
        except AdapterAccessVerificationError:
            code, blocked = "channel_verification_required", True
        except AdapterDisconnectedError:
            code, blocked = "channel_disconnected", True
        except TimeoutError:
            code, retry = "image_download_timeout", True
        except httpx.TimeoutException:
            code, retry = "image_download_timeout", True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403, 429}:
                code, blocked = "channel_access_required", True
            else:
                code = "image_source_unavailable"
        except CustomerImageError as exc:
            code = exc.code
        except ChannelMediaTooLargeError:
            code = "image_too_large"
        except InvalidToken:
            code = "media_key_unavailable"
        except (ValueError, TypeError):
            code = "media_reference_invalid"
        except AdapterError:
            code = "image_source_unavailable"
        except Exception as exc:
            if getattr(exc, "code", None) in {40014, 42001, 42007, 42009, 40001, 45009}:
                code, blocked = "channel_access_required", True
            else:
                code, retry = "remote_fetch_failed", True
        with self.database.session() as session:
            job = session.get(CustomerImageCaptureJob, archive_id)
            row = session.get(CustomerImageArchive, archive_id)
            if job is None or row is None:
                return
            job.lease_until = None
            if row.deleted_at is not None:
                job.status, job.encrypted_media = "deleted", ""
            elif code:
                row.capture_status, row.error_code = "failed", code
                job.status = "blocked" if blocked else "retry" if retry and job.attempt_count < self.MAX_ATTEMPTS else "failed"
                job.last_error = code
                job.next_attempt_at = utcnow() + timedelta(seconds=5 * 2 ** job.attempt_count) if job.status == "retry" else None
            else:
                if manual_resume:
                    self._release_channel_protection(session, channel)
                job.status, job.encrypted_media, job.last_error = "completed", "", None
            if blocked:
                pending = list(session.scalars(select(CustomerImageCaptureJob).join(CustomerImageArchive, CustomerImageArchive.id == CustomerImageCaptureJob.archive_id).where(CustomerImageArchive.channel == channel, CustomerImageCaptureJob.status.in_(["pending", "retry"]))))
                for other in pending:
                    other.status, other.last_error = "blocked", code
                    other_row = session.get(CustomerImageArchive, other.archive_id)
                    if other_row and other_row.deleted_at is None:
                        other_row.capture_status, other_row.error_code = "failed", "channel_protection_skipped"
                        additional_events.append(other_row.id)
            session.commit()
        self._publish_image(archive_id)
        for image_id in additional_events:
            self._publish_image(image_id)

    def _archive_path(self, received_at: datetime, digest: str, suffix: str) -> Path:
        aware = received_at
        if aware.tzinfo is None:
            aware = aware.replace(tzinfo=timezone.utc)
        local = aware.astimezone(SHANGHAI)
        directory = self.root / f"{local.year:04d}" / f"{local.month:02d}"
        self._ensure_private_dir(directory)
        return directory / f"{digest}{suffix}"

    def _resolved_storage_file(self, storage_path: str) -> Path:
        if not storage_path:
            raise CustomerImageError("image_not_stored", "原图尚未保存", status_code=409)
        candidate = (self.project_root / storage_path).resolve()
        if self.root not in candidate.parents:
            raise CustomerImageError("image_path_invalid", "原图存储路径无效", status_code=409)
        return candidate

    def _write_original(self, target: Path, data: bytes, digest: str) -> None:
        if target.is_file():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise CustomerImageError("image_hash_conflict", "本地原图校验冲突", status_code=409)
            target.chmod(0o600)
            return

        self._ensure_private_dir(self.temp_root)
        fd, temporary_name = tempfile.mkstemp(
            prefix="customer-image-",
            suffix=".part",
            dir=self.temp_root,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise CustomerImageError("image_hash_mismatch", "原图写入校验失败", status_code=500)
            os.replace(temporary, target)
            target.chmod(0o600)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                target.unlink(missing_ok=True)
                raise CustomerImageError("image_hash_mismatch", "原图落盘校验失败", status_code=500)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _is_image_message(message: Message) -> bool:
        return (
            message.direction == "inbound"
            and (message.message_type == "image" or message.content.strip() == "[图片]")
        )

    def _ensure_row(
        self,
        message_id: int,
        media_index: int,
        *,
        capture_source: str,
    ) -> CustomerImageArchive:
        with self.database.session() as session:
            message = session.get(Message, message_id)
            if not message or message.direction != "inbound":
                raise CustomerImageError("image_message_not_found", "没有找到对应的客户图片消息", status_code=404)
            row = session.scalar(
                select(CustomerImageArchive).where(
                    CustomerImageArchive.message_id == message_id,
                    CustomerImageArchive.media_index == media_index,
                )
            )
            if row:
                return row
            if not self._is_image_message(message):
                raise CustomerImageError("image_message_not_found", "没有找到对应的客户图片消息", status_code=404)
            row = CustomerImageArchive(
                id=f"cimg-{uuid4()}",
                conversation_id=message.conversation_id,
                message_id=message.id,
                channel=message.channel,
                platform_message_id=message.platform_message_id,
                media_index=media_index,
                capture_status="pending",
                capture_source=capture_source,
                received_at=message.received_at,
            )
            session.add(row)
            session.commit()
            return row

    def store_original(
        self,
        message_id: int,
        media_index: int,
        *,
        data: bytes,
        content_type: str | None,
        original_name: str | None,
        capture_source: str,
    ) -> dict[str, Any]:
        row = self._ensure_row(message_id, media_index, capture_source=capture_source)
        if row.deleted_at is not None or row.capture_status == "deleted":
            raise CustomerImageError("image_deleted", "用户已删除该本地图片，自动归档不会恢复", status_code=409)
        if row.capture_status == "stored" and row.deleted_at is None:
            with self.database.session() as session:
                current = session.get(CustomerImageArchive, row.id)
                if not current:
                    raise CustomerImageError("image_archive_missing", "原图记录不存在", status_code=404)
                return self._view(current, current.conversation.customer_name)

        mime, suffix, width, height = self._detect_image(data, content_type)
        digest = hashlib.sha256(data).hexdigest()
        target = self._archive_path(row.received_at, digest, suffix)
        self._write_original(target, data, digest)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise CustomerImageError("image_hash_mismatch", "原图完整性校验失败", status_code=500)

        with self.database.session() as session:
            current = session.get(CustomerImageArchive, row.id)
            if not current:
                raise CustomerImageError("image_archive_missing", "原图记录不存在", status_code=404)
            if current.deleted_at is not None:
                raise CustomerImageError("image_deleted", "用户已删除该本地图片", status_code=409)
            current.capture_status = "stored"
            current.capture_source = capture_source
            current.mime_type = mime
            current.original_name = self._safe_name(original_name, suffix)
            current.storage_path = target.relative_to(self.project_root).as_posix()
            current.sha256 = digest
            current.file_size = len(data)
            current.width = width
            current.height = height
            current.integrity_verified = True
            current.error_code = None
            current.captured_at = utcnow()
            session.commit()
            return self._view(current, current.conversation.customer_name)

    async def capture_message(
        self,
        event: ChannelMessage,
        message_id: int,
        fetcher: MediaFetcher | None,
        *,
        capture_source: str,
        already_enqueued: bool = False,
    ) -> dict[str, int]:
        if event.direction != "inbound" or not (event.media or event.message_type == "image"):
            return {"stored": 0, "failed": 0}
        if not already_enqueued:
            self.enqueue_message(event, message_id, capture_source=capture_source)
        if fetcher is not None:
            self.media_fetchers[event.channel] = fetcher
        await self.drain_pending(message_id=message_id)
        with self.database.session() as session:
            rows = list(session.scalars(select(CustomerImageArchive).where(CustomerImageArchive.message_id == message_id)))
            return {"stored": sum(row.capture_status == "stored" and row.deleted_at is None for row in rows), "failed": sum(row.capture_status in {"failed", "pending"} and row.deleted_at is None for row in rows)}

    @staticmethod
    def _view(row: CustomerImageArchive, customer_name: str) -> dict[str, Any]:
        return {
            "id": row.id,
            "archive_id": row.id,
            "media_index": row.media_index,
            "status": row.capture_status,
            "capture_status": row.capture_status,
            "error_code": row.error_code,
            "conversation_id": row.conversation_id,
            "message_id": row.message_id,
            "channel": row.channel,
            "customer_name": customer_name,
            "received_at": utc_from_storage(row.received_at),
            "captured_at": utc_from_storage(row.captured_at),
            "mime_type": row.mime_type,
            "original_name": row.original_name,
            "file_size": row.file_size,
            "width": row.width,
            "height": row.height,
            "integrity_verified": row.integrity_verified,
            "content_url": f"/api/customer-images/{row.id}/content",
            "download_url": f"/api/customer-images/{row.id}/content?download=true",
            "preview_url": f"/api/customer-images/{row.id}/preview" if row.capture_status == "stored" else None,
        }

    @staticmethod
    def _parse_date_bound(value: str | None, *, end: bool) -> datetime | None:
        if not value:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise CustomerImageError("date_invalid", "日期筛选格式无效") from exc
        local = datetime.combine(parsed, time.max if end else time.min, tzinfo=SHANGHAI)
        return local.astimezone(timezone.utc)

    def list_images(
        self,
        *,
        channel: str | None = None,
        conversation_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        search: str | None = None,
        item_id: int | None = None,
        conversation_ids: list[int] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        start = self._parse_date_bound(date_from, end=False)
        end = self._parse_date_bound(date_to, end=True)
        conditions = [
            CustomerImageArchive.deleted_at.is_(None),
        ]
        if channel and channel != "all":
            conditions.append(CustomerImageArchive.channel == channel)
        if conversation_id is not None:
            conditions.append(CustomerImageArchive.conversation_id == conversation_id)
        if conversation_ids is not None:
            conditions.append(CustomerImageArchive.conversation_id.in_(conversation_ids))
        if item_id is not None:
            conditions.append(Item.id == item_id)
        if search and search.strip():
            term = f"%{search.strip()[:200]}%"
            conditions.append(or_(Conversation.customer_name.ilike(term), CustomerImageArchive.original_name.ilike(term), Item.title.ilike(term)))
        if start:
            conditions.append(CustomerImageArchive.received_at >= start)
        if end:
            conditions.append(CustomerImageArchive.received_at <= end)

        bounded_limit = min(max(1, limit), 200)
        bounded_offset = max(0, offset)
        with self.database.session() as session:
            total = int(
                session.scalar(
                    select(func.count())
                    .select_from(CustomerImageArchive)
                    .join(Conversation, Conversation.id == CustomerImageArchive.conversation_id)
                    .outerjoin(CustomerImageCaptureJob, CustomerImageCaptureJob.archive_id == CustomerImageArchive.id)
                    .outerjoin(Item, Item.external_id == CustomerImageCaptureJob.source_item_external_id)
                    .where(*conditions)
                )
                or 0
            )
            rows = list(
                session.execute(
                    select(CustomerImageArchive, Conversation.customer_name, Item.id, Item.title)
                    .join(Conversation, Conversation.id == CustomerImageArchive.conversation_id)
                    .outerjoin(CustomerImageCaptureJob, CustomerImageCaptureJob.archive_id == CustomerImageArchive.id)
                    .outerjoin(Item, Item.external_id == CustomerImageCaptureJob.source_item_external_id)
                    .where(*conditions)
                    .order_by(CustomerImageArchive.received_at.desc(), CustomerImageArchive.id.desc())
                    .offset(bounded_offset)
                    .limit(bounded_limit)
                )
            )
            return {
                "items": [{**self._view(row, customer_name), "source_item_id": source_item_id, "source_item_title": title or "未知商品"} for row, customer_name, source_item_id, title in rows],
                "total": total,
                "has_more": bounded_offset + len(rows) < total,
            }

    def filters(self) -> dict[str, Any]:
        with self.database.session() as session:
            conversations = list(
                session.execute(
                    select(
                        Conversation.id,
                        Conversation.customer_name,
                        Conversation.channel,
                        func.count(CustomerImageArchive.id),
                    )
                    .join(CustomerImageArchive, CustomerImageArchive.conversation_id == Conversation.id)
                    .where(
                        CustomerImageArchive.deleted_at.is_(None),
                    )
                    .group_by(Conversation.id, Conversation.customer_name, Conversation.channel)
                    .order_by(Conversation.customer_name.asc())
                )
            )
            items = list(session.execute(select(Item.id, Item.title).join(CustomerImageCaptureJob, CustomerImageCaptureJob.source_item_external_id == Item.external_id).join(CustomerImageArchive, CustomerImageArchive.id == CustomerImageCaptureJob.archive_id).where(CustomerImageArchive.deleted_at.is_(None)).distinct().order_by(Item.title)))
        return {
            "channels": ["xianyu", "wechat"],
            "items": [{"id": item_id, "title": title} for item_id, title in items],
            "conversations": [
                {"id": row[0], "customer_name": row[1], "channel": row[2], "image_count": row[3]}
                for row in conversations
            ],
        }

    def _candidate_messages(self) -> list[Message]:
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(Message)
                    .where(
                        Message.direction == "inbound",
                        or_(Message.message_type == "image", Message.content == "[图片]", Message.id.in_(select(CustomerImageArchive.message_id))),
                    )
                    .order_by(Message.received_at.desc(), Message.id.desc())
                )
            )

    def status(self) -> dict[str, Any]:
        candidates = self._candidate_messages()
        candidate_ids = [message.id for message in candidates]
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(CustomerImageArchive).where(
                        CustomerImageArchive.message_id.in_(candidate_ids)
                    )
                )
            ) if candidate_ids else []
            last_captured_at = session.scalar(
                select(func.max(CustomerImageArchive.captured_at)).where(
                    CustomerImageArchive.capture_status == "stored",
                    CustomerImageArchive.deleted_at.is_(None),
                )
            )
        by_message: dict[int, list[CustomerImageArchive]] = {}
        for row in rows:
            by_message.setdefault(row.message_id, []).append(row)
        missing_messages = set(candidate_ids) - set(by_message)
        stored_count = sum(row.capture_status == "stored" and row.deleted_at is None for row in rows)
        failed_count = sum(row.capture_status == "failed" and row.deleted_at is None for row in rows)
        pending_count = sum(row.capture_status == "pending" and row.deleted_at is None for row in rows)
        attention = failed_count + pending_count + len(missing_messages)
        channel_counts = Counter(row.channel for row in rows if row.capture_status in {"failed", "pending"} and row.deleted_at is None)
        channel_counts.update(message.channel for message in candidates if message.id in missing_messages)
        return {
            "state": "healthy" if attention == 0 else "needs_attention",
            "stored_count": stored_count,
            "attention_count": attention,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "missing_count": len(missing_messages),
            "candidate_count": len(rows) + len(missing_messages),
            "channel_counts": dict(channel_counts),
            "last_captured_at": utc_from_storage(last_captured_at),
            "message": (
                "客户原图自动归档正常"
                if attention == 0
                else f"有 {attention} 条历史图片尚未取得原图，可在连接恢复后自动匹配"
            ),
        }

    def history_preview(self, listener_status: str = "unknown") -> dict[str, Any]:
        status = self.status()
        related_conversations = {
            item["conversation_id"]
            for item in self.attention_items()
            if item["channel"] == "xianyu"
        }
        connected = listener_status == "connected"
        return {
            "candidate_count": status["attention_count"],
            "channel_counts": status["channel_counts"],
            "related_conversation_count": len(related_conversations),
            "automatic": True,
            "connection_status": listener_status,
            "can_recover": connected and bool(related_conversations),
            "notice": (
                "连接恢复后，点击一次即可按相关会话自动匹配已有图片占位；"
                "不会发送消息、调用 AI 或处理图片内容。"
            ),
        }

    def attention_items(self) -> list[dict[str, Any]]:
        candidates = self._candidate_messages()
        if not candidates:
            return []
        message_ids = [message.id for message in candidates]
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(CustomerImageArchive).where(
                        CustomerImageArchive.message_id.in_(message_ids)
                    )
                )
            )
            names = {
                conversation_id: customer_name
                for conversation_id, customer_name in session.execute(
                    select(Conversation.id, Conversation.customer_name).where(
                        Conversation.id.in_({message.conversation_id for message in candidates})
                    )
                )
            }
        by_message: dict[int, list[CustomerImageArchive]] = {}
        for row in rows:
            by_message.setdefault(row.message_id, []).append(row)
        result = []
        for message in candidates:
            linked = by_message.get(message.id, [])
            if linked and all(row.capture_status in {"stored", "deleted"} for row in linked):
                continue
            failed = next((row for row in linked if row.capture_status == "failed"), None)
            pending = next((row for row in linked if row.capture_status == "pending"), None)
            if linked and failed is None and pending is None:
                # A deliberately deleted local copy is not an interrupted
                # capture and must not reappear as a recovery reminder.
                continue
            for image_row in [row for row in linked if row.capture_status in {"failed", "pending"}] or [None]:
                result.append(
                {
                    "image_id": image_row.id if image_row else None,
                    "media_index": image_row.media_index if image_row else 0,
                    "message_id": message.id,
                    "conversation_id": message.conversation_id,
                    "channel": message.channel,
                    "customer_name": names.get(message.conversation_id, "客户"),
                    "received_at": utc_from_storage(message.received_at),
                    "status": image_row.capture_status if image_row else "missing",
                    "error_code": (
                        image_row.error_code
                        if image_row and image_row.error_code
                        else "capture_interrupted" if pending else "source_unavailable"
                    ),
                }
            )
        return result[:200]

    async def recover_xianyu_history(
        self,
        request_id: str,
        adapter: Any,
        processor: Any,
    ) -> dict[str, Any]:
        async with self._history_recovery_lock:
            with self.database.session() as session:
                receipt = session.get(CustomerImageHistoryRecoveryRun, request_id)
                if receipt is not None and receipt.status == "completed":
                    try:
                        cached = json.loads(receipt.result_json)
                    except (TypeError, ValueError):
                        cached = {}
                    if isinstance(cached, dict):
                        return cached
                if receipt is None:
                    receipt = CustomerImageHistoryRecoveryRun(
                        request_id=request_id,
                        status="running",
                        result_json="{}",
                        started_at=utcnow(),
                        completed_at=None,
                        updated_at=utcnow(),
                    )
                    session.add(receipt)
                else:
                    receipt.status = "running"
                    receipt.updated_at = utcnow()
                session.commit()
            try:
                result = await self._recover_xianyu_history(adapter, processor)
            except Exception as exc:
                with self.database.session() as session:
                    receipt = session.get(CustomerImageHistoryRecoveryRun, request_id)
                    if receipt is not None:
                        receipt.status = "failed"
                        receipt.result_json = json.dumps(
                            {"error_code": type(exc).__name__},
                            ensure_ascii=False,
                        )
                        receipt.completed_at = utcnow()
                        receipt.updated_at = utcnow()
                        session.commit()
                raise
            stored_result = json.loads(
                json.dumps(
                    {**result, "idempotent": True},
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            )
            with self.database.session() as session:
                receipt = session.get(CustomerImageHistoryRecoveryRun, request_id)
                if receipt is None:
                    raise CustomerImageError(
                        "recovery_receipt_missing", "图片恢复回执写入失败", status_code=500
                    )
                receipt.status = "completed"
                receipt.result_json = json.dumps(
                    stored_result, ensure_ascii=False, sort_keys=True
                )
                receipt.completed_at = utcnow()
                receipt.updated_at = utcnow()
                session.commit()
            return stored_result

    async def _recover_xianyu_history(
        self,
        adapter: Any,
        processor: Any,
    ) -> dict[str, Any]:
        candidates = self._candidate_messages()
        status_before = self.status()
        if status_before["attention_count"] == 0:
            return {
                "conversation_count": 0,
                "checked_conversation_count": 0,
                "stored_count": 0,
                "unmatched_count": 0,
                "failed_count": 0,
                "failed_conversations": [],
                "stopped_early": False,
                "action_hint": "没有待恢复的客户图片",
                "status": status_before,
            }

        attention_ids: set[int] = set()
        target_keys: dict[int, set[str]] = {}
        with self.database.session() as session:
            for message in candidates:
                unfinished = session.scalar(
                    select(CustomerImageArchive.id).where(
                        CustomerImageArchive.message_id == message.id,
                        CustomerImageArchive.capture_status.in_(["pending", "failed"]),
                        CustomerImageArchive.deleted_at.is_(None),
                    )
                )
                has_rows = session.scalar(select(CustomerImageArchive.id).where(CustomerImageArchive.message_id == message.id).limit(1))
                if unfinished or not has_rows:
                    attention_ids.add(message.conversation_id)
                    keys = target_keys.setdefault(message.conversation_id, set())
                    if message.platform_message_id:
                        keys.add(message.platform_message_id)
            conversations = list(
                session.scalars(
                    select(Conversation)
                    .where(
                        Conversation.id.in_(attention_ids),
                        Conversation.channel == "xianyu",
                    )
                    .order_by(Conversation.last_message_at.desc())
                    .limit(self.MAX_HISTORY_CONVERSATIONS)
                )
            )

        stored_before = status_before["stored_count"]
        checked_conversations = 0
        failed_conversations: list[dict[str, Any]] = []
        stopped_early = False
        for conversation in conversations:
            try:
                checked_conversations += 1
                events = await adapter.fetch_recent_messages(conversation.external_id, 200)
                allowed_keys = target_keys.get(conversation.id, set())
                for event in events:
                    if (
                        event.direction == "inbound"
                        and event.message_type == "image"
                        and event.platform_message_id in allowed_keys
                    ):
                        await processor.process(event, source="image_history")
            except LoginExpiredError:
                failed_conversations.append(
                    {
                        "conversation_id": conversation.id,
                        "customer_name": conversation.customer_name,
                        "error_code": "xianyu_login_required",
                    }
                )
                stopped_early = True
                break
            except AdapterAccessVerificationError:
                failed_conversations.append(
                    {
                        "conversation_id": conversation.id,
                        "customer_name": conversation.customer_name,
                        "error_code": "xianyu_verification_required",
                    }
                )
                stopped_early = True
                break
            except AdapterDisconnectedError:
                failed_conversations.append(
                    {
                        "conversation_id": conversation.id,
                        "customer_name": conversation.customer_name,
                        "error_code": "xianyu_disconnected",
                    }
                )
                stopped_early = True
                break
            except (AdapterError, TimeoutError, ConnectionError):
                failed_conversations.append(
                    {
                        "conversation_id": conversation.id,
                        "customer_name": conversation.customer_name,
                        "error_code": "xianyu_connection_failed",
                    }
                )
                stopped_early = True
                break
            except Exception:
                failed_conversations.append(
                    {
                        "conversation_id": conversation.id,
                        "customer_name": conversation.customer_name,
                        "error_code": "history_fetch_failed",
                    }
                )
        status_after = self.status()
        unmatched_count = int(status_after["attention_count"])
        action_hint = (
            "请先在设置中心恢复闲鱼连接，再重新点击自动恢复"
            if stopped_early
            else (
                f"仍有 {unmatched_count} 张未在最近 200 条会话历史中匹配"
                if unmatched_count
                else "已有图片占位均已恢复"
            )
        )
        return {
            "conversation_count": len(conversations),
            "checked_conversation_count": checked_conversations,
            "stored_count": max(0, status_after["stored_count"] - stored_before),
            "unmatched_count": unmatched_count,
            "failed_count": len(failed_conversations),
            "failed_conversations": failed_conversations,
            "stopped_early": stopped_early,
            "action_hint": action_hint,
            "status": status_after,
        }

    def content_file(self, archive_id: str) -> tuple[Path, str, str]:
        with self.database.session() as session:
            row = session.get(CustomerImageArchive, archive_id)
            if not row or row.deleted_at is not None:
                raise CustomerImageError("image_not_found", "原图不存在", status_code=404)
            if row.capture_status == "pending":
                raise CustomerImageError("image_not_stored", "原图尚未归档", status_code=409)
            if row.capture_status != "stored":
                raise CustomerImageError(row.error_code or "image_capture_failed", "原图归档失败，请查看逐图失败原因", status_code=409)
            path = self._resolved_storage_file(row.storage_path)
            if not path.is_file():
                raise CustomerImageError("image_file_missing", "原图文件缺失", status_code=409)
            if hashlib.sha256(path.read_bytes()).hexdigest() != row.sha256:
                raise CustomerImageError("image_integrity_failed", "原图完整性校验失败", status_code=409)
            return path, row.mime_type, row.original_name

    def preview_file(self, archive_id: str) -> tuple[Path, str, str]:
        original, _mime, _name = self.content_file(archive_id)
        data = original.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = self.preview_root / f"{digest}-v1.png"
        try:
            preview, _ = compatible_preview(data)
        except ImageCodecError as exc:
            raise CustomerImageError(exc.code, str(exc), status_code=422) from exc
        self._write_original(target, preview, hashlib.sha256(preview).hexdigest())
        return target, "image/png", "preview.png"

    def delete_local_copy(self, archive_id: str) -> None:
        with self.database.session() as session:
            row = session.get(CustomerImageArchive, archive_id)
            if not row or row.deleted_at is not None:
                raise CustomerImageError("image_not_found", "原图不存在", status_code=404)
            path = self._resolved_storage_file(row.storage_path) if row.storage_path else None
            shared = int(
                session.scalar(
                    select(func.count())
                    .select_from(CustomerImageArchive)
                    .where(
                        CustomerImageArchive.id != row.id,
                        CustomerImageArchive.storage_path == row.storage_path,
                        CustomerImageArchive.capture_status == "stored",
                        CustomerImageArchive.deleted_at.is_(None),
                    )
                )
                or 0
            )
            row.capture_status = "deleted"
            row.deleted_at = utcnow()
            job = session.get(CustomerImageCaptureJob, archive_id)
            if job:
                job.status, job.encrypted_media = "deleted", ""
            digest = row.sha256
            session.commit()
        self._publish_image(archive_id)
        if shared == 0 and path is not None:
            path.unlink(missing_ok=True)
            if re.fullmatch(r"[0-9a-f]{64}", digest or ""):
                (self.preview_root / f"{digest}-v1.png").unlink(missing_ok=True)
            parent = path.parent
            while parent != self.root and self.root in parent.parents:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
