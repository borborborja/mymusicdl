"""Search / album response DTOs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QualityOptionDTO(BaseModel):
    tier: int
    label: str
    lossless: bool
    fmt: str
    bitrate_kbps: int | None = None
    note: str | None = None


class ProviderQualitiesDTO(BaseModel):
    provider: str
    label: str
    qualities: list[QualityOptionDTO] = Field(default_factory=list)


class LibraryMatchDTO(BaseModel):
    in_library: bool = False
    navidrome_id: str | None = None
    quality: QualityOptionDTO | None = None
    can_upgrade: bool = False  # in library, but a better tier is downloadable


class TrackResultDTO(BaseModel):
    title: str
    artist: str
    album: str | None = None
    source_url: str | None = None
    isrc: str | None = None
    duration_s: int | None = None
    cover_url: str | None = None
    ext_ids: dict[str, str] = Field(default_factory=dict)
    providers: list[ProviderQualitiesDTO] = Field(default_factory=list)
    library: LibraryMatchDTO = Field(default_factory=LibraryMatchDTO)
    best_tier: int | None = None


class AlbumResultDTO(BaseModel):
    id: str
    title: str
    artist: str
    provider: str
    year: int | None = None
    cover_url: str | None = None
    total_tracks: int | None = None


class ArtistResultDTO(BaseModel):
    id: str
    name: str
    provider: str
    cover_url: str | None = None


class SearchResponseDTO(BaseModel):
    kind: str
    tracks: list[TrackResultDTO] = Field(default_factory=list)
    albums: list[AlbumResultDTO] = Field(default_factory=list)
    artists: list[ArtistResultDTO] = Field(default_factory=list)


class AlbumDetailDTO(BaseModel):
    album: AlbumResultDTO
    tracks: list[TrackResultDTO] = Field(default_factory=list)
