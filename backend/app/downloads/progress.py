"""In-process pub/sub broker.

Each connected SSE client subscribes and gets its own bounded queue; the worker / updater publish
plain dicts that are fanned out to every subscriber. No external broker required.
"""
from __future__ import annotations

import asyncio

from backend.app.logging import get_logger

log = get_logger(__name__)


class ProgressBroker:
    def __init__(self, maxsize: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def publish(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer — drop the event rather than block the worker.
                pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
