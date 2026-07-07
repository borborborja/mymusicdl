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

# Cover Art Archive — free, keyless artwork keyed by MusicBrainz MBIDs. Not every release has art,
# so these URLs may 404; the frontend's <Artwork> falls back to a generated cover on image error.
_CAA = "https://coverartarchive.org"


def _caa_release(release_id: str | None) -> str | None:
    return f"{_CAA}/release/{release_id}/front-250" if release_id else None


def _caa_release_group(rg_id: str | None) -> str | None:
    return f"{_CAA}/release-group/{rg_id}/front-250" if rg_id else None


def _lucene_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _lucene(query: str, field: str, **filters: str | None) -> str:
    """Compose a fielded Lucene query (``recording:"Creep" AND artist:"Radiohead"``).

    With no filters set the query passes through verbatim (free-text match as before). Filter
    keys are MB field names for the target endpoint (``firstreleasedate`` on /recording,
    ``date`` on /release, …). Filter values match word-by-word rather than as an exact phrase:
    the credit "Freddie Mercury & Montserrat Caballé" must be findable with "mercury caballé",
    where a phrase would fail on the non-adjacent words.
    """
    active = {k: v.strip() for k, v in filters.items() if v and v.strip()}
    if not active:
        return query
    parts = [f'{field}:"{_lucene_escape(query.strip())}"'] if query.strip() else []
    for key, value in active.items():
        parts.extend(f'{key}:"{_lucene_escape(word)}"' for word in value.split())
    return " AND ".join(parts)


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
        # Full credit incl. join phrases ("Freddie Mercury & Montserrat Caballé",
        # "Manu Guix feat. Pau Donés") — showing only the first artist hides why a
        # collaboration matched an artist filter.
        ac = obj.get("artist-credit") or []
        return "".join(f"{c.get('name', '')}{c.get('joinphrase', '')}" for c in ac)

    async def search_tracks(
        self,
        query: str,
        limit: int = 20,
        *,
        artist: str | None = None,
        album: str | None = None,
        year: str | None = None,
    ) -> list[TrackRef]:
        q = _lucene(query, "recording", artist=artist, release=album, firstreleasedate=year)
        data = await self._get("/recording", {"query": q, "limit": limit})
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
                    cover_url=_caa_release(releases[0].get("id")) if releases else None,
                    ext_ids={"mbid": rec["id"]} if rec.get("id") else {},
                )
            )
        return out

    async def search_albums(
        self,
        query: str,
        limit: int = 20,
        *,
        artist: str | None = None,
        year: str | None = None,
    ) -> list[AlbumRef]:
        # Search /release rather than /release-group: same Lucene fields, but each hit carries
        # a track-count (the RG endpoint doesn't), so album cards can show the song count
        # without one extra lookup per result. Collapse editions back to one card per RG.
        q = _lucene(query, "release", artist=artist, date=year)
        data = await self._get("/release", {"query": q, "limit": limit})
        out: list[AlbumRef] = []
        seen: set[str] = set()
        for rel in data.get("releases", []) or []:
            rg_id = (rel.get("release-group") or {}).get("id")
            if not rg_id or rg_id in seen:
                continue
            seen.add(rg_id)
            date = rel.get("date") or ""
            out.append(
                AlbumRef(
                    id=rg_id,
                    title=rel.get("title", ""),
                    artist=self._artist_credit(rel),
                    provider=self.name,
                    year=int(date[:4]) if date[:4].isdigit() else None,
                    cover_url=_caa_release_group(rg_id),
                    total_tracks=rel.get("track-count"),
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
        # Prefer art on the specific release; fall back to the release-group cover.
        cover = _caa_release(rel.get("id")) or _caa_release_group(album_id)
        ref = AlbumRef(
            id=album_id,
            title=rel.get("title", ""),
            artist=self._artist_credit(rel),
            provider=self.name,
            cover_url=cover,
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
                        cover_url=cover,
                    )
                )
        return ref, tracks

    async def aclose(self) -> None:
        await self._http.aclose()
