"""yt-dlp provider — FREE, implemented.

Universal fallback: extracts audio (from a URL, or a ``ytsearch1:`` query) and re-encodes to the
configured format, embedding metadata + thumbnail. Lossy.
"""
from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator

from backend.app.downloads.runner import stream_subprocess
from backend.app.providers.base import ProgressEvent, Provider, Quality, QualityOption, TrackRef

# Rendered by --progress-template "download:DLP|<pct>|<speed>|<eta>"
_PCT_RE = re.compile(r"([\d.]+)%")


def _parse_pct(token: str) -> float | None:
    m = _PCT_RE.search(token)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def _parse_eta(token: str) -> int | None:
    token = token.strip()
    if not token or token.upper() == "NA" or ":" not in token:
        return None
    try:
        parts = [int(p) for p in token.split(":")]
    except ValueError:
        return None
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


class YtdlpProvider(Provider):
    id = "ytdlp"
    label = "yt-dlp"
    requires_credentials = False

    async def get_qualities(self, track: TrackRef) -> list[QualityOption]:
        return [
            QualityOption(
                quality=Quality.MP3_320,
                fmt=self.settings.default_format,
                bitrate_kbps=320,
                note="lossy, re-encoded from best audio",
            )
        ]

    async def download(
        self,
        track: TrackRef,
        *,
        quality: Quality,
        dest_dir: str,
        job_id: str,
        filename: str | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        # Only follow a *YouTube* URL; a Spotify/MusicBrainz URL would break yt-dlp, so search instead.
        url = track.source_url or ""
        is_youtube = any(d in url for d in ("youtube.com", "youtu.be"))
        target = url if is_youtube else f"ytsearch1:{track.artist} {track.title}"
        name_tpl = f"{filename}.%(ext)s" if filename else "%(artist)s - %(title)s.%(ext)s"
        output_tpl = os.path.join(dest_dir, name_tpl)
        cmd = [
            self.settings.tool_bin("yt-dlp"),
            "-x",
            "--audio-format",
            self.settings.default_format,
            "--audio-quality",
            "0",
            "--embed-metadata",
            "--embed-thumbnail",
            "--no-playlist",
            "--newline",
            "--no-colors",
            "--progress-template",
            "download:DLP|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "-o",
            output_tpl,
            target,
        ]

        def parse(line: str) -> ProgressEvent | None:
            if line.startswith("DLP|"):
                parts = line.split("|")
                pct = _parse_pct(parts[1]) if len(parts) > 1 else None
                speed = parts[2].strip() if len(parts) > 2 else None
                eta = _parse_eta(parts[3]) if len(parts) > 3 else None
                return ProgressEvent(
                    job_id=job_id, stage="downloading", pct=pct, speed=speed, eta_s=eta
                )
            if "[ExtractAudio]" in line or "[Metadata]" in line or "[EmbedThumbnail]" in line:
                return ProgressEvent(job_id=job_id, stage="tagging", message=line)
            return None

        yield ProgressEvent(job_id=job_id, stage="resolving", message="Resolving with yt-dlp…")
        async for ev in stream_subprocess(cmd, job_id=job_id, parse=parse, settings=self.settings):
            yield ev
