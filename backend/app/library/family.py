"""Shared family selections and presentation state; the downloader remains the single queue path."""

from __future__ import annotations

import asyncio
import json
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert

from backend.app.db.base import utcnow
from backend.app.db.models import CatalogTrack, FamilyArtist, FamilyTrack, Job, LibraryItem
from backend.app.downloads.service import EnqueueItem, enqueue_tracks
from backend.app.library.files import library_file
from backend.app.schemas.collection import CollectionTrack, digest, mbid


class Family:
    def __init__(self, *, settings, session_factory, catalog, broker, queue, registry):
        self.settings, self.session_factory, self.catalog = settings, session_factory, catalog
        self.broker, self.queue, self.registry = broker, queue, registry
        self.lock = asyncio.Lock()

    async def changed(self):
        await self.broker.publish({"type": "collection"})

    async def preference(self, change):
        track = change.track
        if track.catalog_id:
            async with self.session_factory() as session:
                row = await session.get(CatalogTrack, track.catalog_id)
                if row is None or row.server_key != self.catalog.server_key:
                    raise ValueError("La pista ya no pertenece a este catálogo.")
                track = CollectionTrack(**json.loads(row.payload)["track"])
        flags = change.model_dump(exclude={"track"}, exclude_none=True)
        if not flags:
            raise ValueError("Selecciona una preferencia.")
        async with self.lock:
            async with self.session_factory() as session:
                values = dict(
                    id=track.identity(),
                    payload=track.model_dump_json(),
                    updated_at=utcnow(),
                    **flags,
                )
                stmt = insert(FamilyTrack).values(**values)
                # Update only the submitted flags: simultaneous saves must not erase favorites.
                await session.execute(
                    stmt.on_conflict_do_update(index_elements=["id"], set_=values)
                )
                await session.commit()
        await self.changed()
        return (await self.cards([track]))[0]

    async def artist(self, choice):
        async with self.lock:
            async with self.session_factory() as session:
                rows = list(await session.scalars(select(FamilyArtist)))
                key = str(choice.id)
                if not any(a.id == key for a in rows) and len(rows) >= 5:
                    raise ValueError(
                        "Puedes elegir hasta cinco artistas. Quita uno para cambiar la selección."
                    )
                stmt = insert(FamilyArtist).values(id=key, name=choice.name)
                await session.execute(
                    stmt.on_conflict_do_update(index_elements=["id"], set_={"name": choice.name})
                )
                await session.commit()
        await self.changed()

    async def remove_artist(self, key):
        async with self.lock:
            async with self.session_factory() as session:
                row = await session.get(FamilyArtist, key)
                if row:
                    await session.delete(row)
                    await session.commit()
        await self.changed()

    async def cards(self, tracks):
        if not tracks:
            return []
        status = await self.catalog.status()
        ids = [t.identity() for t in tracks]
        catalog_ids = [t.catalog_id for t in tracks if t.catalog_id]
        mbids = [mbid(t.ext_ids.get("mbid")) for t in tracks]
        async with self.session_factory() as session:
            preferences = {
                r.id: r
                for r in await session.scalars(select(FamilyTrack).where(FamilyTrack.id.in_(ids)))
            }
            local = list(
                await session.scalars(
                    select(LibraryItem)
                    .where(LibraryItem.title.in_([t.title for t in tracks]))
                    .order_by(LibraryItem.downloaded_at.desc())
                )
            )
            catalog = list(
                await session.scalars(
                    select(CatalogTrack).where(
                        CatalogTrack.server_key == self.catalog.server_key,
                        or_(
                            CatalogTrack.id.in_(catalog_ids),
                            CatalogTrack.recording_mbid.in_([m for m in mbids if m]),
                            CatalogTrack.navidrome_id.in_(
                                [r.navidrome_id for r in local if r.navidrome_id]
                            ),
                        ),
                    )
                )
            )
            jobs = {
                j.id: j
                for j in await session.scalars(
                    select(Job).where(
                        Job.id.in_([p.job_id for p in preferences.values() if p.job_id])
                    )
                )
            }
        cards = []
        for track in tracks:
            pref = preferences.get(track.identity())
            job = jobs.get(pref.job_id) if pref else None
            recording = mbid(track.ext_ids.get("mbid"))
            matches = [
                r
                for r in catalog
                if r.id == track.catalog_id
                or (not track.catalog_id and recording and r.recording_mbid == recording)
            ]
            match = next((r for r in matches if r.available), None)
            local_item = next(
                (
                    r
                    for r in local
                    if (recording and mbid(r.mbid) == recording)
                    or (job and r.file_path == job.result_path)
                ),
                None,
            )
            if track.catalog_id:
                # Selecting a concrete Navidrome file must audition that file, even when another
                # local edition carries the same recording MBID.
                local_item = next(
                    (r for r in local if match and r.navidrome_id == match.navidrome_id), None
                )
            if local_item is None and not track.catalog_id:
                candidates = [
                    r
                    for r in local
                    if not recording
                    and not mbid(r.mbid)
                    and r.title == track.title
                    and r.artist == track.artist
                    and (r.album or "") == (track.album or "")
                ]
                if len(candidates) == 1:
                    local_item = candidates[0]
            if match is None and not track.catalog_id and local_item and local_item.navidrome_id:
                match = next(
                    (
                        r
                        for r in catalog
                        if r.available and r.navidrome_id == local_item.navidrome_id
                    ),
                    None,
                )
            if local_item:
                try:
                    library_file(self.settings.music_path, local_item.file_path)
                except ValueError:
                    local_item = None
            available = "unknown" if status["stale"] or not status["configured"] else "missing"
            if match:
                available = "unknown" if status["stale"] else "available"
            if job and job.status in ("queued", "running"):
                available = "downloading"
            elif job and job.status == "done":
                available = "available" if job.library_confirmed else "pending"
                if job.library_confirmed and status["stale"]:
                    available = "unknown"
            elif job and job.status in ("error", "canceled") and not match:
                available = "failed"
            payload = json.loads(match.payload) if match else {}
            cards.append(
                {
                    "id": track.identity(),
                    "track": track.model_dump(),
                    "availability": available,
                    "saved": bool(pref and pref.saved),
                    "favorite": bool(pref and pref.favorite),
                    "dismissed": bool(pref and pref.dismissed),
                    "reason": track.reason,
                    "catalog_id": match.id if match else None,
                    "job_id": job.id if job else None,
                    "job_done": bool(job and job.status == "done" and not track.catalog_id),
                    "local_item_id": local_item.id if local_item else None,
                    "error": (job.library_error or job.error) if job else None,
                    "format": payload.get("format"),
                    "bitrate_kbps": payload.get("bitrate_kbps"),
                }
            )
        return cards

    async def download(self, key, choice):
        # Same-family retries/double clicks must share the queue's existing deduplication path.
        async with self.lock:
            async with self.session_factory() as session:
                pref = await session.get(FamilyTrack, key)
                if pref is None:
                    raise ValueError("Guarda primero la pista en pendientes.")
                track = CollectionTrack.model_validate_json(pref.payload)
                current = (await self.cards([track]))[0]
                if current["availability"] in ("available", "pending"):
                    raise ValueError("La pista ya está disponible o pendiente de sincronización.")
                if current["availability"] == "downloading":
                    return {"job_id": pref.job_id}
                data = track.model_dump(exclude={"catalog_id", "reason", "seed_id"})
                # A catalog reference is metadata, never an arbitrary downloader target.
                result = await enqueue_tracks(
                    session,
                    self.queue,
                    self.registry,
                    self.settings,
                    [EnqueueItem(provider=choice.provider, quality=choice.quality, track=data)],
                    origin="web",
                )
                if result.queued:
                    pref.job_id = result.queued[0].id
                else:
                    # A web/bot job may already be queued for this same track.
                    from backend.app.downloads.service import _job_dedup_key

                    item_key = EnqueueItem(
                        provider=choice.provider, quality=choice.quality, track=data
                    ).dedup_key
                    active = await session.scalars(
                        select(Job).where(
                            Job.kind == "download", Job.status.in_(("queued", "running"))
                        )
                    )
                    existing = next((j for j in active if _job_dedup_key(j) == item_key), None)
                    if not existing:
                        raise ValueError("La cola ha cambiado. Vuelve a intentarlo.")
                    pref.job_id = existing.id
                pref.saved = True
                pref.updated_at = utcnow()
                await session.commit()
                result = {"job_id": pref.job_id}
        await self.changed()
        return result

    async def selected(self, mode, *, offset=0, limit=40):
        async with self.session_factory() as session:
            column = {
                "saved": FamilyTrack.saved,
                "favorite": FamilyTrack.favorite,
                "dismissed": FamilyTrack.dismissed,
            }[mode]
            rows = list(
                await session.scalars(
                    select(FamilyTrack)
                    .where(column.is_(True))
                    .order_by(FamilyTrack.updated_at.desc(), FamilyTrack.id)
                    .offset(offset)
                    .limit(limit + 1)
                )
            )
        return {
            "items": await self.cards(
                [CollectionTrack.model_validate_json(r.payload) for r in rows[:limit]]
            ),
            "has_more": len(rows) > limit,
        }

    async def suggestions(self, tracks):
        cards = await self.cards([CollectionTrack(**t) for t in tracks])
        counts = Counter()
        result = []
        # Stable daily rotation avoids permanently favoring the first chosen seed/artist.
        from datetime import date

        cards.sort(key=lambda c: digest(f"{date.today()}:{c['id']}"))
        for card in cards:
            if card["dismissed"]:
                continue
            artist = card["track"]["ext_ids"].get("artist_mbid") or card["track"]["artist"]
            if counts[artist] >= 2:
                continue
            counts[artist] += 1
            result.append(card)
            if len(result) == 20:
                break
        return result
