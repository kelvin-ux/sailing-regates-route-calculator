from __future__ import annotations


import asyncio
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_calls: int = 550, period: int = 60):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.time()
            while self.calls and self.calls[0] < now - self.period:
                self.calls.popleft()

            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0]) + 0.1
                await asyncio.sleep(sleep_time)
                return await self.acquire()

            self.calls.append(now)

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass