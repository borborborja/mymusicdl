"""MusicBrainz metadata — keyless fallback when Spotify credentials are absent.

No audio URLs (MB is a metadata DB), so downloads fall back to search-by-name (spotdl/yt-dlp resolve
"artist - title"). MB asks for a descriptive User-Agent and ~1 req/s; fine for interactive use.
"""
from __future__ import annotations

import httpx

from backend.app.logging import get_logger
from backend.app.metadata.base import AlbumRef, ArtistRef, MetadataProvider
from backend.app.providers.base import TrackRef

log = get_logger(__name__)

_BASE = "https://musicbrainz.org/ws/2"
_UA = "mymusicdl/0.1 (https://github.com/; self-hosted family music tool)"


class MusicBrainzMetadata(MetadataProvider):
    name = "musicbrainz"

    def __init__(self, settings=None) -> None:
        self._http = httpx.AsyncClient(
            timeout=12.0, headers={"User-Agent": _UA, "Accept": "application/json"}
        )

    async def _get(self, path: str, params: dict) -> dict:
        params = {**params, "fmt": "json"}
        resp = await self._http.get(f"{_BASE}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _artist_credit(obj: dict) -> str:
        ac = obj.get("artist-credit") or []
        return ac[0]["name"] if ac else ""

    async def search_tracks(self, query: str, limit: int = 20) -> list[TrackRef]:
        data = await self._get("/recording", {"query": query, "limit": limit})
        out: list[TrackRef] = []
        for rec in data.get("recordings", []) or []:
            releases = rec.get("releases") or []
            album = releases[0].get("title") if releases else None
            length = rec.get("length")
            out.append(
                TrackRef(
                    provider_id=None,
                    title=rec.get("title", ""),
                    artist=self._artist_credit(rec),
                    album=album,
                    source_url=None,
                    isrc=(rec.get("isrcs") or [None])[0],
                    duration_s=int(length) // 1000 if length else None,
                    ext_ids={"mbid": rec["id"]} if rec.get("id") else {},
                )
            )
        return out

    async def search_albums(self, query: str, limit: int = 20) -> list[AlbumRef]:
        data = await self._get("/release-group", {"query": query, "limit": limit})
        out: list[AlbumRef] = []
        for rg in data.get("release-groups", []) or []:
            date = rg.get("first-release-date") or ""
            out.append(
                AlbumRef(
                    id=rg["id"],
                    title=rg.get("title", ""),
                    artist=self._artist_credit(rg),
                    provider=self.name,
                    year=int(date[:4]) if date[:4].isdigit() else None,
                )
            )
        return out

    async def search_artists(self, query: str, limit: int = 20) -> list[ArtistRef]:
        data = await self._get("/artist", {"query": query, "limit": limit})
        return [
            ArtistRef(id=a["id"], name=a.get("name", ""), provider=self.name)
            for a in (data.get("artists", []) or [])
        ]

    async def get_album_tracks(self, album_id: str) -> tuple[AlbumRef | None, list[TrackRef]]:
        # album_id is a release-group id; fetch one release with its recordings.
        data = await self._get(
            "/release",
            {"release-group": album_id, "inc": "recordings+artist-credits", "limit": 1},
        )
        releases = data.get("releases") or []
        if not releases:
            return None, []
        rel = releases[0]
        ref = AlbumRef(
            id=album_id,
            title=rel.get("title", ""),
            artist=self._artist_credit(rel),
            provider=self.name,
        )
        tracks: list[TrackRef] = []
        for medium in rel.get("media") or []:
            for tr in medium.get("tracks") or []:
                length = tr.get("length")
                tracks.append(
                    TrackRef(
                        provider_id=None,
                        title=tr.get("title", ""),
                        artist=self._artist_credit(rel),
                        album=rel.get("title"),
                        duration_s=int(length) // 1000 if length else None,
                    )
                )
        return ref, tracks

    async def aclose(self) -> None:
        await self._http.aclose()
