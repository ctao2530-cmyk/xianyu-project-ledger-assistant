from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone

from ..adapters import LoginExpiredError, XianyuAdapterProtocol
from ..config import Settings
from .notifier import MacOSNotifier
from .processor import MessageProcessor
from .listener_state import ListenerStateTracker
from .status import RuntimeStatus


logger = logging.getLogger(__name__)


class ListenerService:
    def __init__(
        self,
        settings: Settings,
        adapter: XianyuAdapterProtocol,
        processor: MessageProcessor,
        notifier: MacOSNotifier,
        status: RuntimeStatus,
        state_tracker: ListenerStateTracker | None = None,
    ) -> None:
        self.settings = settings
        self.adapter = adapter
        self.processor = processor
        self.notifier = notifier
        self.status = status
        self.state_tracker = state_tracker
        self.stop_event = asyncio.Event()
        self._processing: set[asyncio.Task] = set()
        self._login_notified = False

    def _ready(self) -> None:
        self._set_status("connected")
        self.status.realtime_delivery = "awaiting_message"
        self.status.realtime_detail = "消息订阅已确认，等待首条实时客户消息"
        self._login_notified = False

    def _set_status(
        self,
        status: str,
        detail: str | None = None,
        *,
        error_type: str | None = None,
    ) -> None:
        if self.state_tracker:
            self.state_tracker.record(status, detail, error_type=error_type)
        else:
            self.status.listener = status
            self.status.listener_detail = detail

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def run_forever(self) -> None:
        if not self.settings.xianyu_configured:
            self._set_status(
                "config_required", "请在 .env 配置有效的 XIANYU_COOKIE 后重启"
            )
            return

        reconcile_task = asyncio.create_task(
            self._reconcile_loop(), name="xianyu-reconcile"
        )
        try:
            attempt = 0
            while not self.stop_event.is_set():
                self._set_status("connecting" if attempt == 0 else "reconnecting")
                try:
                    async for event in self.adapter.listen(self._ready):
                        if self.stop_event.is_set():
                            break
                        attempt = 0
                        self.status.last_event_at = datetime.now(timezone.utc)
                        self.status.realtime_delivery = "healthy"
                        self.status.realtime_detail = None
                        task = asyncio.create_task(self.processor.process(event))
                        self._processing.add(task)
                        task.add_done_callback(self._processing.discard)
                except asyncio.CancelledError:
                    raise
                except LoginExpiredError as exc:
                    self._set_status(
                        "login_required", str(exc), error_type=type(exc).__name__
                    )
                    if not self._login_notified:
                        await self.notifier.notify(
                            "闲鱼登录已失效",
                            "请更新 .env 中的 XIANYU_COOKIE 并重启助手。",
                            "监听已暂停",
                        )
                        self._login_notified = True
                    await self._sleep_or_stop(self.settings.xianyu_reconnect_max_seconds)
                except Exception as exc:
                    attempt += 1
                    cap = min(
                        self.settings.xianyu_reconnect_max_seconds,
                        self.settings.xianyu_reconnect_min_seconds * (2 ** min(attempt, 8)),
                    )
                    delay = random.uniform(self.settings.xianyu_reconnect_min_seconds, cap)
                    detail = f"连接中断（{type(exc).__name__}），{delay:.0f} 秒后重试"
                    self._set_status(
                        "reconnecting", detail, error_type=type(exc).__name__
                    )
                    if not self.state_tracker:
                        logger.warning("闲鱼监听断开，准备重连：%s", type(exc).__name__)
                    await self._sleep_or_stop(delay)
        finally:
            reconcile_task.cancel()
            await asyncio.gather(reconcile_task, return_exceptions=True)

    async def _reconcile_loop(self) -> None:
        await asyncio.sleep(1)
        while not self.stop_event.is_set():
            if self.adapter.connected:
                try:
                    self.status.last_reconcile_at = datetime.now(timezone.utc)
                    recovered = await self.processor.reconcile_recent_conversations(
                        self.settings.xianyu_reconcile_conversation_limit,
                        self.settings.xianyu_reconcile_max_age_minutes,
                    )
                    if recovered:
                        self.status.last_event_at = datetime.now(timezone.utc)
                        self.status.reconcile_recovered_total += recovered
                        self.status.realtime_delivery = "degraded"
                        self.status.realtime_detail = (
                            "实时推送未覆盖全部客户消息，当前已启用补偿轮询"
                        )
                        logger.info("闲鱼漏消息补偿完成 recovered=%s", recovered)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("闲鱼漏消息补偿失败：%s", type(exc).__name__)
            delay = self.settings.xianyu_reconcile_interval_seconds + random.uniform(0, 5)
            await self._sleep_or_stop(delay)

    async def stop(self) -> None:
        self.stop_event.set()
        await self.adapter.close()
        if self._processing:
            await asyncio.gather(*self._processing, return_exceptions=True)
        stop_processor = getattr(self.processor, "stop", None)
        if stop_processor:
            await stop_processor()
