from __future__ import annotations

import asyncio
from contextlib import suppress

from .listener import ListenerService
from .listener_state import ListenerStateTracker
from .status import RuntimeStatus


class ListenerSupervisor:
    """Controls the listener task without changing its protocol logic."""

    def __init__(
        self,
        listener: ListenerService,
        status: RuntimeStatus,
        state_tracker: ListenerStateTracker | None = None,
    ) -> None:
        self.listener = listener
        self.status = status
        self.state_tracker = state_tracker
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._shutting_down = False
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    def _set_status(self, status: str, detail: str | None = None) -> None:
        if self.state_tracker:
            self.state_tracker.record(status, detail)
        else:
            self.status.listener = status
            self.status.listener_detail = detail

    async def start(self) -> None:
        async with self._lock:
            if self._shutting_down:
                return
            if self._task and not self._task.done():
                return
            self._paused = False
            self._task = asyncio.create_task(
                self.listener.run_forever(), name="xianyu-listener"
            )

    async def pause(self) -> None:
        async with self._lock:
            self._paused = True
            await self._cancel_task()
            self._set_status("paused", "已由菜单栏暂停监听")

    async def resume(self) -> None:
        async with self._lock:
            if self._shutting_down:
                return
            if self._task and not self._task.done():
                return
            self._paused = False
            self._set_status("connecting", "正在恢复闲鱼监听")
            self._task = asyncio.create_task(
                self.listener.run_forever(), name="xianyu-listener"
            )

    async def reconnect(self) -> None:
        async with self._lock:
            if self._shutting_down:
                return
            await self._cancel_task()
            self._paused = False
            self._set_status("reconnecting", "正在按用户请求重新连接")
            self._task = asyncio.create_task(
                self.listener.run_forever(), name="xianyu-listener"
            )

    async def shutdown(self) -> None:
        async with self._lock:
            self._shutting_down = True
            await self._cancel_task()
            await self.listener.stop()

    async def _cancel_task(self) -> None:
        task = self._task
        self._task = None
        if not task or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
