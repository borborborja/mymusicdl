"""Post-download bookkeeping: record what we downloaded (and at what quality) and ask Navidrome to
rescan so the file shows up in the library."""
from __future__ import annotations

import os
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.db.base import utcnow
from backend.app.db.models import LibraryItem
from backend.app.logging import get_logger
from backend.app.providers.base import Quality, TrackRef

log = get_logger(__name__)


def _bitrate_for(settings: Settings, quality: Quality) -> int | None:
    if quality in (Quality.MP3_128, Quality.MP3_320):
        m = re.search(r"\d+", settings.default_bitrate)
        return int(m.group()) if m else None
    return None  # lossless: bitrate is variable / not meaningful


async def record_download(
    session: AsyncSession,
    settings: Settings,
    navidrome,
    *,
    job,
    track: TrackRef,
    result_path: str | None,
    quality: Quality,
) -> None:
    fmt = (
        os.path.splitext(result_path)[1].lstrip(".").lower()
        if result_path
        else settings.default_format
    )
    size = (
        os.path.getsize(result_path)
        if result_path and os.path.exists(result_path)
        else None
    )

    existing = (
        await session.execute(
            select(LibraryItem).where(
                LibraryItem.artist == track.artist,
                LibraryItem.title == track.title,
                LibraryItem.album == track.album,
                LibraryItem.quality_tier == int(quality),
            )
        )
    ).scalar_one_or_none()

    fields = dict(
        file_path=result_path or "",
        fmt=fmt,
        bitrate_kbps=_bitrate_for(settings, quality),
        size_bytes=size,
        source_provider=job.provider or "",
        source_url=track.source_url,
        downloaded_at=utcnow(),
    )
    if existing is not None:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(
            LibraryItem(
                title=track.title,
                artist=track.artist,
                album=track.album,
                isrc=track.isrc,
                mbid=track.ext_ids.get("mbid"),
                quality_tier=int(quality),
                duration_s=track.duration_s,
                **fields,
            )
        )
    await session.commit()

    if navidrome is not None:
        try:
            await navidrome.start_scan()
            log.info("Triggered Navidrome rescan after %s", fields["file_path"])
        except Exception:
            log.warning("Navidrome rescan failed", exc_info=True)
