from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any


EventPayload = dict[str, Any]


@dataclass(slots=True)
class Subscription:
    queue: asyncio.Queue[EventPayload]
    replay: list[EventPayload]


class EventHub:
    """In-process fan-out for local desktop clients.

    AI and Xianyu services do not depend on WebSocket objects. Slow desktop
    clients get a bounded queue, and recent reply events are replayed after a
    reconnect during the same backend process lifetime.
    """

    def __init__(self, *, queue_size: int = 100, replay_size: int = 100) -> None:
        self.queue_size = queue_size
        self._subscribers: set[asyncio.Queue[EventPayload]] = set()
        self._replay: deque[EventPayload] = deque(maxlen=replay_size)

    def subscribe(self) -> Subscription:
        queue: asyncio.Queue[EventPayload] = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers.add(queue)
        return Subscription(queue=queue, replay=list(self._replay))

    def unsubscribe(self, queue: asyncio.Queue[EventPayload]) -> None:
        self._subscribers.discard(queue)

    def publish_nowait(self, event: EventPayload) -> None:
        payload = dict(event)
        if payload.get("type") == "new_reply":
            self._replay.append(payload)
        for queue in tuple(self._subscribers):
            if queue.full():
                # Never replace an unread reply with a newer one. The desktop
                # has its own visible max queue and will surface that limit.
                continue
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
