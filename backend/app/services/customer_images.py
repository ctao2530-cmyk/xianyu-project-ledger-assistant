from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_, select

from ..adapters import (
    AdapterAccessVerificationError,
    AdapterDisconnectedError,
    AdapterError,
    LoginExpiredError,
)
from ..channels.base import ChannelMedia, ChannelMediaContent, ChannelMessage
from ..database import Database
from ..models import (
    Conversation,
    CustomerImageArchive,
    CustomerImageHistoryRecoveryRun,
    Message,
    utcnow,
)


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

    _MIME_ALIASES = {
        "image/jpg": "image/jpeg",
        "image/pjpeg": "image/jpeg",
        "image/x-png": "image/png",
    }
    _PIL_FORMATS = {
        "JPEG": ("image/jpeg", ".jpg"),
        "PNG": ("image/png", ".png"),
        "GIF": ("image/gif", ".gif"),
        "WEBP": ("image/webp", ".webp"),
        "BMP": ("image/bmp", ".bmp"),
        "TIFF": ("image/tiff", ".tiff"),
    }
    _ISO_BRANDS = {
        b"avif": ("image/avif", ".avif"),
        b"avis": ("image/avif", ".avif"),
        b"heic": ("image/heic", ".heic"),
        b"heix": ("image/heic", ".heic"),
        b"hevc": ("image/heic", ".heic"),
        b"hevx": ("image/heic", ".heic"),
        b"mif1": ("image/heif", ".heif"),
        b"msf1": ("image/heif", ".heif"),
    }

    def __init__(self, database: Database, project_root: Path) -> None:
        self.database = database
        self.project_root = project_root.resolve()
        self.root = (self.project_root / self.ROOT_RELATIVE).resolve()
        self.temp_root = (self.project_root / self.TEMP_RELATIVE).resolve()
        self._history_recovery_lock = asyncio.Lock()
        self._ensure_private_dir(self.root)
        self._ensure_private_dir(self.temp_root)

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
        if not data:
            raise CustomerImageError("image_empty", "图片文件为空")
        if len(data) > cls.MAX_IMAGE_BYTES:
            raise CustomerImageError("image_too_large", "单张原图不能超过 25 MB")

        mime = ""
        suffix = ""
        width = 0
        height = 0
        try:
            with Image.open(BytesIO(data)) as source:
                image_format = str(source.format or "").upper()
                detected = cls._PIL_FORMATS.get(image_format)
                if not detected:
                    raise CustomerImageError(
                        "image_format_unsupported",
                        "暂不支持该图片格式",
                    )
                mime, suffix = detected
                width, height = (int(source.width), int(source.height))
                source.verify()
        except CustomerImageError:
            raise
        except (UnidentifiedImageError, OSError, ValueError):
            if len(data) >= 12 and data[4:8] == b"ftyp":
                detected = cls._ISO_BRANDS.get(data[8:12].lower())
                if detected:
                    mime, suffix = detected
                else:
                    raise CustomerImageError("image_corrupt", "图片格式无法安全识别")
            else:
                raise CustomerImageError("image_corrupt", "图片文件损坏或格式不可信")

        supplied = (content_type or "").split(";", 1)[0].strip().lower()
        supplied = cls._MIME_ALIASES.get(supplied, supplied)
        if supplied and supplied not in {mime, "application/octet-stream", "binary/octet-stream"}:
            raise CustomerImageError("image_mime_mismatch", "图片格式与文件内容不一致")
        return mime, suffix, width, height

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
            if not message or not self._is_image_message(message):
                raise CustomerImageError("image_message_not_found", "没有找到对应的客户图片消息", status_code=404)
            row = session.scalar(
                select(CustomerImageArchive).where(
                    CustomerImageArchive.message_id == message_id,
                    CustomerImageArchive.media_index == media_index,
                )
            )
            if row:
                return row
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

    def _mark_failed(self, row_id: str, code: str) -> None:
        with self.database.session() as session:
            row = session.get(CustomerImageArchive, row_id)
            if not row or row.capture_status == "stored":
                return
            row.capture_status = "failed"
            row.error_code = code[:64]
            row.integrity_verified = False
            session.commit()

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
            current.deleted_at = None
            session.commit()
            return self._view(current, current.conversation.customer_name)

    async def capture_message(
        self,
        event: ChannelMessage,
        message_id: int,
        fetcher: MediaFetcher | None,
        *,
        capture_source: str,
    ) -> dict[str, int]:
        if event.direction != "inbound" or not (event.media or event.message_type == "image"):
            return {"stored": 0, "failed": 0}
        if not event.media:
            row = self._ensure_row(message_id, 0, capture_source=capture_source)
            self._mark_failed(row.id, "source_unavailable")
            return {"stored": 0, "failed": 1}

        stored = 0
        failed = 0
        for media in event.media:
            row = self._ensure_row(
                message_id,
                media.media_index,
                capture_source=capture_source,
            )
            if row.capture_status == "stored" and row.deleted_at is None:
                stored += 1
                continue
            if fetcher is None:
                self._mark_failed(row.id, "fetcher_unavailable")
                failed += 1
                continue
            try:
                content = await fetcher(media)
                self.store_original(
                    message_id,
                    media.media_index,
                    data=content.data,
                    content_type=content.mime_type or media.mime_type,
                    original_name=content.original_name or media.original_name,
                    capture_source=capture_source,
                )
                stored += 1
            except CustomerImageError as exc:
                self._mark_failed(row.id, exc.code)
                failed += 1
            except Exception:
                self._mark_failed(row.id, "remote_fetch_failed")
                failed += 1
        return {"stored": stored, "failed": failed}

    @staticmethod
    def _view(row: CustomerImageArchive, customer_name: str) -> dict[str, Any]:
        return {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "message_id": row.message_id,
            "channel": row.channel,
            "customer_name": customer_name,
            "received_at": row.received_at,
            "captured_at": row.captured_at,
            "mime_type": row.mime_type,
            "original_name": row.original_name,
            "file_size": row.file_size,
            "width": row.width,
            "height": row.height,
            "integrity_verified": row.integrity_verified,
            "content_url": f"/api/customer-images/{row.id}/content",
            "download_url": f"/api/customer-images/{row.id}/content?download=true",
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
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        start = self._parse_date_bound(date_from, end=False)
        end = self._parse_date_bound(date_to, end=True)
        conditions = [
            CustomerImageArchive.capture_status == "stored",
            CustomerImageArchive.deleted_at.is_(None),
        ]
        if channel and channel != "all":
            conditions.append(CustomerImageArchive.channel == channel)
        if conversation_id is not None:
            conditions.append(CustomerImageArchive.conversation_id == conversation_id)
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
                    .where(*conditions)
                )
                or 0
            )
            rows = list(
                session.execute(
                    select(CustomerImageArchive, Conversation.customer_name)
                    .join(Conversation, Conversation.id == CustomerImageArchive.conversation_id)
                    .where(*conditions)
                    .order_by(CustomerImageArchive.received_at.desc(), CustomerImageArchive.id.desc())
                    .offset(bounded_offset)
                    .limit(bounded_limit)
                )
            )
            return {
                "items": [self._view(row, customer_name) for row, customer_name in rows],
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
                        CustomerImageArchive.capture_status == "stored",
                        CustomerImageArchive.deleted_at.is_(None),
                    )
                    .group_by(Conversation.id, Conversation.customer_name, Conversation.channel)
                    .order_by(Conversation.customer_name.asc())
                )
            )
        return {
            "channels": ["xianyu", "wechat"],
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
                        or_(Message.message_type == "image", Message.content == "[图片]"),
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
        stored_messages = {
            message_id
            for message_id, values in by_message.items()
            if any(value.capture_status == "stored" and value.deleted_at is None for value in values)
        }
        failed_messages = {
            message_id
            for message_id, values in by_message.items()
            if message_id not in stored_messages and any(value.capture_status == "failed" for value in values)
        }
        pending_messages = {
            message_id
            for message_id, values in by_message.items()
            if message_id not in stored_messages
            and message_id not in failed_messages
            and any(value.capture_status == "pending" for value in values)
        }
        missing_messages = set(candidate_ids) - set(by_message)
        attention_messages = failed_messages | pending_messages | missing_messages
        attention = len(attention_messages)
        channel_counts = Counter(
            message.channel
            for message in candidates
            if message.id in attention_messages
        )
        return {
            "state": "healthy" if attention == 0 else "needs_attention",
            "stored_count": len(stored_messages),
            "attention_count": attention,
            "failed_count": len(failed_messages),
            "pending_count": len(pending_messages),
            "missing_count": len(missing_messages),
            "candidate_count": len(candidates),
            "channel_counts": dict(channel_counts),
            "last_captured_at": last_captured_at,
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
            if any(row.capture_status == "stored" and row.deleted_at is None for row in linked):
                continue
            failed = next((row for row in linked if row.capture_status == "failed"), None)
            pending = next((row for row in linked if row.capture_status == "pending"), None)
            if linked and failed is None and pending is None:
                # A deliberately deleted local copy is not an interrupted
                # capture and must not reappear as a recovery reminder.
                continue
            result.append(
                {
                    "message_id": message.id,
                    "conversation_id": message.conversation_id,
                    "channel": message.channel,
                    "customer_name": names.get(message.conversation_id, "客户"),
                    "received_at": message.received_at,
                    "status": "failed" if failed else "pending" if pending else "missing",
                    "error_code": (
                        failed.error_code
                        if failed
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
                stored = session.scalar(
                    select(CustomerImageArchive.id).where(
                        CustomerImageArchive.message_id == message.id,
                        CustomerImageArchive.capture_status == "stored",
                        CustomerImageArchive.deleted_at.is_(None),
                    )
                )
                if not stored:
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
            if not row or row.capture_status != "stored" or row.deleted_at is not None:
                raise CustomerImageError("image_not_found", "原图不存在", status_code=404)
            path = self._resolved_storage_file(row.storage_path)
            if not path.is_file():
                raise CustomerImageError("image_file_missing", "原图文件缺失", status_code=409)
            if hashlib.sha256(path.read_bytes()).hexdigest() != row.sha256:
                raise CustomerImageError("image_integrity_failed", "原图完整性校验失败", status_code=409)
            return path, row.mime_type, row.original_name

    def delete_local_copy(self, archive_id: str) -> None:
        with self.database.session() as session:
            row = session.get(CustomerImageArchive, archive_id)
            if not row or row.deleted_at is not None:
                raise CustomerImageError("image_not_found", "原图不存在", status_code=404)
            path = self._resolved_storage_file(row.storage_path)
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
            session.commit()
        if shared == 0:
            path.unlink(missing_ok=True)
            parent = path.parent
            while parent != self.root and self.root in parent.parents:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
