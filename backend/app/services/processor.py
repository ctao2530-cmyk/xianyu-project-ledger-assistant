from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import func, select

from ..adapters import IncomingMessage, XianyuAdapterProtocol
from ..database import Database
from ..models import Conversation, Message, OperationLog
from .ai_queue import AIJobQueue
from .customer_images import CustomerImageArchiveService, MediaFetcher
from .event_hub import EventHub
from .notifier import MacOSNotifier
from .repository import hydrate_conversation_context, ingest_message


logger = logging.getLogger(__name__)


class SalesAnalysisScheduler(Protocol):
    def schedule(self, message_id: int) -> None: ...


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
        reply_burst_coalesce_seconds: float = 0,
        reply_drafts_enabled: bool = True,
        sales_analysis_enabled: bool = True,
        sales_agent: SalesAnalysisScheduler | None = None,
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
        self.reply_burst_coalesce_seconds = reply_burst_coalesce_seconds
        self.reply_drafts_enabled = reply_drafts_enabled
        self.sales_analysis_enabled = sales_analysis_enabled
        self.sales_agent = sales_agent
        self.customer_images = customer_images
        self.media_fetchers = media_fetchers or {}
        self.event_hub = event_hub
        self._ingest_lock = asyncio.Lock()
        self._hydration_tasks: set[asyncio.Task[None]] = set()
        self._reply_debounce_lock = asyncio.Lock()
        self._reply_debounce_tasks: dict[str, tuple[int, asyncio.Task[None]]] = {}

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
                    session, event, history, item_info
                )

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

    def _mark_superseded(self, message_id: int, replacement_id: int) -> None:
        with self.database.session() as session:
            message = session.get(Message, message_id)
            if not message or message.status != "new":
                return
            message.status = "superseded"
            session.add(
                OperationLog(
                    message_id=message_id,
                    action="ai_generation_coalesced",
                    detail=f"同会话连续消息已合并，由较新消息 {replacement_id} 生成一次草稿",
                )
            )
            session.commit()

    async def _enqueue_after_delay(
        self, conversation_key: str, message_id: int
    ) -> None:
        try:
            if self.reply_burst_coalesce_seconds:
                await asyncio.sleep(self.reply_burst_coalesce_seconds)
            await self._enqueue_ai_services(message_id)
            logger.info(
                "连续消息合并窗口结束，已进入 AI 队列 message_id=%s delay_ms=%s",
                message_id,
                int(self.reply_burst_coalesce_seconds * 1000),
            )
        except asyncio.CancelledError:
            raise
        finally:
            async with self._reply_debounce_lock:
                current = self._reply_debounce_tasks.get(conversation_key)
                if current and current[0] == message_id:
                    self._reply_debounce_tasks.pop(conversation_key, None)

    async def _schedule_ai_generation(
        self, conversation_key: str, message_id: int
    ) -> None:
        if self.reply_burst_coalesce_seconds <= 0:
            await self._enqueue_ai_services(message_id)
            return
        async with self._reply_debounce_lock:
            previous = self._reply_debounce_tasks.get(conversation_key)
            if previous:
                previous_message_id, previous_task = previous
                previous_task.cancel()
                self._mark_superseded(previous_message_id, message_id)
            task = asyncio.create_task(
                self._enqueue_after_delay(conversation_key, message_id),
                name=f"coalesce-reply-{message_id}",
            )
            self._reply_debounce_tasks[conversation_key] = (message_id, task)

    async def _enqueue_ai_services(self, message_id: int) -> None:
        if self.reply_drafts_enabled:
            await self.ai_queue.enqueue(message_id, automatic=True)
        if self.sales_analysis_enabled and self.sales_agent is not None:
            # Sales analysis is independent: scheduling it never blocks or
            # changes the existing reply-draft task and it cannot send.
            self.sales_agent.schedule(message_id)

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
            result = await self.customer_images.capture_message(
                event,
                message_id,
                self.media_fetchers.get(event.channel),
                capture_source=(
                    "history"
                    if source == "image_history"
                    else "wecom" if source == "wecom_callback" else "live"
                ),
            )
            logger.info(
                "客户原图归档完成 channel=%s message_id=%s stored=%s failed=%s",
                event.channel,
                message_id,
                result["stored"],
                result["failed"],
            )
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
                    session, event, [], None, source=source
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

        if self.event_hub is not None and event.message_type == "text":
            # ingest_message commits before returning.  The event deliberately
            # carries no body and never schedules model work.
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
        if self.reply_drafts_enabled or self.sales_analysis_enabled:
            await self._schedule_ai_generation(
                f"{event.channel}:{event.conversation_id}", result.message_id
            )
            logger.info(
                "渠道消息已入库并安排可用分析任务 channel=%s source=%s message_id=%s "
                "drafts_enabled=%s sales_enabled=%s cached_context=%s coalesce_ms=%s elapsed_ms=%s",
                event.channel,
                source,
                result.message_id,
                self.reply_drafts_enabled,
                self.sales_analysis_enabled,
                self._cached_context_ready(event),
                int(self.reply_burst_coalesce_seconds * 1000),
                int((time.monotonic() - started) * 1000),
            )
        else:
            logger.info(
                "渠道消息已入库，客户消息 AI 功能已暂停 channel=%s source=%s message_id=%s elapsed_ms=%s",
                event.channel,
                source,
                result.message_id,
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
        debounce_tasks = [entry[1] for entry in self._reply_debounce_tasks.values()]
        tasks = list(self._hydration_tasks) + debounce_tasks
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reply_debounce_tasks.clear()
