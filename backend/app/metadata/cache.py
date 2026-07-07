"""Tiny in-memory TTL cache — no external dependency.

Search results and Navidrome library lookups repeat constantly (opening an album fires one
``library_quality`` call per track; re-running the same search re-hits Spotify/MusicBrainz). A
short-lived memoization cuts that traffic without risking stale data: entries expire after a few
minutes, so a freshly downloaded track still shows up on the next rescan.

Not thread-safe by design — the whole app runs on a single asyncio loop, and cache ops are
synchronous between awaits.
"""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    def __init__(self, *, ttl_s: float, max_entries: int = 2048) -> None:
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if len(self._store) >= self.max_entries:
            self._evict_expired()
            if len(self._store) >= self.max_entries:
                # Still full of live entries — drop the oldest-expiring one.
                oldest = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest, None)
        self._store[key] = (time.monotonic() + self.ttl_s, value)

    def invalidate(self, key: Any) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        for key in [k for k, (exp, _) in self._store.items() if now >= exp]:
            self._store.pop(key, None)
