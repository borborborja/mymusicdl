"""streamrip providers — PAID, stub-but-ready (Tidal / Qobuz / Deezer).

These adapters are structurally complete but stay DISABLED until credentials exist (env
TIDAL_TOKEN / QOBUZ_TOKEN / DEEZER_ARL, or a row in the credentials table set via Settings). With
no credentials the registry hides them; with credentials they surface in search + quality badges.

Full activation note (TODO when you actually subscribe): streamrip reads its tokens and the
download folder from ``~/.config/streamrip/config.toml``. To make downloads land in ``dest_dir`` and
authenticate non-interactively, the app should template that config per job (inject the token and
set ``downloads.folder = dest_dir``) and pass ``--config-path``. Until then a configured streamrip
on the host works; an unconfigured one will raise a clear SubprocessError — which is expected.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from backend.app.downloads.runner import stream_subprocess
from backend.app.providers.base import ProgressEvent, Provider, Quality, QualityOption, TrackRef

_FMT_FOR = {
    Quality.MP3_128: "mp3",
    Quality.MP3_320: "mp3",
    Quality.FLAC_16: "flac",
    Quality.HIRES_96: "flac",
    Quality.HIRES_192: "flac",
}


def _ladder(max_quality: Quality) -> list[QualityOption]:
    tiers = [Quality.MP3_320, Quality.FLAC_16, Quality.HIRES_96, Quality.HIRES_192]
    out: list[QualityOption] = []
    for t in tiers:
        if t <= max_quality:
            out.append(QualityOption(quality=t, fmt=_FMT_FOR[t]))
    return out


class StreamripProvider(Provider):
    requires_credentials = True
    source: str = ""  # "tidal" | "qobuz" | "deezer"
    max_quality: Quality = Quality.FLAC_16

    async def get_qualities(self, track: TrackRef) -> list[QualityOption]:
        return _ladder(self.max_quality)

    async def download(
        self,
        track: TrackRef,
        *,
        quality: Quality,
        dest_dir: str,
        job_id: str,
        filename: str | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        if not self.enabled:
            raise RuntimeError(f"{self.label} is not configured (no credentials)")
        effective = Quality(min(int(quality), int(self.max_quality)))
        cmd = [
            self.settings.tool_bin("rip"),
            "--quality",
            str(int(effective)),
            "url",
            track.query,
        ]

        def parse(line: str) -> ProgressEvent | None:
            low = line.lower()
            if "%" in line:
                return ProgressEvent(job_id=job_id, stage="downloading", message=line)
            if "completed" in low or "downloaded" in low or "tagging" in low:
                return ProgressEvent(job_id=job_id, stage="tagging", message=line)
            if "error" in low or "fail" in low:
                return ProgressEvent(job_id=job_id, stage="downloading", message=line)
            return None

        yield ProgressEvent(job_id=job_id, stage="resolving", message=f"Resolving with {self.label}…")
        async for ev in stream_subprocess(cmd, job_id=job_id, parse=parse, settings=self.settings):
            yield ev


class TidalProvider(StreamripProvider):
    id = "tidal"
    label = "Tidal (streamrip)"
    source = "tidal"
    max_quality = Quality.HIRES_96  # Tidal HiRes/MQA ≈ tier 3


class QobuzProvider(StreamripProvider):
    id = "qobuz"
    label = "Qobuz (streamrip)"
    source = "qobuz"
    max_quality = Quality.HIRES_192  # up to 24/192


class DeezerProvider(StreamripProvider):
    id = "deezer"
    label = "Deezer (streamrip)"
    source = "deezer"
    max_quality = Quality.FLAC_16  # CD-quality FLAC
