"""Provider abstraction — the linchpin of the pluggable download design.

Every source (free: spotdl, yt-dlp; paid: Tidal/Qobuz/Deezer via streamrip, tiddl) implements the
same small interface. A provider that ``requires_credentials`` stays ``enabled == False`` until
credentials are supplied, and the registry simply hides disabled providers from search/quality
aggregation. Turning a paid source on is therefore "add a credential", not "write code".
"""
from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import IntEnum


class Quality(IntEnum):
    """Mirrors streamrip's quality tiers so paid sources map 1:1."""

    MP3_128 = 0
    MP3_320 = 1
    FLAC_16 = 2  # FLAC 16-bit / 44.1 kHz (CD)
    HIRES_96 = 3  # 24-bit / ≤96 kHz
    HIRES_192 = 4  # 24-bit / ≤192 kHz

    @property
    def label(self) -> str:
        return {
            0: "MP3 128",
            1: "MP3 320",
            2: "FLAC 16/44.1",
            3: "Hi-Res 24/96",
            4: "Hi-Res 24/192",
        }[int(self)]

    @property
    def lossless(self) -> bool:
        return self >= Quality.FLAC_16


@dataclass(frozen=True)
class TrackRef:
    """Provider-agnostic identity of a single track to fetch."""

    provider_id: str
    title: str
    artist: str
    album: str | None = None
    source_url: str | None = None
    isrc: str | None = None
    duration_s: int | None = None
    cover_url: str | None = None
    ext_ids: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrackRef":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def query(self) -> str:
        return self.source_url or f"{self.artist} - {self.title}"


@dataclass(frozen=True)
class QualityOption:
    quality: Quality
    fmt: str  # "mp3" | "flac" | "m4a" | "opus"
    bitrate_kbps: int | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "tier": int(self.quality),
            "label": self.quality.label,
            "lossless": self.quality.lossless,
            "fmt": self.fmt,
            "bitrate_kbps": self.bitrate_kbps,
            "note": self.note,
        }


@dataclass
class SearchHit:
    """One provider's view of a track plus the qualities it can deliver."""

    track: TrackRef
    qualities: list[QualityOption]


@dataclass
class ProgressEvent:
    job_id: str
    stage: str  # "resolving" | "downloading" | "tagging" | "done" | "error"
    pct: float | None = None  # 0..100
    speed: str | None = None
    eta_s: int | None = None
    message: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


class Provider(ABC):
    id: str
    label: str
    requires_credentials: bool = False
    # Default download format/bitrate when the source transcodes (free providers).
    default_quality: Quality = Quality.MP3_320

    def __init__(self, settings, creds: dict | None = None) -> None:
        self.settings = settings
        self._creds = creds or {}

    # ── lifecycle / capability ──
    @property
    def enabled(self) -> bool:
        if not self.requires_credentials:
            return True
        return bool(self._creds)

    def set_credentials(self, creds: dict | None) -> None:
        self._creds = creds or {}

    # ── catalog ──
    async def search(self, *, kind: str, query: str, limit: int = 20) -> list[SearchHit]:
        """Native catalog search. Free providers return [] and rely on the metadata layer;
        paid providers override this with their real catalog (which carries true qualities)."""
        return []

    @abstractmethod
    async def get_qualities(self, track: TrackRef) -> list[QualityOption]:
        """Best-effort downloadable tiers this provider can deliver for the given track."""

    @abstractmethod
    def download(
        self, track: TrackRef, *, quality: Quality, dest_dir: str, job_id: str
    ) -> AsyncIterator[ProgressEvent]:
        """Run the underlying CLI as a subprocess, yielding progress and writing a single,
        well-tagged audio file into ``dest_dir``. Implemented as an async generator."""
        raise NotImplementedError

    def info(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "requires_credentials": self.requires_credentials,
            "enabled": self.enabled,
        }
