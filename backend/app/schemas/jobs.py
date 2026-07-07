"""Job / download request DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TrackRefIn(BaseModel):
    provider_id: str | None = None
    title: str
    artist: str
    album: str | None = None
    source_url: str | None = None
    isrc: str | None = None
    duration_s: int | None = None
    cover_url: str | None = None
    ext_ids: dict[str, str] = Field(default_factory=dict)


class DownloadItem(BaseModel):
    provider: str
    quality: int  # Quality tier 0..4
    track: TrackRefIn


class DownloadRequest(BaseModel):
    items: list[DownloadItem]


class JobDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    status: str
    provider: str | None = None
    requested_quality: int | None = None
    progress_pct: float = 0.0
    stage: str | None = None
    error: str | None = None
    result_path: str | None = None
    library_confirmed: bool | None = None
    batch_id: str | None = None
    title: str | None = None
    origin: str = "web"
    origin_chat: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
