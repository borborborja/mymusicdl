"""Shared bot brain.

Platform-agnostic logic the Telegram/Matrix adapters reuse: run a catalog search, pick the best
downloadable source for a track, and enqueue it (tagged with the bot's ``origin``). The adapters
own only the chat-specific formatting and transport.
"""
from __future__ import annotations

from backend.app.config import Settings
from backend.app.downloads.service import EnqueueItem, enqueue_tracks
from backend.app.logging import get_logger

log = get_logger(__name__)


class BotCore:
    def __init__(self, *, aggregator, registry, settings: Settings, queue, session_factory) -> None:
        self.aggregator = aggregator
        self.registry = registry
        self.settings = settings
        self.queue = queue
        self.session_factory = session_factory

    async def search_songs(self, query: str, limit: int = 6) -> list:
        """Return decorated track results (each carries the providers/qualities available)."""
        resp = await self.aggregator.search(kind="song", query=query, limit=limit)
        return resp.tracks

    @staticmethod
    def _best_item(track) -> EnqueueItem | None:
        """Highest-tier (provider, quality) offered for this track, as an enqueue item."""
        best: tuple[int, str] | None = None
        for p in track.providers:
            for q in p.qualities:
                if best is None or q.tier > best[0]:
                    best = (q.tier, p.provider)
        if best is None:
            return None
        payload = {
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "source_url": track.source_url,
            "isrc": track.isrc,
            "duration_s": track.duration_s,
            "cover_url": track.cover_url,
            "ext_ids": track.ext_ids,
        }
        return EnqueueItem(provider=best[1], quality=best[0], track=payload)

    async def enqueue_one(self, track, *, origin: str):
        """Queue the best available source for ``track``. Returns the Job, or None if no source."""
        item = self._best_item(track)
        if item is None:
            return None
        async with self.session_factory() as session:
            jobs = await enqueue_tracks(
                session, self.queue, self.registry, self.settings, [item], origin=origin
            )
        return jobs[0] if jobs else None
