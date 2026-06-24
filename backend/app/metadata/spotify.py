"""Spotify Web API metadata (client-credentials grant — no user login).

This is what spotdl resolves against, so results map 1:1 to what spotdl can download. The track
``source_url`` is the Spotify URL (spotdl consumes it directly; yt-dlp ignores it and searches).
"""
from __future__ import annotations

import base64
import time

import httpx

from backend.app.config import Settings
from backend.app.logging import get_logger
from backend.app.metadata.base import AlbumRef, ArtistRef, MetadataProvider
from backend.app.providers.base import TrackRef

log = get_logger(__name__)

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API = "https://api.spotify.com/v1"


class SpotifyMetadata(MetadataProvider):
    name = "spotify"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=12.0)
        self._token: str | None = None
        self._token_exp: float = 0.0
        # Runtime overrides (set via Settings UI) take precedence over the env-configured values.
        self._client_id: str | None = settings.spotify_client_id
        self._client_secret: str | None = settings.spotify_client_secret

    def set_credentials(self, creds: dict | None) -> None:
        """Apply (or clear) Spotify credentials at runtime, invalidating the cached token."""
        if creds:
            self._client_id = creds.get("client_id") or self._client_id
            self._client_secret = creds.get("client_secret") or self._client_secret
        else:  # cleared → fall back to env config (disabled if none)
            self._client_id = self.settings.spotify_client_id
            self._client_secret = self.settings.spotify_client_secret
        self._token, self._token_exp = None, 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def _bearer(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        creds = f"{self._client_id}:{self._client_secret}"
        auth = base64.b64encode(creds.encode()).decode()
        resp = await self._http.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {auth}"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600)) - 30
        return self._token

    async def _get(self, path: str, params: dict) -> dict:
        token = await self._bearer()
        resp = await self._http.get(
            f"{_API}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json()

    # ── mapping ──
    @staticmethod
    def _track_from(item: dict, album: dict | None = None) -> TrackRef:
        album = album or item.get("album") or {}
        images = album.get("images") or []
        artists = item.get("artists") or []
        return TrackRef(
            provider_id=None,
            title=item.get("name", ""),
            artist=artists[0]["name"] if artists else "",
            album=album.get("name"),
            source_url=(item.get("external_urls") or {}).get("spotify"),
            isrc=(item.get("external_ids") or {}).get("isrc"),
            duration_s=(item.get("duration_ms") or 0) // 1000 or None,
            cover_url=images[0]["url"] if images else None,
            ext_ids={"spotify": item["id"]} if item.get("id") else {},
        )

    async def search_tracks(self, query: str, limit: int = 20) -> list[TrackRef]:
        data = await self._get("/search", {"q": query, "type": "track", "limit": limit})
        return [self._track_from(i) for i in (data.get("tracks", {}).get("items") or [])]

    async def search_albums(self, query: str, limit: int = 20) -> list[AlbumRef]:
        data = await self._get("/search", {"q": query, "type": "album", "limit": limit})
        out: list[AlbumRef] = []
        for a in data.get("albums", {}).get("items") or []:
            images = a.get("images") or []
            artists = a.get("artists") or []
            year = (a.get("release_date") or "")[:4]
            out.append(
                AlbumRef(
                    id=a["id"],
                    title=a.get("name", ""),
                    artist=artists[0]["name"] if artists else "",
                    provider=self.name,
                    year=int(year) if year.isdigit() else None,
                    cover_url=images[0]["url"] if images else None,
                    total_tracks=a.get("total_tracks"),
                )
            )
        return out

    async def search_artists(self, query: str, limit: int = 20) -> list[ArtistRef]:
        data = await self._get("/search", {"q": query, "type": "artist", "limit": limit})
        out: list[ArtistRef] = []
        for a in data.get("artists", {}).get("items") or []:
            images = a.get("images") or []
            out.append(
                ArtistRef(
                    id=a["id"],
                    name=a.get("name", ""),
                    provider=self.name,
                    cover_url=images[0]["url"] if images else None,
                )
            )
        return out

    async def get_album_tracks(self, album_id: str) -> tuple[AlbumRef | None, list[TrackRef]]:
        album = await self._get(f"/albums/{album_id}", {})
        images = album.get("images") or []
        artists = album.get("artists") or []
        year = (album.get("release_date") or "")[:4]
        ref = AlbumRef(
            id=album["id"],
            title=album.get("name", ""),
            artist=artists[0]["name"] if artists else "",
            provider=self.name,
            year=int(year) if year.isdigit() else None,
            cover_url=images[0]["url"] if images else None,
            total_tracks=album.get("total_tracks"),
        )
        tracks = [
            self._track_from(item, album=album)
            for item in (album.get("tracks", {}).get("items") or [])
        ]
        return ref, tracks

    async def aclose(self) -> None:
        await self._http.aclose()
