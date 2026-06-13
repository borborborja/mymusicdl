"""Metadata/catalog provider contract.

The catalog search is decoupled from the download providers: Spotify (or MusicBrainz) supplies the
canonical artist/album/track identity; the download providers then say which qualities they can
deliver for each track.
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from backend.app.providers.base import TrackRef


@dataclass
class AlbumRef:
    id: str
    title: str
    artist: str
    provider: str
    year: int | None = None
    cover_url: str | None = None
    total_tracks: int | None = None


@dataclass
class ArtistRef:
    id: str
    name: str
    provider: str
    cover_url: str | None = None


class MetadataProvider(ABC):
    name: str = "base"

    @property
    def enabled(self) -> bool:
        return True

    async def search_tracks(self, query: str, limit: int = 20) -> list[TrackRef]:
        return []

    async def search_albums(self, query: str, limit: int = 20) -> list[AlbumRef]:
        return []

    async def search_artists(self, query: str, limit: int = 20) -> list[ArtistRef]:
        return []

    async def get_album_tracks(self, album_id: str) -> tuple[AlbumRef | None, list[TrackRef]]:
        return None, []

    async def aclose(self) -> None:
        return None
