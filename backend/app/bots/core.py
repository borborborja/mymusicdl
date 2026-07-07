"""Shared bot brain.

Platform-agnostic logic the Telegram/Matrix adapters reuse: run a catalog search (songs or albums),
pick the best downloadable source for a track, and enqueue it (tagged with the bot's ``origin`` and
the chat id so a terminal-status ping survives a restart). It also persists each chat's last results
in the DB so "reply with N" keeps working after the process restarts. The adapters own only the
chat-specific formatting and transport.
"""

from __future__ import annotations

import json

from backend.app.config import Settings
from backend.app.db.models import BotSelection
from backend.app.downloads.service import EnqueueItem, enqueue_tracks
from backend.app.logging import get_logger

log = get_logger(__name__)

MAX_RESULTS = 20


def split_limit(text: str, default: int) -> tuple[str, int]:
    """Pull an optional trailing result count off a query (``creep 10`` → ("creep", 10))."""
    parts = text.split()
    if len(parts) >= 2 and parts[-1].isdigit():
        n = int(parts[-1])
        if 1 <= n <= MAX_RESULTS:
            return " ".join(parts[:-1]), n
    return text, default


class BotCore:
    def __init__(self, *, aggregator, registry, settings: Settings, queue, session_factory) -> None:
        self.aggregator = aggregator
        self.registry = registry
        self.settings = settings
        self.queue = queue
        self.session_factory = session_factory

    # ── search ──
    async def search_songs(self, query: str, limit: int = 6) -> list:
        """Decorated track results (each carries providers/qualities + library match).

        ``Artista - Canción`` messages become a fielded search (artist + title).
        """
        artist: str | None = None
        if " - " in query:
            artist, _, query = (part.strip() for part in query.partition(" - "))
        resp = await self.aggregator.search(kind="song", query=query, artist=artist, limit=limit)
        return resp.tracks

    async def search_albums(self, query: str, limit: int = 6) -> list:
        """Album results for the album flow. Supports the ``Artista - Álbum`` shorthand too."""
        artist: str | None = None
        if " - " in query:
            artist, _, query = (part.strip() for part in query.partition(" - "))
        resp = await self.aggregator.search(kind="album", query=query, artist=artist, limit=limit)
        return resp.albums

    # ── serialization for persisted selections ──
    @staticmethod
    def song_item(track) -> dict:
        """A decorated track reduced to what enqueue needs, plus library flags for display."""
        options = [
            {"provider": p.provider, "tier": q.tier} for p in track.providers for q in p.qualities
        ]
        lib = track.library
        return {
            "label": f"{track.artist} — {track.title}".strip(" —"),
            "album": track.album,
            "payload": {
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "source_url": track.source_url,
                "isrc": track.isrc,
                "duration_s": track.duration_s,
                "cover_url": track.cover_url,
                "ext_ids": track.ext_ids,
            },
            "options": options,
            "in_library": bool(lib and lib.in_library),
            "can_upgrade": bool(lib and lib.can_upgrade),
        }

    @staticmethod
    def album_item(album) -> dict:
        return {
            "provider": album.provider,
            "id": album.id,
            "label": f"{album.artist} — {album.title}".strip(" —"),
            "year": album.year,
            "total_tracks": album.total_tracks,
        }

    @staticmethod
    def _best_option(options: list[dict]) -> dict | None:
        """Highest-tier (provider, tier) among a song item's options."""
        return max(options, key=lambda o: o["tier"], default=None) if options else None

    # ── persisted selection (survives restart) ──
    async def save_selection(
        self, platform: str, chat_id: str, mode: str, items: list[dict]
    ) -> None:
        payload = json.dumps({"mode": mode, "items": items})
        async with self.session_factory() as session:
            row = await session.get(BotSelection, (platform, chat_id))
            if row is None:
                session.add(BotSelection(platform=platform, chat_id=chat_id, payload=payload))
            else:
                row.payload = payload
            await session.commit()

    async def load_selection(self, platform: str, chat_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = await session.get(BotSelection, (platform, chat_id))
            if row is None:
                return None
            try:
                return json.loads(row.payload)
            except (ValueError, TypeError):
                return None

    # ── enqueue ──
    async def _enqueue(self, items: list[EnqueueItem], *, origin: str, origin_chat: str | None):
        async with self.session_factory() as session:
            return await enqueue_tracks(
                session,
                self.queue,
                self.registry,
                self.settings,
                items,
                origin=origin,
                origin_chat=origin_chat,
            )

    async def enqueue_song_item(self, item: dict, *, origin: str, chat_id: str):
        """Queue one persisted song item (best available source). Returns the Job, or None."""
        opt = self._best_option(item.get("options") or [])
        if opt is None:
            return None
        enq = EnqueueItem(
            provider=opt["provider"], quality=opt["tier"], track=dict(item["payload"])
        )
        jobs = await self._enqueue([enq], origin=origin, origin_chat=chat_id)
        return jobs[0] if jobs else None

    async def enqueue_album(self, provider: str, album_id: str, *, origin: str) -> int:
        """Queue every track of an album individually (best source each). Returns count queued.

        Album batches don't set ``origin_chat`` — the chat gets one "N queued" message up front
        instead of N terminal pings.
        """
        detail = await self.aggregator.get_album(provider, album_id)
        if detail is None:
            return 0
        items: list[EnqueueItem] = []
        for track in detail.tracks:
            si = self.song_item(track)
            opt = self._best_option(si["options"])
            if opt is None:
                continue
            items.append(
                EnqueueItem(provider=opt["provider"], quality=opt["tier"], track=si["payload"])
            )
        if not items:
            return 0
        jobs = await self._enqueue(items, origin=origin, origin_chat=None)
        return len(jobs)
