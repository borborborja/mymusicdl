"""On-demand artist-based discovery. No listening history or preference writes leave the server."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta

import httpx
from sqlalchemy import select

from backend.app.db.base import utcnow
from backend.app.db.models import DiscoveryCache, FamilyArtist
from backend.app.schemas.collection import CollectionTrack, iso, mbid


class ListenBrainz:
    def __init__(self):
        self.http = httpx.AsyncClient(
            base_url="https://api.listenbrainz.org",
            timeout=12,
            headers={"User-Agent": "mymusicdl/0.1 (https://github.com/borborborja/mymusicdl)"},
        )
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def get(self, path, params):
        async with self._lock:
            for attempt in range(2):
                await asyncio.sleep(max(0, self._next - time.monotonic()))
                self._next = time.monotonic() + 1.1
                try:
                    response = await self.http.get(path, params=params)
                    if response.headers.get("X-RateLimit-Remaining") == "0":
                        try:
                            self._next = time.monotonic() + min(
                                60,
                                max(
                                    1.1, float(response.headers.get("X-RateLimit-Reset-In", "1.1"))
                                ),
                            )
                        except ValueError:
                            pass
                    response.raise_for_status()
                    return response.json()
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt:
                        raise
                except httpx.HTTPStatusError as exc:
                    if attempt or exc.response.status_code not in (429, 502, 503, 504):
                        raise
                    try:
                        delay = float(exc.response.headers.get("Retry-After", "3"))
                    except ValueError:
                        delay = 3
                    self._next = max(self._next, time.monotonic() + min(60, max(1.1, delay)))

    async def recommendations(self, artists):
        candidates = []
        for artist in artists:
            response = await self.get(
                f"/1/lb-radio/artist/{artist.id}",
                {
                    "mode": "easy",
                    "max_similar_artists": 6,
                    "max_recordings_per_artist": 2,
                    "pop_begin": 0,
                    "pop_end": 100,
                },
            )
            if not isinstance(response, dict):
                raise ValueError("Invalid recommendation response")
            for rows in response.values():
                for row in rows:
                    recording = mbid(row.get("recording_mbid"))
                    if recording:
                        candidates.append((recording, artist))
        ids = list(dict.fromkeys(key for key, _ in candidates))[:100]
        metadata = {}
        for offset in range(0, len(ids), 50):
            data = await self.get(
                "/1/metadata/recording/",
                {"recording_mbids": ",".join(ids[offset : offset + 50]), "inc": "artist release"},
            )
            if not isinstance(data, dict):
                raise ValueError("Invalid metadata response")
            metadata.update(data)
        tracks, seen = [], set()
        for recording_id, seed in candidates:
            if recording_id in seen:
                continue
            data = metadata.get(recording_id) or {}
            recording, artist, release = (
                data.get(k) or {} for k in ("recording", "artist", "release")
            )
            if not recording.get("name") or not artist.get("name"):
                continue
            seen.add(recording_id)
            artist_ids = [
                a["artist_mbid"] for a in artist.get("artists", []) if mbid(a.get("artist_mbid"))
            ]
            tracks.append(
                CollectionTrack(
                    title=recording["name"],
                    artist=artist["name"],
                    album=release.get("name"),
                    album_artist=release.get("album_artist_name"),
                    provider_id="musicbrainz",
                    source_url=f"https://musicbrainz.org/recording/{recording_id}",
                    duration_s=(
                        round(recording["length"] / 1000) if recording.get("length") else None
                    ),
                    ext_ids={
                        "mbid": recording_id,
                        **({"artist_mbid": artist_ids[0]} if artist_ids else {}),
                    },
                    reason=f"Relacionado con {seed.name}",
                    seed_id=seed.id,
                ).model_dump()
            )
        return tracks

    async def aclose(self):
        await self.http.aclose()


class Discovery:
    def __init__(self, *, settings, session_factory, broker, client=None):
        self.settings, self.session_factory, self.broker = settings, session_factory, broker
        self.client = client or ListenBrainz()
        self._wake = asyncio.Event()
        self._task = None
        self.refreshing = False

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self.client.aclose()

    async def seeds(self):
        async with self.session_factory() as session:
            return list(await session.scalars(select(FamilyArtist).order_by(FamilyArtist.id)))

    @staticmethod
    def seed_key(artists):
        return ",".join(a.id for a in artists)

    async def snapshot(self):
        artists = await self.seeds()
        enabled = self.settings.discovery_external_enabled
        async with self.session_factory() as session:
            cache = await session.get(DiscoveryCache, "family")
            matches = cache and cache.seed_key == self.seed_key(artists)
            fresh = (
                matches
                and cache.updated_at
                and cache.updated_at.replace(tzinfo=None)
                > (utcnow() - timedelta(hours=24)).replace(tzinfo=None)
            )
            cooling = (
                matches
                and cache.retry_at
                and cache.retry_at.replace(tzinfo=None) > utcnow().replace(tzinfo=None)
            )
            if enabled and artists and not fresh and not cooling:
                self._wake.set()
            return {
                "tracks": json.loads(cache.payload) if matches and enabled and artists else [],
                "updated_at": iso(cache.updated_at) if matches else None,
                "stale": not bool(fresh),
                "error": cache.error if matches else None,
                "refreshing": self.refreshing
                or bool(enabled and artists and not fresh and not cooling),
                "enabled": enabled,
                "artists": [{"id": a.id, "name": a.name} for a in artists],
            }

    async def refresh(self):
        artists = await self.seeds()
        if not artists or not self.settings.discovery_external_enabled:
            return
        self.refreshing = True
        key = self.seed_key(artists)
        try:
            tracks = await self.client.recommendations(artists)
            error = None
        except asyncio.CancelledError:
            raise
        except Exception:
            tracks = None
            error = "Las sugerencias no están disponibles ahora. Conservamos las anteriores y volveremos a intentarlo."
        finally:
            self.refreshing = False
        # Do not publish recommendations for preferences changed during the request.
        if self.seed_key(await self.seeds()) != key:
            self._wake.set()
            return
        async with self.session_factory() as session:
            cache = await session.get(DiscoveryCache, "family")
            if cache is None:
                cache = DiscoveryCache(id="family", seed_key=key, payload="[]")
                session.add(cache)
            if cache.seed_key != key:
                cache.payload, cache.updated_at = "[]", None
            cache.seed_key, cache.error = key, error
            cache.retry_at = utcnow() + timedelta(minutes=5) if error else None
            if tracks is not None:
                cache.payload, cache.updated_at = json.dumps(tracks), utcnow()
            await session.commit()
        await self.broker.publish({"type": "collection"})

    async def _loop(self):
        while True:
            await self._wake.wait()
            self._wake.clear()
            try:
                # snapshot may have been requested concurrently; coalesce refreshes.
                artists = await self.seeds()
                async with self.session_factory() as session:
                    cache = await session.get(DiscoveryCache, "family")
                    if cache and cache.seed_key == self.seed_key(artists):
                        now = utcnow().replace(tzinfo=None)
                        if cache.retry_at and cache.retry_at.replace(tzinfo=None) > now:
                            continue
                        if cache.updated_at and cache.updated_at.replace(
                            tzinfo=None
                        ) > now - timedelta(hours=24):
                            continue
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A storage failure must not spin or kill application startup.
                await asyncio.sleep(5)
