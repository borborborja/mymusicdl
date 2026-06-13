"""spotDL provider — FREE, implemented.

Resolves Spotify metadata and downloads the audio from YouTube Music, embedding rich tags. Lossy
only (the target format/bitrate is configurable). Great single-track tagging.
"""
from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator

from backend.app.downloads.runner import stream_subprocess
from backend.app.providers.base import ProgressEvent, Provider, Quality, QualityOption, TrackRef

_BITRATE_RE = re.compile(r"(\d+)")
_NOTABLE = ("processing", "found", "downloading", "downloaded", "skipping", "converting", "error")


def _bitrate_kbps(bitrate: str) -> int | None:
    m = _BITRATE_RE.search(bitrate or "")
    return int(m.group(1)) if m else None


class SpotdlProvider(Provider):
    id = "spotdl"
    label = "spotDL (Spotify → YouTube Music)"
    requires_credentials = False

    async def get_qualities(self, track: TrackRef) -> list[QualityOption]:
        fmt = self.settings.default_format
        return [
            QualityOption(
                quality=Quality.MP3_320,
                fmt=fmt,
                bitrate_kbps=_bitrate_kbps(self.settings.default_bitrate),
                note="lossy via YouTube Music",
            )
        ]

    async def download(
        self, track: TrackRef, *, quality: Quality, dest_dir: str, job_id: str
    ) -> AsyncIterator[ProgressEvent]:
        fmt = self.settings.default_format
        bitrate = self.settings.default_bitrate
        output_tpl = os.path.join(dest_dir, "{artists} - {title}.{output-ext}")
        cmd = [
            self.settings.tool_bin("spotdl"),
            "download",
            track.query,
            "--output",
            output_tpl,
            "--format",
            fmt,
            "--bitrate",
            bitrate,
            "--print-errors",
        ]

        def parse(line: str) -> ProgressEvent | None:
            low = line.lower()
            if not any(k in low for k in _NOTABLE):
                return None
            if "downloaded" in low or "converting" in low:
                stage = "tagging"
            elif "processing" in low or "found" in low:
                stage = "resolving"
            else:
                stage = "downloading"
            return ProgressEvent(job_id=job_id, stage=stage, message=line)

        yield ProgressEvent(job_id=job_id, stage="resolving", message="Resolving with spotDL…")
        async for ev in stream_subprocess(cmd, job_id=job_id, parse=parse, settings=self.settings):
            yield ev
