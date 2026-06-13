"""tiddl provider — PAID, optional alternative Tidal backend (stub-but-ready).

``tiddl`` is the most actively-maintained Tidal-only downloader. It is NOT registered by default
(streamrip already covers Tidal); to prefer it, swap it into ``build_registry``. Disabled until a
Tidal credential is present.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from backend.app.downloads.runner import stream_subprocess
from backend.app.providers.base import ProgressEvent, Provider, Quality, QualityOption, TrackRef


class TiddlProvider(Provider):
    id = "tidal-tiddl"
    label = "Tidal (tiddl)"
    requires_credentials = True
    max_quality = Quality.HIRES_192  # tiddl MAX: 24-bit up to 192 kHz FLAC

    async def get_qualities(self, track: TrackRef) -> list[QualityOption]:
        return [
            QualityOption(quality=Quality.MP3_320, fmt="m4a"),
            QualityOption(quality=Quality.FLAC_16, fmt="flac"),
            QualityOption(quality=Quality.HIRES_192, fmt="flac", note="tiddl MAX"),
        ]

    async def download(
        self, track: TrackRef, *, quality: Quality, dest_dir: str, job_id: str
    ) -> AsyncIterator[ProgressEvent]:
        if not self.enabled:
            raise RuntimeError("tiddl is not configured (no Tidal credentials)")
        quality_arg = {
            Quality.MP3_128: "low",
            Quality.MP3_320: "normal",
            Quality.FLAC_16: "high",
            Quality.HIRES_96: "master",
            Quality.HIRES_192: "master",
        }[Quality(min(int(quality), int(self.max_quality)))]
        cmd = [self.settings.tool_bin("tiddl"), "url", track.query, "-q", quality_arg]

        def parse(line: str) -> ProgressEvent | None:
            low = line.lower()
            if "%" in line or "downloading" in low:
                return ProgressEvent(job_id=job_id, stage="downloading", message=line)
            if "saved" in low or "done" in low:
                return ProgressEvent(job_id=job_id, stage="tagging", message=line)
            return None

        yield ProgressEvent(job_id=job_id, stage="resolving", message="Resolving with tiddl…")
        async for ev in stream_subprocess(cmd, job_id=job_id, parse=parse, settings=self.settings):
            yield ev
