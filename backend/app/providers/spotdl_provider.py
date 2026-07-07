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

    # Spotify app credentials (env or set at runtime from Settings). When present, spotdl is told to
    # use the official Spotify API for better track resolution; otherwise it uses its keyless default.
    _spotify_creds: dict | None = None

    def set_spotify_credentials(self, creds: dict | None) -> None:
        self._spotify_creds = creds or None

    def _spotify_id_secret(self) -> tuple[str | None, str | None]:
        creds = self._spotify_creds or {}
        cid = creds.get("client_id") or self.settings.spotify_client_id
        secret = creds.get("client_secret") or self.settings.spotify_client_secret
        return cid, secret

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
        self,
        track: TrackRef,
        *,
        quality: Quality,
        dest_dir: str,
        job_id: str,
        filename: str | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        fmt = self.settings.default_format
        bitrate = self.settings.default_bitrate
        name_tpl = f"{filename}.{{output-ext}}" if filename else "{artists} - {title}.{output-ext}"
        output_tpl = os.path.join(dest_dir, name_tpl)
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
        # With Spotify credentials, prefer the official API (better matches; recent spotdl defaults
        # to a reduced keyless client otherwise).
        cid, secret = self._spotify_id_secret()
        if cid and secret:
            cmd += ["--use-official-api", "--client-id", cid, "--client-secret", secret]

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
