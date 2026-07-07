"""Shared enqueue path.

Both the web API (:mod:`routes_downloads`) and the chat bots create download jobs the same way —
one ``jobs`` row per track, then a push onto the in-memory queue. Centralising it here keeps the
``origin`` bookkeeping (web | telegram | matrix) in one place so the UI can badge bot-queued items.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.models import Job
from backend.app.downloads.queue import DownloadQueue
from backend.app.navidrome.matcher import norm
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

    @property
    def dedup_key(self) -> tuple:
        """Identity used to skip a track already queued/running for the same provider."""
        isrc = (self.track.get("isrc") or "").strip().upper()
        if isrc:
            return (self.provider, "isrc", isrc)
        return (
            self.provider,
            norm(self.track.get("artist")),
            norm(self.track.get("title")),
            norm(self.track.get("album") or ""),
        )


@dataclass
class EnqueueSkip:
    label: str
    reason: str  # currently only "duplicate" (already queued/running)


@dataclass
class EnqueueResult:
    queued: list[Job] = field(default_factory=list)
    skipped: list[EnqueueSkip] = field(default_factory=list)


def _job_dedup_key(job: Job) -> tuple | None:
    try:
        track = json.loads(job.track_json or "{}")
    except (ValueError, TypeError):
        return None
    return EnqueueItem(provider=job.provider or "", quality=0, track=track).dedup_key


async def enqueue_tracks(
    session: AsyncSession,
    queue: DownloadQueue,
    registry: ProviderRegistry,
    settings: Settings,
    items: list[EnqueueItem],
    *,
    origin: str = "web",
    origin_chat: str | None = None,
) -> EnqueueResult:
    """Validate providers, persist one queued ``Job`` per item, and push them onto the queue.

    Skips any track that already has a queued/running job for the same provider (double-click /
    re-queue guard) — those are returned in ``EnqueueResult.skipped`` rather than duplicated.
    ``origin_chat`` (a bot chat/room id) is stored on each job so the terminal-status ping can be
    routed after a restart. Raises :class:`EnqueueError` if any provider is unknown or disabled
    (nothing is queued then).
    """
    if not items:
        raise EnqueueError("No items to download")

    for item in items:
        provider = registry.get(item.provider)
        if provider is None:
            raise EnqueueError(f"Unknown provider '{item.provider}'")
        if not provider.enabled:
            raise EnqueueError(f"Provider '{item.provider}' is not enabled (missing credentials)")

    # Keys already in flight, so a re-submit of the same track doesn't spawn a second download.
    active = await session.execute(
        select(Job).where(Job.kind == "download", Job.status.in_(("queued", "running")))
    )
    active_keys = {k for j in active.scalars() if (k := _job_dedup_key(j)) is not None}

    result = EnqueueResult()
    seen: set[tuple] = set()
    to_queue: list[EnqueueItem] = []
    for item in items:
        key = item.dedup_key
        if key in active_keys or key in seen:
            result.skipped.append(EnqueueSkip(label=item.label, reason="duplicate"))
            continue
        seen.add(key)
        to_queue.append(item)

    if not to_queue:
        return result

    batch_id = str(uuid4()) if len(to_queue) > 1 else None
    for item in to_queue:
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
            origin_chat=origin_chat,
        )
        session.add(job)
        result.queued.append(job)

    await session.commit()
    for job in result.queued:
        await queue.put(job.id)
    return result
