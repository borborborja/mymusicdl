"""Durable, batched Navidrome reconciliation, independent of the download workers."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import PurePosixPath
from weakref import WeakValueDictionary

from sqlalchemy import or_, select

from backend.app.db.base import utcnow
from backend.app.db.models import Job, LibraryItem
from backend.app.downloads.tagging import tag_audio
from backend.app.library.files import library_file
from backend.app.logging import get_logger
from backend.app.providers.base import TrackRef
from backend.app.schemas.jobs import JobDTO

log = get_logger(__name__)


class LibrarySync:
    def __init__(
        self,
        *,
        settings,
        session_factory,
        navidrome,
        broker,
        invalidate=None,
        on_confirmed=None,
        destination_locks=None,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.navidrome = navidrome
        self.broker = broker
        self.invalidate = invalidate
        self.on_confirmed = on_confirmed
        self._task = None
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._destination_locks = (
            destination_locks if destination_locks is not None else WeakValueDictionary()
        )

    def wake(self):
        self._wake.set()

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self):
        while True:
            self._wake.clear()
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Navidrome reconciliation failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=5)
            except TimeoutError:
                pass

    async def _publish(self, job):
        await self.broker.publish(
            {
                "type": "job",
                "library_sync": True,
                "job": JobDTO.model_validate(job).model_dump(mode="json"),
            }
        )

    async def retry(self, job_id: str):
        if self.navidrome is None:
            raise ValueError("Navidrome no está configurado.")
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.kind != "download" or job.status != "done":
                raise ValueError("Solo se pueden sincronizar descargas terminadas.")
            library_file(self.settings.music_path, job.result_path)
            # A request already being processed is idempotent; don't reset its attempt count.
            if job.library_status != "syncing":
                job.library_status, job.library_confirmed = "pending", None
                job.library_error, job.library_next_retry_at = None, None
                job.library_attempts = 0
                await session.commit()
                await self._publish(job)
        self.wake()

    async def _wait_scan(self):
        async with asyncio.timeout(max(0.01, self.settings.navidrome_scan_timeout_s)):
            while (await self.navidrome.get_scan_status()).get("scanning"):
                await asyncio.sleep(min(2, max(0.001, self.settings.navidrome_scan_timeout_s / 10)))

    async def _find_file(self, track, relative):
        # Navidrome's path is relative to its music folder. A metadata-only match may be a
        # different copy or an older lossy version, so it cannot confirm this downloaded file.
        for query in dict.fromkeys([track.title, f"{track.artist} {track.title}"]):
            for offset in range(0, 1000, 100):
                result = await self.navidrome.search3(query, song_count=100, song_offset=offset)
                songs = result.get("song") or []
                for song in songs:
                    path = song.get("path")
                    if (
                        path
                        and song.get("id")
                        and not song.get("isMissing")
                        and str(PurePosixPath(path.replace("\\", "/"))).lstrip("/") == relative
                    ):
                        return song
                if len(songs) < 100:
                    break
        return None

    async def _finish(self, job_id, *, song=None, error=None, permanent=False):
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status != "done":
                return
            job.library_confirmed = song is not None
            job.library_error = error
            job.library_next_retry_at = None
            if song is not None:
                job.library_status = "confirmed"
                rows = await session.scalars(
                    select(LibraryItem).where(LibraryItem.file_path == job.result_path)
                )
                for item in rows:
                    item.navidrome_id = song.get("id")
                if self.invalidate:
                    self.invalidate()
            elif permanent or job.library_attempts >= max(
                1, self.settings.navidrome_sync_max_attempts
            ):
                job.library_status = "error"
            else:
                job.library_status = "pending"
                delay = min(
                    300,
                    max(1, self.settings.navidrome_sync_retry_s)
                    * 2 ** max(0, job.library_attempts - 1),
                )
                job.library_next_retry_at = utcnow() + timedelta(seconds=delay)
            await session.commit()
            if song is not None and self.on_confirmed:
                try:
                    await self.on_confirmed(song)
                except Exception:
                    log.warning("Catalog update deferred after confirmation")
            await self._publish(job)

    async def run_once(self):
        async with self._lock:
            async with self.session_factory() as session:
                jobs = list(
                    await session.scalars(
                        select(Job)
                        .where(
                            Job.kind == "download",
                            Job.status == "done",
                            Job.library_confirmed.is_not(True),
                            or_(
                                Job.library_status.is_(None),
                                Job.library_status.in_(("pending", "syncing", "unconfigured")),
                            ),
                            or_(
                                Job.library_next_retry_at.is_(None),
                                Job.library_next_retry_at <= utcnow(),
                            ),
                            (
                                True
                                if self.navidrome is not None
                                else or_(
                                    Job.library_status.is_(None),
                                    Job.library_status != "unconfigured",
                                )
                            ),
                        )
                        .order_by(Job.created_at)
                        .limit(100)
                    )
                )
                if not jobs:
                    return
                if self.navidrome is None:
                    for job in jobs:
                        if job.library_status != "unconfigured":
                            job.library_status = "unconfigured"
                            job.library_error = (
                                "Navidrome no está configurado. El archivo se puede escuchar aquí."
                            )
                            await session.commit()
                            await self._publish(job)
                    return
                pending = []
                for job in jobs:
                    try:
                        path = library_file(self.settings.music_path, job.result_path)
                        track = TrackRef.from_dict(json.loads(job.track_json or "{}"))
                        if not job.library_prepared:
                            lock = self._destination_locks.setdefault(
                                str(path.parent), asyncio.Lock()
                            )
                            async with lock:
                                await tag_audio(str(path), track)
                            job.library_prepared = True
                    except (ValueError, TypeError, RuntimeError, OSError, TimeoutError) as exc:
                        job.library_status, job.library_confirmed = "error", False
                        job.library_error = str(exc)
                        await session.commit()
                        await self._publish(job)
                        continue
                    job.library_status = "syncing"
                    job.library_attempts += 1
                    job.library_error = None
                    await session.commit()
                    await self._publish(job)
                    relative = path.relative_to(self.settings.music_path.resolve()).as_posix()
                    pending.append((job.id, track, relative, job.library_attempts))
            if not pending:
                return
            try:
                # A scan already in progress can predate the new files. Wait for it, then
                # request a fresh scan. Escalate retries to full scan for stale folder mtimes.
                await self._wait_scan()
                await self.navidrome.start_scan(
                    full=any(attempt > 1 for _, _, _, attempt in pending)
                )
                await self._wait_scan()
            except Exception as exc:
                message = "Navidrome no respondió al escaneo. Comprueba la conexión y los permisos del usuario."
                if isinstance(exc, TimeoutError):
                    message = "El escaneo de Navidrome sigue ocupado; se volverá a intentar."
                # Avoid persisting signed authentication URLs from HTTPX exceptions.
                log.warning("Navidrome scan failed (%s)", type(exc).__name__)
                for job_id, _, _, _ in pending:
                    await self._finish(job_id, error=message)
                return
            for job_id, track, relative, _ in pending:
                try:
                    song = await self._find_file(track, relative)
                    await self._finish(
                        job_id,
                        song=song,
                        error=(
                            None
                            if song
                            else (
                                "El archivo está descargado, pero Navidrome aún no muestra esa ruta. "
                                "Comprueba que ambos servicios leen el mismo volumen, los permisos y las exclusiones .ndignore. "
                                "Los volúmenes remotos pueden tardar en mostrar los cambios."
                            )
                        ),
                    )
                except Exception as exc:
                    log.warning("Navidrome file lookup failed (%s)", type(exc).__name__)
                    await self._finish(
                        job_id,
                        error="No se pudo comprobar el archivo en Navidrome; se volverá a intentar.",
                    )
