"""Atomic, paginated Navidrome projection. An interrupted refresh preserves the last snapshot."""

from __future__ import annotations

import asyncio
import json
import unicodedata
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert

from backend.app.db.base import utcnow
from backend.app.db.models import CatalogState, CatalogTrack
from backend.app.logging import get_logger
from backend.app.schemas.collection import CollectionTrack, digest, iso, mbid

log = get_logger(__name__)


def searchable(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)
    )


class Catalog:
    def __init__(self, *, settings, session_factory, navidrome, broker):
        self.settings, self.session_factory = settings, session_factory
        self.navidrome, self.broker = navidrome, broker
        # Account scopes may differ even on the same server. Never mix their snapshots.
        self.server_key = digest(f"{settings.navidrome_url or ''}|{settings.navidrome_user or ''}")
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._task = None
        self.refreshing = False

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def wake(self):
        self._wake.set()

    async def _loop(self):
        while True:
            self._wake.clear()
            try:
                await self.sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Catalog refresh failed")
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=60 if (await self.status())["error"] else 6 * 3600
                )
            except TimeoutError:
                pass

    def _values(self, song):
        if not song.get("id") or not song.get("title"):
            raise ValueError("Invalid Navidrome song")
        key = digest(f"{self.server_key}:{song['id']}")
        recording = mbid(song.get("musicBrainzId"))
        artist_ids = [
            a.get("musicBrainzId") for a in song.get("artists", []) if a.get("musicBrainzId")
        ]
        track = CollectionTrack(
            catalog_id=key,
            title=song["title"],
            artist=song.get("artist") or "Artista desconocido",
            album=song.get("album"),
            provider_id="navidrome",
            duration_s=song.get("duration"),
            album_artist=song.get("displayAlbumArtist"),
            ext_ids={
                **({"mbid": recording} if recording else {}),
                **({"artist_mbid": artist_ids[0]} if artist_ids else {}),
            },
        )
        payload = {
            "track": track.model_dump(),
            "navidrome_id": str(song["id"]),
            "cover_art": song.get("coverArt"),
            "format": song.get("suffix"),
            "bitrate_kbps": song.get("bitRate"),
            "created": song.get("created"),
        }
        return dict(
            id=key,
            server_key=self.server_key,
            navidrome_id=str(song["id"]),
            title=track.title,
            artist=track.artist,
            album=track.album or "",
            search_text=searchable(f"{track.title} {track.artist} {track.album or ''}"),
            recording_mbid=recording,
            available=not song.get("isMissing", False),
            payload=json.dumps(payload),
            updated_at=utcnow(),
        )

    async def _upsert(self, session, values):
        stmt = insert(CatalogTrack).values(**values)
        await session.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=values))

    async def accept_song(self, song):
        """A confirmed download is visible immediately, without another complete scan."""
        async with self._lock:
            async with self.session_factory() as session:
                await self._upsert(session, self._values(song))
                state = await session.get(CatalogState, self.server_key)
                if state is None:
                    state = CatalogState(server_key=self.server_key)
                    session.add(state)
                state.generation = str(uuid4())
                await session.commit()
        await self.broker.publish({"type": "collection"})

    async def status(self):
        async with self.session_factory() as session:
            state = await session.get(CatalogState, self.server_key)
            stale = (
                not state
                or not state.updated_at
                or state.updated_at.replace(tzinfo=None)
                < (utcnow() - timedelta(hours=6)).replace(tzinfo=None)
            )
            return {
                "generation": state.generation if state else None,
                "configured": self.navidrome is not None,
                "refreshing": self.refreshing,
                "updated_at": iso(state.updated_at) if state else None,
                "stale": stale or bool(state and state.error),
                "error": state.error if state else None,
            }

    async def sync(self):
        if self.navidrome is None:
            return
        async with self._lock:
            self.refreshing = True
            try:
                before = await self.navidrome.get_scan_status()
                if before.get("scanning"):
                    raise RuntimeError("scan running")
                songs = {}
                offset = 0
                while True:
                    result = await self.navidrome.search3("", song_count=500, song_offset=offset)
                    page = result.get("song", [])
                    if not isinstance(page, list):
                        raise ValueError("Invalid catalog page")
                    if not page:
                        break
                    for song in page:
                        values = self._values(song)
                        if values["id"] in songs:
                            raise ValueError("Catalog changed during pagination")
                        songs[values["id"]] = values
                    offset += len(page)
                    # Ask for the next page even if the server caps our requested page size.
                after = await self.navidrome.get_scan_status()
                if after.get("scanning") or before != after:
                    raise RuntimeError("Catalog changed during refresh")
                async with self.session_factory() as session:
                    await session.execute(
                        update(CatalogTrack)
                        .where(CatalogTrack.server_key == self.server_key)
                        .values(available=False)
                    )
                    for values in songs.values():
                        await self._upsert(session, values)
                    state = await session.get(CatalogState, self.server_key)
                    if state is None:
                        state = CatalogState(server_key=self.server_key)
                        session.add(state)
                    state.generation = str(uuid4())
                    state.updated_at = state.checked_at = utcnow()
                    state.error = None
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Catalog unavailable (%s)", type(exc).__name__)
                async with self.session_factory() as session:
                    state = await session.get(CatalogState, self.server_key)
                    if state is None:
                        state = CatalogState(server_key=self.server_key)
                        session.add(state)
                    state.checked_at = utcnow()
                    state.error = "No se pudo actualizar Navidrome. Se conserva la última biblioteca; puedes volver a intentarlo."
                    await session.commit()
            finally:
                self.refreshing = False
        await self.broker.publish({"type": "collection"})
