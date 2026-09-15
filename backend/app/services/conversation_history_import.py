from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.fernet import InvalidToken

from sqlalchemy import func, select

from ..adapters import (
    AdapterAccessVerificationError,
    AdapterDisconnectedError,
    AdapterError,
    IncomingMessage,
    ItemInfo,
    LoginExpiredError,
    XianyuAdapterProtocol,
)
from ..database import Database
from ..models import (
    Conversation,
    ConversationHistoryImportRequest,
    Item,
    Message,
    OperationLog,
)
from .ai_queue import AIJobQueue
from .customer_images import CustomerImageArchiveService
from .event_hub import EventHub
from .risk import detect_risks
from .customer_names import stable_customer_name


class ConversationHistoryImportError(RuntimeError):
    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(slots=True)
class HistoryPreviewRecord:
    token: str
    conversation_external_id: str
    customer_id: str
    customer_name: str
    item_info: ItemInfo | None
    messages: list[IncomingMessage]
    existing_platform_ids: frozenset[str]
    fingerprint: str
    expires_at: datetime
    has_more: bool = False
    next_continuation_token: str | None = None


@dataclass(slots=True)
class ConversationHistoryImportService:
    database: Database
    adapter: XianyuAdapterProtocol
    ai_queue: AIJobQueue
    event_hub: EventHub | None = None
    customer_images: CustomerImageArchiveService | None = None
    draft_generation_enabled: bool = True
    token_ttl_seconds: int = 600
    history_timeout_seconds: float = 20
    full_history_timeout_seconds: float = 90
    item_timeout_seconds: float = 22  # Legacy constructor compatibility; no remote item reads.
    _previews: dict[str, HistoryPreviewRecord] = field(default_factory=dict)

    SEARCH_LIMIT = 200
    MESSAGE_LIMIT = 200
    FULL_MESSAGE_LIMIT = 5000

    @staticmethod
    def _platform_id(message: IncomingMessage) -> str:
        return str(message.platform_message_id or message.external_id)

    @classmethod
    def _message_fingerprint(cls, messages: list[IncomingMessage]) -> str:
        payload = [
            {
                "platform_message_id": cls._platform_id(message),
                "conversation_id": message.conversation_id,
                "sender_id": message.sender_id,
                "direction": message.direction,
                "message_type": message.message_type,
                "content": message.content,
                "received_at": message.received_at.astimezone(timezone.utc).isoformat(),
                "item_id": message.item_id,
                "media": [{"index": media.media_index, "kind": media.locator_type, "reference_hash": hashlib.sha256(media.locator.encode()).hexdigest()} for media in message.media],
            }
            for message in messages
        ]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _request_hash(preview: HistoryPreviewRecord, mark_latest_pending: bool) -> str:
        payload = {
            "conversation_external_id": preview.conversation_external_id,
            "preview_fingerprint": preview.fingerprint,
            "mark_latest_pending": mark_latest_pending,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _cleanup_previews(self) -> None:
        now = datetime.now(timezone.utc)
        for token in [
            key for key, value in self._previews.items() if value.expires_at <= now
        ]:
            self._previews.pop(token, None)

    @staticmethod
    def _history_read_error(exc: Exception) -> ConversationHistoryImportError:
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return ConversationHistoryImportError(
                "xianyu_history_timeout",
                "闲鱼消息读取超时，本次未写入消息，请稍后手动重试",
                status_code=504,
            )
        if isinstance(exc, LoginExpiredError):
            return ConversationHistoryImportError(
                "xianyu_login_required",
                "闲鱼登录已失效，请先在渠道连接中恢复监听",
                status_code=401,
            )
        if isinstance(exc, AdapterAccessVerificationError):
            return ConversationHistoryImportError(
                "xianyu_verification_required",
                "闲鱼要求完成人机验证，请在现有 Ego Lite 会话中验证后重试",
                status_code=409,
            )
        if isinstance(exc, AdapterDisconnectedError):
            return ConversationHistoryImportError(
                "xianyu_listener_unavailable",
                "闲鱼监听正在重新连接，请稍后再读取历史会话",
                status_code=409,
            )
        if isinstance(exc, (OSError, httpx.RequestError)):
            return ConversationHistoryImportError(
                "xianyu_history_network_error",
                "闲鱼消息网络连接失败，本次未写入消息，请检查网络后手动重试",
                status_code=503,
            )
        return ConversationHistoryImportError(
            "xianyu_history_unavailable",
            "闲鱼历史会话暂时无法读取，请稍后重试",
            status_code=503,
        )

    async def _fetch_recent_conversations(self) -> list[IncomingMessage]:
        try:
            return await asyncio.wait_for(
                self.adapter.fetch_recent_conversation_messages(self.SEARCH_LIMIT),
                timeout=max(0.01, self.history_timeout_seconds),
            )
        except TimeoutError as exc:
            raise ConversationHistoryImportError(
                "xianyu_history_timeout",
                "闲鱼历史会话读取超时，监听仍会继续运行，请稍后重试",
                status_code=504,
            ) from exc
        except (AdapterError, OSError, httpx.RequestError) as exc:
            raise self._history_read_error(exc) from exc

    async def _fetch_conversation_messages(
        self,
        conversation_external_id: str,
        limit: int,
        *,
        full_history: bool = False,
    ) -> list[IncomingMessage]:
        try:
            if full_history:
                return await asyncio.wait_for(
                    self.adapter.fetch_all_messages(
                        conversation_external_id,
                        page_size=100,
                        max_messages=self.FULL_MESSAGE_LIMIT,
                    ),
                    timeout=max(0.01, self.full_history_timeout_seconds),
                )
            return await asyncio.wait_for(
                self.adapter.fetch_recent_messages(conversation_external_id, limit),
                timeout=max(0.01, self.history_timeout_seconds),
            )
        except TimeoutError as exc:
            raise ConversationHistoryImportError(
                "xianyu_history_timeout",
                "该闲鱼会话读取超时，未生成可导入预览且未写入任何消息，请稍后重试",
                status_code=504,
            ) from exc
        except (AdapterError, OSError, httpx.RequestError) as exc:
            raise self._history_read_error(exc) from exc

    def _local_item_info(
        self,
        item_external_id: str | None,
    ) -> ItemInfo | None:
        """Message sync must not depend on or refresh the product API."""
        if not item_external_id:
            return None
        with self.database.session() as session:
            item = session.scalar(
                select(Item).where(Item.external_id == item_external_id)
            )
            if item is None:
                return None
            return ItemInfo(
                external_id=item.external_id,
                title=item.title,
                price=item.price,
                description=item.description,
                raw={},
            )

    @staticmethod
    def _customer_identity(
        messages: list[IncomingMessage],
        existing: Conversation | None,
    ) -> tuple[str, str]:
        inbound = next(
            (message for message in reversed(messages) if message.direction == "inbound"),
            None,
        )
        if inbound:
            name = existing.customer_name if existing else None
            for message in sorted(messages, key=lambda message: message.received_at):
                if message.direction == "inbound" and message.sender_id == inbound.sender_id:
                    name = stable_customer_name(name, message.sender_name)
            return inbound.sender_id, name or "闲鱼客户"
        if existing:
            return existing.customer_id, existing.customer_name
        return "unknown-xianyu-customer", "闲鱼历史会话"

    async def search(
        self,
        *,
        query: str = "",
        days: int = 30,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if days not in {7, 30, 90, 365}:
            raise ConversationHistoryImportError("invalid_range", "请选择有效的历史时间范围")
        bounded_limit = min(max(1, limit), self.SEARCH_LIMIT)
        latest_messages = await self._fetch_recent_conversations()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        latest_by_conversation: dict[str, IncomingMessage] = {}
        for message in latest_messages:
            if message.received_at < cutoff:
                continue
            current = latest_by_conversation.get(message.conversation_id)
            if current is None or message.received_at > current.received_at:
                latest_by_conversation[message.conversation_id] = message

        with self.database.session() as session:
            existing_rows = {
                row.external_id: row
                for row in session.scalars(
                    select(Conversation).where(
                        Conversation.channel == "xianyu",
                        Conversation.external_id.in_(latest_by_conversation),
                    )
                )
            }
            item_ids = {
                row.item_id for row in existing_rows.values() if row.item_id is not None
            }
            items = {
                row.id: row
                for row in session.scalars(select(Item).where(Item.id.in_(item_ids)))
            } if item_ids else {}
            counts = dict(
                session.execute(
                    select(Conversation.external_id, func.count(Message.id))
                    .join(Message, Message.conversation_id == Conversation.id)
                    .where(
                        Conversation.channel == "xianyu",
                        Conversation.external_id.in_(latest_by_conversation),
                    )
                    .group_by(Conversation.external_id)
                ).all()
            ) if latest_by_conversation else {}

        normalized_query = query.strip().casefold()
        result: list[dict[str, Any]] = []
        for conversation_id, message in sorted(
            latest_by_conversation.items(),
            key=lambda entry: entry[1].received_at,
            reverse=True,
        ):
            existing = existing_rows.get(conversation_id)
            item = items.get(existing.item_id) if existing and existing.item_id else None
            customer_name = (
                existing.customer_name
                if existing
                else message.sender_name if message.direction == "inbound" else "闲鱼历史会话"
            )
            item_title = item.title if item else None
            searchable = " ".join(
                value for value in (customer_name, item_title or "", message.content) if value
            ).casefold()
            if normalized_query and normalized_query not in searchable:
                continue
            result.append(
                {
                    "external_conversation_id": conversation_id,
                    "customer_name": customer_name,
                    "item_title": item_title,
                    "last_message": message.content,
                    "last_message_at": message.received_at,
                    "direction": message.direction,
                    "existing_conversation_id": existing.id if existing else None,
                    "known_message_count": int(counts.get(conversation_id, 0)),
                }
            )
            if len(result) >= bounded_limit:
                break
        return result

    async def preview(
        self,
        *,
        external_conversation_id: str,
        message_limit: int = 100,
        full_history: bool = False,
        paged: bool = False,
        continuation_token: str | None = None,
    ) -> dict[str, Any]:
        self._cleanup_previews()
        conversation_external_id = external_conversation_id.strip()
        if not conversation_external_id or len(conversation_external_id) > 128:
            raise ConversationHistoryImportError(
                "invalid_conversation", "请选择有效的闲鱼历史会话"
            )
        bounded_limit = min(max(1, message_limit), self.MESSAGE_LIMIT)
        next_continuation_token = None
        has_more = False
        if paged:
            if not self.customer_images or self.customer_images._cipher is None or not hasattr(self.adapter, "fetch_messages_page"):
                raise ConversationHistoryImportError("history_pagination_unavailable", "当前渠道暂不支持可恢复分页同步")
            cursor = None
            if continuation_token:
                try:
                    continuation = json.loads(self.customer_images._cipher.decrypt(continuation_token.encode()))
                    if continuation["conversation"] != conversation_external_id or continuation["page_size"] != bounded_limit or continuation["kind"] != "history_page_v1":
                        raise ValueError()
                    cursor = continuation["cursor"]
                except (InvalidToken, ValueError, KeyError, TypeError):
                    raise ConversationHistoryImportError("history_cursor_invalid", "同步断点与当前会话或范围不一致", status_code=409) from None
            try:
                messages, next_cursor, has_more = await asyncio.wait_for(self.adapter.fetch_messages_page(conversation_external_id, page_size=bounded_limit, cursor=cursor), timeout=self.history_timeout_seconds)
            except (AdapterError, OSError, httpx.RequestError) as exc:
                raise self._history_read_error(exc) from exc
            if has_more:
                next_continuation_token = self.customer_images._cipher.encrypt(json.dumps({"kind": "history_page_v1", "conversation": conversation_external_id, "page_size": bounded_limit, "cursor": next_cursor}).encode()).decode()
        else:
            messages = await self._fetch_conversation_messages(conversation_external_id, bounded_limit, full_history=full_history)
        messages = sorted(
            [
                message
                for message in messages
                if message.conversation_id == conversation_external_id
            ],
            key=lambda message: (message.received_at, self._platform_id(message)),
        )
        if not messages:
            raise ConversationHistoryImportError(
                "conversation_empty",
                "没有读取到该会话的历史消息，请确认会话仍可访问",
                status_code=404,
            )

        item_external_id = next(
            (message.item_id for message in reversed(messages) if message.item_id),
            None,
        )
        item_info = self._local_item_info(item_external_id)
        platform_ids = {self._platform_id(message) for message in messages}
        with self.database.session() as session:
            existing_conversation = session.scalar(
                select(Conversation).where(
                    Conversation.channel == "xianyu",
                    Conversation.external_id == conversation_external_id,
                )
            )
            existing_message_rows = list(
                session.execute(
                    select(Message.platform_message_id, Conversation.external_id)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(
                        Message.channel == "xianyu",
                        Message.platform_message_id.in_(platform_ids),
                    )
                )
            )
            if any(
                external_id != conversation_external_id
                for _platform_id, external_id in existing_message_rows
            ):
                raise ConversationHistoryImportError(
                    "message_identity_conflict",
                    "平台消息身份与本地其他会话冲突，请先核对数据后再导入",
                    status_code=409,
                )
            existing_platform_ids = frozenset(
                platform_id for platform_id, _external_id in existing_message_rows
            )
            customer_id, customer_name = self._customer_identity(
                messages,
                existing_conversation,
            )

        fingerprint = self._message_fingerprint(messages)
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self.token_ttl_seconds
        )
        preview = HistoryPreviewRecord(
            token=token,
            conversation_external_id=conversation_external_id,
            customer_id=customer_id,
            customer_name=customer_name,
            item_info=item_info,
            messages=messages,
            existing_platform_ids=existing_platform_ids,
            fingerprint=fingerprint,
            expires_at=expires_at,
            has_more=has_more,
            next_continuation_token=next_continuation_token,
        )
        self._previews[token] = preview
        message_views = []
        unsupported_count = 0
        for message in messages:
            platform_id = self._platform_id(message)
            is_unsupported = message.message_type == "unsupported"
            if is_unsupported:
                unsupported_count += 1
            message_views.append(
                {
                    "platform_message_id": platform_id,
                    "sender_name": message.sender_name,
                    "direction": message.direction,
                    "message_type": message.message_type,
                    "content": (
                        "[暂不支持的历史消息，已保留安全占位]"
                        if is_unsupported
                        else message.content
                    ),
                    "received_at": message.received_at,
                    "import_status": (
                        "existing"
                        if platform_id in existing_platform_ids
                        else "unsupported" if is_unsupported else "new"
                    ),
                }
            )
        existing_count = len(existing_platform_ids)
        return {
            "token": token,
            "expires_at": expires_at,
            "external_conversation_id": conversation_external_id,
            "customer_name": customer_name,
            "item": (
                {
                    "external_id": item_info.external_id,
                    "title": item_info.title,
                    "price": item_info.price,
                    "description": item_info.description,
                }
                if item_info
                else None
            ),
            "item_warning": None,
            "messages": message_views,
            "platform_message_count": len(messages),
            "existing_count": existing_count,
            "new_count": len(messages) - existing_count,
            "unsupported_count": unsupported_count,
            "history_scope": "page" if paged else "full" if full_history else "recent",
            "has_more": has_more,
            "next_continuation_token": next_continuation_token,
            "image_candidate_count": sum(max(1, len(message.media)) for message in messages if message.direction == "inbound" and (message.media or message.message_type == "image")),
            "history_complete": not has_more if paged else None,
            "history_limit": self.FULL_MESSAGE_LIMIT if full_history else bounded_limit,
        }

    @staticmethod
    def _safe_external_id(message: IncomingMessage, occupied: set[str]) -> str:
        preferred = message.external_id
        if preferred not in occupied:
            occupied.add(preferred)
            return preferred
        fallback = "history-xianyu-" + hashlib.sha256(
            str(message.platform_message_id or message.external_id).encode("utf-8")
        ).hexdigest()
        occupied.add(fallback)
        return fallback

    @staticmethod
    def _existing_item(session, item_info: ItemInfo | None) -> Item | None:
        if not item_info:
            return None
        # Preview metadata is display-only; never write an older cached title,
        # price or description back over a concurrent product update.
        return session.scalar(select(Item).where(Item.external_id == item_info.external_id))

    async def _ensure_optional_draft(
        self,
        result: dict[str, Any],
        *,
        requested: bool,
    ) -> dict[str, Any]:
        if (
            not self.draft_generation_enabled
            or not requested
            or not result.get("pending_message_id")
        ):
            return result
        try:
            task = await self.ai_queue.enqueue(
                int(result["pending_message_id"]),
                automatic=True,
            )
        except Exception:
            # Import remains successful and explicit. The UI exposes the queue
            # failure instead of silently changing provider or sending anything.
            return {**result, "draft_task_queued": False}
        return {
            **result,
            "draft_task_queued": task is not None,
            "draft_task_id": task.id if task else None,
        }

    async def _archive_preview_images(
        self,
        preview: HistoryPreviewRecord,
        message_ids_by_platform: dict[str, int],
    ) -> dict[str, int]:
        candidates = [
            message
            for message in preview.messages
            if message.direction == "inbound"
            and (message.message_type == "image" or bool(message.media))
            and self._platform_id(message) in message_ids_by_platform
        ]
        candidate_count = sum(max(1, len(message.media)) for message in candidates)
        if not candidates:
            return {
                "image_candidate_count": 0,
                "image_stored_count": 0,
                "image_failed_count": 0,
            }
        if self.customer_images is None:
            return {
                "image_candidate_count": candidate_count,
                "image_stored_count": 0,
                "image_failed_count": candidate_count,
            }

        stored = 0
        failed = 0
        fetcher = getattr(self.adapter, "fetch_media", None)
        for message in candidates:
            try:
                result = await self.customer_images.capture_message(
                    message,
                    message_ids_by_platform[self._platform_id(message)],
                    fetcher,
                    capture_source="history_import",
                    already_enqueued=True,
                )
                stored += int(result.get("stored", 0))
                failed += int(result.get("failed", 0))
            except Exception:
                # The confirmed conversation import is already committed. A
                # single image failure must stay visible without rolling back
                # messages or stopping the remaining image downloads.
                failed += max(1, len(message.media))
        return {
            "image_candidate_count": candidate_count,
            "image_stored_count": stored,
            "image_failed_count": failed,
        }

    async def commit(
        self,
        *,
        request_id: str,
        preview_token: str,
        mark_latest_pending: bool = False,
    ) -> dict[str, Any]:
        self._cleanup_previews()
        if not request_id or len(request_id) > 128:
            raise ConversationHistoryImportError("invalid_request_id", "导入请求标识无效")
        preview_token_hash = hashlib.sha256(preview_token.encode("utf-8")).hexdigest()
        with self.database.session() as session:
            prior = session.get(ConversationHistoryImportRequest, request_id)
            if prior:
                if (
                    prior.preview_token_hash != preview_token_hash
                    or prior.mark_latest_pending != mark_latest_pending
                ):
                    raise ConversationHistoryImportError(
                        "request_conflict",
                        "相同请求标识已用于另一份导入，请重新操作",
                        status_code=409,
                    )
                prior_result = json.loads(prior.result_json)
                # Requests committed before image archiving was added remain
                # readable through the expanded response schema.
                prior_result.setdefault("image_candidate_count", 0)
                prior_result.setdefault("image_stored_count", 0)
                prior_result.setdefault("image_failed_count", 0)
                return {**prior_result, "idempotent": True}
        preview = self._previews.get(preview_token)
        if preview is None:
            raise ConversationHistoryImportError(
                "preview_expired",
                "导入预览已失效，请重新读取并确认",
                status_code=409,
            )
        if self._message_fingerprint(preview.messages) != preview.fingerprint:
            self._previews.pop(preview_token, None)
            raise ConversationHistoryImportError(
                "preview_changed",
                "导入预览内容已变化，请重新读取并确认",
                status_code=409,
            )
        payload_hash = self._request_hash(preview, mark_latest_pending)

        with self.database.session() as session:
            conversation = session.scalar(
                select(Conversation).where(
                    Conversation.channel == "xianyu",
                    Conversation.external_id == preview.conversation_external_id,
                )
            )
            created_conversation = conversation is None
            if conversation is None:
                conversation = Conversation(
                    channel="xianyu",
                    external_id=preview.conversation_external_id,
                    customer_id=preview.customer_id,
                    customer_name=stable_customer_name(None, preview.customer_name),
                    unread_count=0,
                    last_message_at=preview.messages[-1].received_at,
                )
                session.add(conversation)
                session.flush()
            else:
                conversation.customer_id = preview.customer_id
                conversation.customer_name = stable_customer_name(conversation.customer_name, preview.customer_name)

            item = self._existing_item(session, preview.item_info)
            if item:
                conversation.item = item

            platform_ids = [self._platform_id(message) for message in preview.messages]
            existing_by_platform = {
                row.platform_message_id: row
                for row in session.scalars(
                    select(Message).where(
                        Message.channel == "xianyu",
                        Message.platform_message_id.in_(platform_ids),
                    )
                )
            }
            if any(
                row.conversation_id != conversation.id
                for row in existing_by_platform.values()
            ):
                raise ConversationHistoryImportError(
                    "message_identity_conflict",
                    "平台消息身份与本地其他会话冲突，请重新预览并核对数据",
                    status_code=409,
                )
            occupied_external_ids = set(
                session.scalars(
                    select(Message.external_id).where(
                        Message.external_id.in_(
                            [message.external_id for message in preview.messages]
                        )
                    )
                )
            )
            imported_count = 0
            imported_by_platform: dict[str, Message] = dict(existing_by_platform)
            for history_message in preview.messages:
                platform_id = self._platform_id(history_message)
                if platform_id in existing_by_platform:
                    continue
                is_unsupported = history_message.message_type == "unsupported"
                message = Message(
                    channel="xianyu",
                    platform_message_id=platform_id,
                    external_id=self._safe_external_id(
                        history_message,
                        occupied_external_ids,
                    ),
                    conversation=conversation,
                    sender_id=history_message.sender_id,
                    sender_name=history_message.sender_name,
                    direction=history_message.direction,
                    message_type=history_message.message_type,
                    content=(
                        "[暂不支持的历史消息，已保留安全占位]"
                        if is_unsupported
                        else history_message.content
                    ),
                    status=(
                        "sent" if history_message.direction == "outbound" else "history"
                    ),
                    risk_flags_json=json.dumps(
                        detect_risks(history_message.content),
                        ensure_ascii=False,
                    ),
                    received_at=history_message.received_at,
                    source_item_external_id=history_message.item_id,
                )
                session.add(message)
                session.flush()
                imported_by_platform[platform_id] = message
                imported_count += 1

            message_ids_by_platform = {
                platform_id: message.id
                for platform_id, message in imported_by_platform.items()
            }
            if self.customer_images:
                for history_message in preview.messages:
                    stored_message = imported_by_platform.get(self._platform_id(history_message))
                    if stored_message is not None:
                        self.customer_images.persist_message_jobs(session, stored_message, history_message, capture_source="history_import")

            latest_message_at = max(message.received_at for message in preview.messages)
            stored_last_message_at = conversation.last_message_at
            if stored_last_message_at.tzinfo is None:
                stored_last_message_at = stored_last_message_at.replace(tzinfo=timezone.utc)
            if stored_last_message_at < latest_message_at:
                conversation.last_message_at = latest_message_at
            latest_inbound = next(
                (
                    imported_by_platform.get(self._platform_id(message))
                    for message in reversed(preview.messages)
                    if message.direction == "inbound"
                ),
                None,
            )
            pending_message_id = None
            if mark_latest_pending and latest_inbound is not None:
                latest_inbound.status = "new"
                pending_message_id = latest_inbound.id

            result = {
                "conversation_id": conversation.id,
                "created_conversation": created_conversation,
                "platform_message_count": len(preview.messages),
                "imported_count": imported_count,
                "existing_count": len(preview.messages) - imported_count,
                "pending_message_id": pending_message_id,
                "draft_task_queued": False,
                "draft_task_id": None,
                "image_candidate_count": 0,
                "image_stored_count": 0,
                "image_failed_count": 0,
                "idempotent": False,
                "has_more": preview.has_more,
                "next_continuation_token": preview.next_continuation_token,
            }
            session.add(
                ConversationHistoryImportRequest(
                    request_id=request_id,
                    payload_hash=payload_hash,
                    preview_token_hash=preview_token_hash,
                    mark_latest_pending=mark_latest_pending,
                    result_json=json.dumps(result, ensure_ascii=False),
                )
            )
            session.add(
                OperationLog(
                    action="conversation_history_imported",
                    detail=(
                        f"用户确认导入闲鱼历史会话：新增 {imported_count} 条，"
                        f"跳过 {len(preview.messages) - imported_count} 条"
                    ),
                )
            )
            session.commit()

        result.update(
            await self._archive_preview_images(preview, message_ids_by_platform)
        )
        result = await self._ensure_optional_draft(
            result,
            requested=mark_latest_pending,
        )
        with self.database.session() as session:
            row = session.get(ConversationHistoryImportRequest, request_id)
            if row:
                row.result_json = json.dumps(result, ensure_ascii=False)
                session.commit()
        if self.event_hub:
            self.event_hub.publish_nowait(
                {
                    "type": "conversation_history_imported",
                    "conversation_id": result["conversation_id"],
                    "imported_count": result["imported_count"],
                    "image_stored_count": result["image_stored_count"],
                    "image_failed_count": result["image_failed_count"],
                }
            )
        return result
