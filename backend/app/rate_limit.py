from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self.lock:
            bucket = self.events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True
