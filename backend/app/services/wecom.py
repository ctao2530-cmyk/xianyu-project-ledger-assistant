from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..channels.wechat import WeChatAdapter
from ..channels.wecom import (
    WeComAPIClient,
    WeComCallbackEvent,
    WeComConfigurationError,
    WeComCrypto,
    WeComError,
    callback_event_from_xml,
    encrypted_value_from_xml,
)
from ..config import Settings
from ..database import Database
from ..models import ChannelCursor
from .notifier import MacOSNotifier
from .processor import MessageProcessor
from .style_learning import StyleLearningService


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WeComStatusSnapshot:
    provider: str
    configured: bool
    status: str
    detail: str
    last_event_at: datetime | None


class WeComService:
    """Bridge official WeCom callbacks into the existing message/AI pipeline."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        adapter: WeChatAdapter,
        processor: MessageProcessor,
        style_learning: StyleLearningService,
        notifier: MacOSNotifier,
        *,
        client: WeComAPIClient | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.adapter = adapter
        self.processor = processor
        self.style_learning = style_learning
        self.notifier = notifier
        self.client = client or WeComAPIClient(settings)
        self._crypto = (
            WeComCrypto(
                settings.wecom_callback_token.get_secret_value(),
                settings.wecom_encoding_aes_key.get_secret_value(),
                settings.wecom_corp_id,
            )
            if settings.wecom_configured
            else None
        )
        self.status = "config_required"
        self.detail = "请配置企业微信客服回调参数"
        self.last_event_at: datetime | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._account_locks: dict[str, asyncio.Lock] = {}

    @property
    def configured(self) -> bool:
        return self.settings.wecom_configured and self._crypto is not None

    def snapshot(self) -> WeComStatusSnapshot:
        return WeComStatusSnapshot(
            provider=self.settings.wechat_provider,
            configured=self.configured,
            status=self.status,
            detail=self.detail,
            last_event_at=self.last_event_at,
        )

    async def start(self) -> None:
        if not self.configured:
            self.status = "config_required"
            self.detail = "企业微信接口未配置；微信 Mock 仍可用于本地测试"
            return
        self.status = "checking"
        self.detail = "正在验证企业微信接口凭证"
        try:
            await self.client.healthcheck()
        except WeComError as exc:
            self.status = "error"
            self.detail = f"企业微信接口验证失败：{exc}"
            logger.warning("企业微信接口启动检查失败 error=%s", type(exc).__name__)
            await self.notifier.notify(
                "鱼答：企业微信连接失败",
                self.detail,
                "请使用已授权微信客服 API 的 Secret",
            )
            return
        except Exception as exc:
            self.status = "error"
            self.detail = f"企业微信接口验证失败：{type(exc).__name__}"
            logger.warning("企业微信接口启动检查失败 error=%s", type(exc).__name__)
            await self.notifier.notify(
                "鱼答：企业微信连接失败",
                self.detail,
                "闲鱼监听和本地消息保存不受影响",
            )
            return
        self.status = "connected"
        self.detail = "企业微信客服 API 权限有效，等待官方回调"

    def verify_url(
        self,
        *,
        signature: str,
        timestamp: str,
        nonce: str,
        echo: str,
    ) -> str:
        crypto = self._require_crypto()
        return crypto.decrypt(
            echo,
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
        )

    def accept_callback(
        self,
        payload: bytes,
        *,
        signature: str,
        timestamp: str,
        nonce: str,
    ) -> WeComCallbackEvent:
        crypto = self._require_crypto()
        encrypted = encrypted_value_from_xml(payload)
        decrypted = crypto.decrypt(
            encrypted,
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
        )
        event = callback_event_from_xml(decrypted)
        self.last_event_at = datetime.now(timezone.utc)
        self._schedule(event)
        return event

    def _require_crypto(self) -> WeComCrypto:
        if not self._crypto:
            raise WeComConfigurationError("企业微信官方接口尚未配置完整")
        return self._crypto

    def _schedule(self, event: WeComCallbackEvent) -> None:
        task = asyncio.create_task(
            self.sync_event(event),
            name=f"wecom-sync-{event.open_kfid[-8:]}",
        )
        self._tasks.add(task)

        def completed(done: asyncio.Task[None]) -> None:
            self._tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error:
                self.status = "error"
                self.detail = f"企业微信消息同步失败：{type(error).__name__}"
                logger.warning(
                    "企业微信消息同步任务失败 error=%s", type(error).__name__
                )

        task.add_done_callback(completed)

    async def sync_event(self, event: WeComCallbackEvent) -> None:
        lock = self._account_locks.setdefault(event.open_kfid, asyncio.Lock())
        async with lock:
            cursor = self._load_cursor(event.open_kfid)
            outbound_seen = False
            has_more = True
            pages = 0
            while has_more and pages < self.settings.wecom_sync_max_pages:
                data = await self.client.sync_page(
                    open_kfid=event.open_kfid,
                    cursor=cursor,
                    callback_token=event.callback_token,
                )
                rows = data.get("msg_list")
                messages = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
                customer_ids = [
                    str(row.get("external_userid"))
                    for row in messages
                    if int(row.get("origin") or 0) in {3, 5}
                    and row.get("external_userid")
                ]
                try:
                    names = await self.client.customer_names(customer_ids)
                except Exception as exc:
                    names = {}
                    logger.warning(
                        "企业微信客户昵称获取失败 error=%s", type(exc).__name__
                    )
                for raw in messages:
                    origin = int(raw.get("origin") or 0)
                    if origin not in {3, 5}:
                        continue
                    if not raw.get("msgid") or not raw.get("external_userid") or not raw.get("open_kfid"):
                        continue
                    customer_id = str(raw["external_userid"])
                    message = await self.adapter.receive_wecom_message(
                        raw,
                        customer_name=names.get(customer_id, "微信客户"),
                    )
                    await self.processor.process(message, source="wecom_callback")
                    outbound_seen = outbound_seen or message.direction == "outbound"
                next_cursor = str(data.get("next_cursor") or cursor)
                if next_cursor:
                    self._save_cursor(event.open_kfid, next_cursor)
                    cursor = next_cursor
                has_more = bool(int(data.get("has_more") or 0))
                pages += 1

            if outbound_seen:
                self.style_learning.capture_synced_outbound()
            self.status = "connected"
            self.detail = (
                f"企业微信消息同步正常，最近处理 {pages} 页"
                if not has_more
                else f"单次同步达到 {pages} 页安全上限，等待下一次回调继续"
            )
            logger.info(
                "企业微信消息同步完成 open_kfid_suffix=%s pages=%s has_more=%s",
                event.open_kfid[-6:],
                pages,
                has_more,
            )

    def _cursor_key(self, open_kfid: str) -> str:
        return f"wecom_customer_service:{open_kfid}"

    def _load_cursor(self, open_kfid: str) -> str:
        with self.database.session() as session:
            row = session.get(ChannelCursor, self._cursor_key(open_kfid))
            return row.cursor if row else ""

    def _save_cursor(self, open_kfid: str, cursor: str) -> None:
        with self.database.session() as session:
            key = self._cursor_key(open_kfid)
            row = session.get(ChannelCursor, key)
            if row is None:
                row = ChannelCursor(key=key, channel="wechat")
                session.add(row)
            row.cursor = cursor
            session.commit()

    async def stop(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        await self.client.close()
