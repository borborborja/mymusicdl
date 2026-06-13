"""Minimal async Subsonic API client (Navidrome speaks Subsonic).

Auth uses the salted-token scheme: ``t = md5(password + salt)`` with a fresh random ``salt`` per
request, so the password is never sent in the clear.
"""
from __future__ import annotations

import hashlib
import secrets

import httpx

from backend.app.config import Settings
from backend.app.logging import get_logger

log = get_logger(__name__)

API_VERSION = "1.16.1"
CLIENT_NAME = "mymusicdl"


class NavidromeError(RuntimeError):
    pass


class NavidromeClient:
    def __init__(self, base_url: str, user: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self._http = httpx.AsyncClient(timeout=15.0)

    def _auth_params(self) -> dict[str, str]:
        salt = secrets.token_hex(8)
        token = hashlib.md5(f"{self.password}{salt}".encode()).hexdigest()
        return {
            "u": self.user,
            "t": token,
            "s": salt,
            "v": API_VERSION,
            "c": CLIENT_NAME,
            "f": "json",
        }

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/rest/{endpoint}"
        query = self._auth_params()
        if params:
            query.update({k: v for k, v in params.items() if v is not None})
        resp = await self._http.get(url, params=query)
        resp.raise_for_status()
        body = resp.json().get("subsonic-response", {})
        if body.get("status") == "failed":
            err = body.get("error", {})
            raise NavidromeError(err.get("message", "Subsonic request failed"))
        return body

    # ── endpoints ──
    async def ping(self) -> bool:
        try:
            body = await self._get("ping")
            return body.get("status") == "ok"
        except Exception:
            return False

    async def search3(
        self,
        query: str,
        *,
        artist_count: int = 0,
        album_count: int = 0,
        song_count: int = 20,
    ) -> dict:
        body = await self._get(
            "search3",
            {
                "query": query,
                "artistCount": artist_count,
                "albumCount": album_count,
                "songCount": song_count,
            },
        )
        return body.get("searchResult3", {})

    async def get_song(self, song_id: str) -> dict:
        body = await self._get("getSong", {"id": song_id})
        return body.get("song", {})

    async def get_album(self, album_id: str) -> dict:
        body = await self._get("getAlbum", {"id": album_id})
        return body.get("album", {})

    async def start_scan(self) -> dict:
        body = await self._get("startScan")
        return body.get("scanStatus", {})

    async def get_scan_status(self) -> dict:
        body = await self._get("getScanStatus")
        return body.get("scanStatus", {})

    async def aclose(self) -> None:
        await self._http.aclose()


def build_navidrome(settings: Settings) -> NavidromeClient | None:
    if settings.navidrome_url and settings.navidrome_user and settings.navidrome_password:
        return NavidromeClient(
            settings.navidrome_url, settings.navidrome_user, settings.navidrome_password
        )
    log.warning("Navidrome not configured — library badges and rescans disabled")
    return None
