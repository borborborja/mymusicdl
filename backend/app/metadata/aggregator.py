"""Search aggregator.

Ties the catalog (Spotify → MusicBrainz) to the download providers: for every track it attaches the
qualities each enabled provider can deliver, plus the Navidrome library match (already-downloaded +
at what quality, and whether a better tier is available).
"""
from __future__ import annotations

import asyncio

from backend.app.config import Settings
from backend.app.logging import get_logger
from backend.app.metadata.base import MetadataProvider
from backend.app.metadata.musicbrainz import MusicBrainzMetadata
from backend.app.metadata.spotify import SpotifyMetadata
from backend.app.navidrome.matcher import library_quality
from backend.app.providers.base import Quality, TrackRef
from backend.app.providers.registry import ProviderRegistry
from backend.app.schemas.search import (
    AlbumDetailDTO,
    AlbumResultDTO,
    ArtistResultDTO,
    LibraryMatchDTO,
    ProviderQualitiesDTO,
    QualityOptionDTO,
    SearchResponseDTO,
    TrackResultDTO,
)

log = get_logger(__name__)


class SearchAggregator:
    def __init__(
        self, *, settings: Settings, registry: ProviderRegistry, navidrome, session_factory
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.navidrome = navidrome
        self.session_factory = session_factory
        self._spotify = SpotifyMetadata(settings)
        self._musicbrainz = MusicBrainzMetadata(settings)

    # ── metadata source selection ──
    def _active_metadata(self) -> MetadataProvider:
        return self._spotify if self._spotify.enabled else self._musicbrainz

    def _metadata_by_name(self, name: str | None) -> MetadataProvider:
        if name == "spotify" and self._spotify.enabled:
            return self._spotify
        if name == "musicbrainz":
            return self._musicbrainz
        return self._active_metadata()

    def metadata_name(self) -> str:
        return self._active_metadata().name

    # ── decoration ──
    async def _decorate(
        self, track: TrackRef, providers_filter: set[str] | None, lossless_only: bool
    ) -> TrackResultDTO | None:
        enabled = self.registry.enabled()
        if providers_filter:
            enabled = [p for p in enabled if p.id in providers_filter]

        provider_dtos: list[ProviderQualitiesDTO] = []
        best_tier: int | None = None
        for p in enabled:
            try:
                qualities = await p.get_qualities(track)
            except Exception:
                continue
            if not qualities:
                continue
            provider_dtos.append(
                ProviderQualitiesDTO(
                    provider=p.id,
                    label=p.label,
                    qualities=[QualityOptionDTO(**q.to_dict()) for q in qualities],
                )
            )
            for q in qualities:
                best_tier = max(best_tier or 0, int(q.quality))

        if lossless_only and (best_tier is None or best_tier < int(Quality.FLAC_16)):
            return None

        library = LibraryMatchDTO()
        match = await library_quality(
            self.navidrome,
            artist=track.artist,
            title=track.title,
            album=track.album,
            duration_s=track.duration_s,
        )
        if match:
            qdto = QualityOptionDTO(**match["quality"].to_dict())
            library = LibraryMatchDTO(
                in_library=True,
                navidrome_id=match.get("navidrome_id"),
                quality=qdto,
                can_upgrade=best_tier is not None and qdto.tier < best_tier,
            )

        return TrackResultDTO(
            title=track.title,
            artist=track.artist,
            album=track.album,
            source_url=track.source_url,
            isrc=track.isrc,
            duration_s=track.duration_s,
            cover_url=track.cover_url,
            ext_ids=track.ext_ids,
            providers=provider_dtos,
            library=library,
            best_tier=best_tier,
        )

    async def _decorate_many(
        self, tracks: list[TrackRef], providers_filter: set[str] | None, lossless_only: bool
    ) -> list[TrackResultDTO]:
        decorated = await asyncio.gather(
            *(self._decorate(t, providers_filter, lossless_only) for t in tracks)
        )
        return [d for d in decorated if d is not None]

    # ── public API ──
    async def search(
        self,
        *,
        kind: str,
        query: str,
        limit: int = 20,
        providers_filter: set[str] | None = None,
        lossless_only: bool = False,
    ) -> SearchResponseDTO:
        md = self._active_metadata()
        kind = kind.lower()
        if kind == "song":
            tracks = await md.search_tracks(query, limit)
            return SearchResponseDTO(
                kind="song",
                tracks=await self._decorate_many(tracks, providers_filter, lossless_only),
            )
        if kind == "album":
            albums = await md.search_albums(query, limit)
            return SearchResponseDTO(
                kind="album",
                albums=[
                    AlbumResultDTO(
                        id=a.id,
                        title=a.title,
                        artist=a.artist,
                        provider=a.provider,
                        year=a.year,
                        cover_url=a.cover_url,
                        total_tracks=a.total_tracks,
                    )
                    for a in albums
                ],
            )
        if kind == "artist":
            artists = await md.search_artists(query, limit)
            return SearchResponseDTO(
                kind="artist",
                artists=[
                    ArtistResultDTO(id=a.id, name=a.name, provider=a.provider, cover_url=a.cover_url)
                    for a in artists
                ],
            )
        raise ValueError(f"Unknown search kind: {kind}")

    async def get_album(
        self,
        provider: str,
        album_id: str,
        *,
        providers_filter: set[str] | None = None,
        lossless_only: bool = False,
    ) -> AlbumDetailDTO | None:
        md = self._metadata_by_name(provider)
        album_ref, tracks = await md.get_album_tracks(album_id)
        if album_ref is None:
            return None
        return AlbumDetailDTO(
            album=AlbumResultDTO(
                id=album_ref.id,
                title=album_ref.title,
                artist=album_ref.artist,
                provider=album_ref.provider,
                year=album_ref.year,
                cover_url=album_ref.cover_url,
                total_tracks=album_ref.total_tracks or len(tracks),
            ),
            tracks=await self._decorate_many(tracks, providers_filter, lossless_only),
        )
