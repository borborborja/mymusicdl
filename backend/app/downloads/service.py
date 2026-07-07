"""Shared enqueue path.

Both the web API (:mod:`routes_downloads`) and the chat bots create download jobs the same way —
one ``jobs`` row per track, then a push onto the in-memory queue. Centralising it here keeps the
``origin`` bookkeeping (web | telegram | matrix) in one place so the UI can badge bot-queued items.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.models import Job
from backend.app.downloads.queue import DownloadQueue
from backend.app.providers.registry import ProviderRegistry


class EnqueueError(Exception):
    """A requested download could not be queued (unknown / disabled provider)."""


@dataclass
class EnqueueItem:
    provider: str
    quality: int  # Quality tier 0..4
    track: dict  # serialized TrackRef (title, artist, album, source_url, isrc, cover_url, ext_ids…)

    @property
    def label(self) -> str:
        return f"{self.track.get('artist', '')} - {self.track.get('title', '')}".strip(" -")


async def enqueue_tracks(
    session: AsyncSession,
    queue: DownloadQueue,
    registry: ProviderRegistry,
    settings: Settings,
    items: list[EnqueueItem],
    *,
    origin: str = "web",
) -> list[Job]:
    """Validate providers, persist one queued ``Job`` per item, and push them onto the queue.

    Raises :class:`EnqueueError` if any provider is unknown or disabled (nothing is queued then).
    """
    if not items:
        raise EnqueueError("No items to download")

    for item in items:
        provider = registry.get(item.provider)
        if provider is None:
            raise EnqueueError(f"Unknown provider '{item.provider}'")
        if not provider.enabled:
            raise EnqueueError(f"Provider '{item.provider}' is not enabled (missing credentials)")

    batch_id = str(uuid4()) if len(items) > 1 else None
    jobs: list[Job] = []
    for item in items:
        track = dict(item.track)
        track.setdefault("provider_id", item.provider)
        job = Job(
            id=str(uuid4()),
            kind="download",
            status="queued",
            provider=item.provider,
            track_json=json.dumps(track),
            requested_quality=item.quality,
            dest_dir=settings.music_library_path,
            title=item.label or None,
            batch_id=batch_id,
            origin=origin,
        )
        session.add(job)
        jobs.append(job)

    await session.commit()
    for job in jobs:
        await queue.put(job.id)
    return jobs
