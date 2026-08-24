from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import CodexDevelopmentRuntime, RuntimeCapabilities, RuntimeEvent, RuntimeRun


class MockDevelopmentRuntime(CodexDevelopmentRuntime):
    def __init__(self) -> None:
        self.events: asyncio.Queue[RuntimeEvent | None] = asyncio.Queue()
        self.approved: list[str] = []
        self.rejected: list[str] = []
        self.interrupted: list[tuple[str, str]] = []
        self._counter = 0

    async def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities("mock", True, version="test")

    async def create_run(self, **_: str) -> RuntimeRun:
        self._counter += 1
        run = RuntimeRun(f"mock-thread-{self._counter}")
        await self.events.put(RuntimeEvent("run_started", thread_id=run.thread_id))
        return run

    async def start_turn(self, *, thread_id: str, **_: str) -> RuntimeRun:
        run = RuntimeRun(thread_id, f"mock-turn-{self._counter}")
        await self.events.put(RuntimeEvent("task_started", thread_id, run.turn_id))
        return run

    async def resume_run(self, *, thread_id: str, **_: str) -> RuntimeRun:
        return RuntimeRun(thread_id)

    async def cancel_run(self, *, thread_id: str, turn_id: str) -> None:
        self.interrupted.append((thread_id, turn_id))

    async def approve_action(self, *, server_request_id: str) -> None:
        self.approved.append(server_request_id)

    async def reject_action(self, *, server_request_id: str, cancel_turn: bool = False) -> None:
        self.rejected.append(server_request_id)

    async def emit(self, event: RuntimeEvent) -> None:
        await self.events.put(event)

    async def _iterator(self) -> AsyncIterator[RuntimeEvent]:
        while True:
            event = await self.events.get()
            if event is None:
                return
            yield event

    def stream_events(self) -> AsyncIterator[RuntimeEvent]:
        return self._iterator()

    async def close(self) -> None:
        await self.events.put(None)
