from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import func, select

from ..adapters import IncomingMessage, XianyuAdapterProtocol
from ..database import Database
from ..models import Conversation, Message
from .ai_queue import AIJobQueue
from .customer_images import CustomerImageArchiveService, MediaFetcher
from .event_hub import EventHub
from .notifier import MacOSNotifier
from .repository import hydrate_conversation_context, ingest_message


logger = logging.getLogger(__name__)


class CustomerAnalysisScheduler(Protocol):
    def persist_message_event(self, session, message: Message) -> bool: ...

    def notify(self) -> None: ...


class MessageProcessor:
    def __init__(
        self,
        database: Database,
        adapter: XianyuAdapterProtocol,
        ai_queue: AIJobQueue,
        notifier: MacOSNotifier,
        history_limit: int,
        context_hydration_timeout_seconds: float = 1.5,
        item_cache_ttl_seconds: int = 1800,
        reply_drafts_enabled: bool = True,
        customer_analysis: CustomerAnalysisScheduler | None = None,
        customer_images: CustomerImageArchiveService | None = None,
        media_fetchers: dict[str, MediaFetcher] | None = None,
        event_hub: EventHub | None = None,
    ) -> None:
        self.database = database
        self.adapter = adapter
        self.ai_queue = ai_queue
        self.notifier = notifier
        self.history_limit = history_limit
        self.context_hydration_timeout_seconds = context_hydration_timeout_seconds
        self.item_cache_ttl_seconds = item_cache_ttl_seconds
        self.reply_drafts_enabled = reply_drafts_enabled
        self.customer_analysis = customer_analysis
        self.customer_images = customer_images
        self.media_fetchers = media_fetchers or {}
        self.event_hub = event_hub
        self._ingest_lock = asyncio.Lock()
        self._hydration_tasks: set[asyncio.Task[None]] = set()

    def _cached_context_ready(self, event: IncomingMessage) -> bool:
        with self.database.session() as session:
            conversation = session.scalar(
                select(Conversation).where(
                    Conversation.channel == event.channel,
                    Conversation.external_id == event.conversation_id
                )
            )
            if not conversation:
                return False
            message_count = session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation.id)
            ) or 0
            if message_count < 2:
                return False
            if not event.item_id:
                return True
            item = conversation.item
            if not item or item.external_id != event.item_id:
                return False
            now = (
                datetime.now(item.updated_at.tzinfo)
                if item.updated_at.tzinfo
                else datetime.now()
            )
            return (now - item.updated_at).total_seconds() <= self.item_cache_ttl_seconds

    async def _hydrate_context(self, event: IncomingMessage) -> None:
        history: list[IncomingMessage] = []
        item_info = None
        history_task = asyncio.create_task(
            self.adapter.fetch_recent_messages(
                event.conversation_id, self.history_limit
            )
        )
        item_task = (
            asyncio.create_task(self.adapter.fetch_item(event.item_id))
            if event.item_id
            else None
        )
        results = await asyncio.gather(
            *([history_task, item_task] if item_task else [history_task]),
            return_exceptions=True,
        )
        history_result = results[0]
        if isinstance(history_result, Exception):
            logger.warning("获取会话历史失败，将使用本地上下文：%s", type(history_result).__name__)
        else:
            history = history_result
        if item_task:
            item_result = results[1]
            if isinstance(item_result, Exception):
                logger.warning("获取商品信息失败：%s", type(item_result).__name__)
            else:
                item_info = item_result

        if not history and item_info is None:
            return
        async with self._ingest_lock:
            with self.database.session() as session:
                hydrate_conversation_context(
                    session, event, history, item_info,
                    on_media_persist=(self.customer_images.persist_message_jobs if self.customer_images else None),
                )
        if self.customer_images:
            self.customer_images._wake.set()

    def _track_hydration(self, task: asyncio.Task[None]) -> None:
        self._hydration_tasks.add(task)

        def completed(done: asyncio.Task[None]) -> None:
            self._hydration_tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error:
                logger.warning("后台上下文补充失败：%s", type(error).__name__)

        task.add_done_callback(completed)

    async def _archive_customer_images(
        self,
        event: IncomingMessage,
        message_id: int,
        *,
        source: str,
    ) -> None:
        if not self.customer_images or event.direction != "inbound":
            return
        if not (event.media or event.message_type == "image"):
            return
        try:
            self.customer_images.start(self.media_fetchers, self.event_hub)
            self.customer_images.notify_committed(message_id)
        except Exception as exc:
            # Message ingestion has already committed.  Image failures remain
            # visible in the archive status and must never roll back chat data.
            logger.warning(
                "客户原图归档失败 channel=%s message_id=%s error=%s",
                event.channel,
                message_id,
                type(exc).__name__,
            )

    async def process(self, event: IncomingMessage, *, source: str = "live") -> int:
        started = time.monotonic()
        async with self._ingest_lock:
            with self.database.session() as session:
                result = ingest_message(
                    session,
                    event,
                    [],
                    None,
                    source=source,
                    on_persist=(
                        self.customer_analysis.persist_message_event
                        if self.customer_analysis is not None
                        else None
                    ),
                    on_media_persist=(self.customer_images.persist_message_jobs if self.customer_images else None),
                )
        if not result.is_new:
            await self._archive_customer_images(
                event,
                result.message_id,
                source=source,
            )
            logger.info(
                "忽略重复渠道消息 channel=%s platform_message_id=%s",
                event.channel,
                event.platform_message_id,
            )
            return result.message_id

        if self.event_hub is not None:
            # ingest_message committed the message and optional analysis Outbox
            # before this body-free desktop notification is published.
            with self.database.session() as session:
                persisted = session.get(Message, result.message_id)
                conversation_id = persisted.conversation_id if persisted else None
            if conversation_id is not None:
                self.event_hub.publish_nowait(
                    {
                        "type": "customer_context_updated",
                        "conversation_id": conversation_id,
                        "message_id": result.message_id,
                        "channel": event.channel,
                        "direction": event.direction,
                    }
                )

        await self._archive_customer_images(event, result.message_id, source=source)
        if self.customer_analysis is not None:
            self.customer_analysis.notify()

        # Official channel sync APIs also return messages sent by a human
        # agent.  Persist them as conversation/style context, but never create
        # a reply task for an outbound echo.
        if event.direction != "inbound":
            logger.info(
                "渠道出站消息已同步 channel=%s source=%s message_id=%s",
                event.channel,
                source,
                result.message_id,
            )
            return result.message_id

        await self.notifier.notify(
            "微信有新消息" if event.channel == "wechat" else "闲鱼有新消息",
            event.content,
            event.sender_name,
        )

        if event.channel == "xianyu":
            hydration_task = asyncio.create_task(
                self._hydrate_context(event),
                name=f"hydrate-context-{result.message_id}",
            )
            self._track_hydration(hydration_task)
        logger.info(
            "渠道消息已入库，持续分析仅由已授权客户订阅消费 "
            "channel=%s source=%s message_id=%s cached_context=%s elapsed_ms=%s",
            event.channel,
            source,
            result.message_id,
            self._cached_context_ready(event),
            int((time.monotonic() - started) * 1000),
        )
        return result.message_id

    async def regenerate(
        self, message_id: int, *, provider_name: str | None = None
    ) -> int | None:
        if not self.reply_drafts_enabled:
            return None
        task = await self.ai_queue.enqueue(
            message_id,
            automatic=False,
            provider_name=provider_name,
        )
        return task.id if task else None

    async def reconcile_recent_conversations(
        self, limit: int, max_age_minutes: int
    ) -> int:
        """Recover the newest unseen inbound message when WebSocket push is missed."""
        events = await self.adapter.fetch_recent_conversation_messages(limit)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        recovered = 0
        for event in events:
            if event.direction != "inbound" or event.received_at < cutoff:
                continue
            with self.database.session() as session:
                exists = session.scalar(
                    select(Message.id).where(
                        Message.channel == "xianyu",
                        Message.platform_message_id == event.platform_message_id,
                    )
                )
            if exists:
                continue
            await self.process(event, source="reconcile")
            recovered += 1
        return recovered

    async def stop(self) -> None:
        tasks = list(self._hydration_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.customer_images:
            await self.customer_images.stop()
