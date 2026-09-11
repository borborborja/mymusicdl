"""Stable, source-qualified music identities shared by discovery and family preferences."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.schemas.jobs import TrackRefIn


def iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def mbid(value) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


class CollectionTrack(TrackRefIn):
    title: str = Field(min_length=1, max_length=512)
    artist: str = Field(min_length=1, max_length=512)
    catalog_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=512)
    seed_id: str | None = None

    def identity(self) -> str:
        recording = mbid(self.ext_ids.get("mbid"))
        if recording:
            return digest(f"recording:{recording}")
        if self.catalog_id:
            return self.catalog_id
        # Preserve provider IDs, edition, duration and URL. Never merge on artist/title alone.
        return digest(json.dumps(self.model_dump(exclude={"reason", "seed_id"}), sort_keys=True))


class PreferenceChange(BaseModel):
    track: CollectionTrack
    saved: bool | None = None
    favorite: bool | None = None
    dismissed: bool | None = None


class ArtistChoice(BaseModel):
    id: UUID
    name: str = Field(min_length=1, max_length=512)


class DownloadChoice(BaseModel):
    provider: str = "ytdlp"
    quality: int = Field(default=1, ge=0, le=4)
