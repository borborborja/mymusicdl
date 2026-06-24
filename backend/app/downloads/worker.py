"""Asyncio worker pool — the no-Redis job engine.

N worker coroutines block on the in-memory queue, claim a ``queued`` job, run the provider's
download (each in a child task so it can be cancelled individually), stream progress to the broker,
and on success detect the produced file and hand it to the library tracker.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os

from backend.app.config import Settings
from backend.app.db.models import Job
from backend.app.downloads.errors import humanize_error
from backend.app.downloads.paths import build_dest
from backend.app.downloads.progress import ProgressBroker
from backend.app.downloads.queue import DownloadQueue
from backend.app.downloads.runner import SubprocessError
from backend.app.logging import get_logger
from backend.app.navidrome.matcher import library_quality
from backend.app.providers.base import Quality, TrackRef
from backend.app.providers.registry import ProviderRegistry
from backend.app.schemas.jobs import JobDTO

log = get_logger(__name__)

_AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac"}


def _audio_files(dest: str) -> set[str]:
    """All audio file paths under ``dest`` (recursive — downloaders may nest by artist/album)."""
    found: set[str] = set()
    for root, _dirs, names in os.walk(dest):
        for name in names:
            if os.path.splitext(name)[1].lower() in _AUDIO_EXTS:
                found.add(os.path.join(root, name))
    return found


def _pick_new_audio(dest: str, before: set[str]) -> str | None:
    """Return the path of the largest newly-created audio file under ``dest``."""
    candidates = []
    for full in _audio_files(dest) - before:
        try:
            candidates.append((os.path.getsize(full), full))
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


class WorkerPool:
    def __init__(
        self,
        *,
        settings: Settings,
        queue: DownloadQueue,
        broker: ProgressBroker,
        registry: ProviderRegistry,
        navidrome,
        session_factory,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.broker = broker
        self.registry = registry
        self.navidrome = navidrome
        self.session_factory = session_factory
        self._tasks: list[asyncio.Task] = []
        self._active: dict[str, asyncio.Task] = {}
        self._cancelled: set[str] = set()
        self._confirm_tasks: set[asyncio.Task] = set()
        self._next_idx = 0

    async def _effective_concurrency(self) -> int:
        """Persisted runtime override (Settings UI) wins over the env-driven default."""
        from backend.app.db.repo import get_setting

        try:
            async with self.session_factory() as session:
                raw = await get_setting(session, "download_concurrency")
            if raw is not None:
                return max(1, int(raw))
        except Exception:
            log.warning("Could not read download_concurrency override; using default", exc_info=True)
        return max(1, self.settings.download_concurrency)

    async def _download_layout(self) -> str:
        """Persisted folder-structure template (Settings UI) or the env-driven default."""
        from backend.app.db.repo import get_setting

        try:
            async with self.session_factory() as session:
                raw = await get_setting(session, "download_layout")
            if raw:
                return raw
        except Exception:
            log.warning("Could not read download_layout override; using default", exc_info=True)
        return self.settings.download_layout

    def _spawn_worker(self) -> None:
        idx = self._next_idx
        self._next_idx += 1
        self._tasks.append(asyncio.create_task(self._run(idx)))

    async def start(self) -> None:
        n = await self._effective_concurrency()
        for _ in range(n):
            self._spawn_worker()
        log.info("Worker pool started (%d workers)", len(self._tasks))

    async def set_concurrency(self, n: int) -> int:
        """Resize the pool live. Growing spawns workers; shrinking cancels surplus ones (a job in
        flight is re-queued, so it resumes on a remaining worker)."""
        n = max(1, min(16, int(n)))
        current = len(self._tasks)
        if n > current:
            for _ in range(n - current):
                self._spawn_worker()
        elif n < current:
            surplus, self._tasks = self._tasks[n:], self._tasks[:n]
            for t in surplus:
                t.cancel()
        log.info("Worker pool resized to %d workers", n)
        return n

    async def stop(self) -> None:
        for t in (*self._tasks, *self._confirm_tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, *self._confirm_tasks, return_exceptions=True)
        self._tasks.clear()
        self._confirm_tasks.clear()

    def cancel(self, job_id: str) -> bool:
        """Request cancellation of a running job. Returns True if it was active."""
        self._cancelled.add(job_id)
        task = self._active.get(job_id)
        if task is not None:
            task.cancel()
            return True
        return False

    async def _run(self, idx: int) -> None:
        while True:
            try:
                job_id = await self.queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._process(job_id)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("worker %d crashed handling job %s", idx, job_id)
            finally:
                self.queue.task_done()

    async def _publish(self, job: Job, *, message: str | None = None, **extra) -> None:
        payload = {"type": "job", "job": JobDTO.model_validate(job).model_dump(mode="json")}
        if message:
            payload["message"] = message
        payload.update({k: v for k, v in extra.items() if v is not None})
        await self.broker.publish(payload)

    async def _process(self, job_id: str) -> None:
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status != "queued":
                return

            provider = self.registry.get(job.provider or "")
            if provider is None or not provider.enabled:
                job.status, job.error, job.stage = "error", f"Provider '{job.provider}' unavailable", "error"
                await session.commit()
                await self._publish(job)
                return

            try:
                track = TrackRef.from_dict(json.loads(job.track_json or "{}"))
                tier = job.requested_quality
                quality = Quality(tier) if tier is not None else provider.default_quality
            except Exception as exc:  # noqa: BLE001
                job.status, job.error, job.stage = "error", f"Bad job payload: {exc!r}", "error"
                await session.commit()
                await self._publish(job)
                return

            base = job.dest_dir or self.settings.music_library_path
            layout = await self._download_layout()
            dest, filename = build_dest(
                base, layout, artist=track.artist, album=track.album, title=track.title
            )
            os.makedirs(dest, exist_ok=True)
            before = _audio_files(dest)

            job.status, job.stage, job.progress_pct, job.error = "running", "resolving", 0.0, None
            await session.commit()
            await self._publish(job)

            async def consume() -> None:
                last_pct = -10.0
                async for ev in provider.download(
                    track, quality=quality, dest_dir=dest, job_id=job_id, filename=filename
                ):
                    dirty = False
                    if ev.stage and ev.stage != job.stage:
                        job.stage = ev.stage
                        dirty = True
                    if ev.pct is not None and ev.pct - last_pct >= 1.0:
                        job.progress_pct = ev.pct
                        last_pct = ev.pct
                        dirty = True
                    if dirty:
                        await session.commit()
                    await self._publish(job, message=ev.message, speed=ev.speed, eta_s=ev.eta_s)

            task = asyncio.create_task(consume())
            self._active[job_id] = task
            try:
                await task
            except asyncio.CancelledError:
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
                if job_id in self._cancelled:
                    self._cancelled.discard(job_id)
                    job.status, job.stage = "canceled", "canceled"
                    with contextlib.suppress(Exception):
                        await session.commit()
                        await self._publish(job)
                    return
                # Pool shutdown / down-resize mid-job → requeue so a remaining worker (or the next
                # boot's rehydrate) resumes it instead of losing it.
                job.status, job.stage = "queued", None
                with contextlib.suppress(Exception):
                    await session.commit()
                    await self.queue.put(job_id)
                raise
            except SubprocessError as exc:
                log.warning("download job %s failed: %s", job_id, exc)
                job.status, job.error, job.stage = "error", humanize_error(str(exc))[:4000], "error"
                await session.commit()
                await self._publish(job)
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("download job %s crashed", job_id)
                job.status, job.error, job.stage = "error", humanize_error(repr(exc))[:4000], "error"
                await session.commit()
                await self._publish(job)
                return
            finally:
                self._active.pop(job_id, None)

            # ── success ──
            job.result_path = _pick_new_audio(dest, before)
            job.status, job.progress_pct, job.stage = "done", 100.0, "done"
            await session.commit()
            await self._publish(job)

            try:
                from backend.app.library.tracker import record_download

                await record_download(
                    session,
                    self.settings,
                    self.navidrome,
                    job=job,
                    track=track,
                    result_path=job.result_path,
                    quality=quality,
                )
            except Exception:
                log.exception("library bookkeeping failed for job %s", job_id)

        # ── confirm in Navidrome (detached: don't hold the worker slot during the rescan) ──
        if self.navidrome is not None:
            t = asyncio.create_task(self._confirm_in_library(job_id, track))
            self._confirm_tasks.add(t)
            t.add_done_callback(self._confirm_tasks.discard)

    async def recheck(self, job_id: str) -> bool:
        """Re-run the Navidrome confirmation for a finished download (the rescan may lag)."""
        if self.navidrome is None:
            return False
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.kind != "download":
                return False
            try:
                track = TrackRef.from_dict(json.loads(job.track_json or "{}"))
            except Exception:
                return False
            job.library_confirmed = None
            await session.commit()
            await self._publish(job, message="Re-comprobando en Navidrome…")
        t = asyncio.create_task(self._confirm_in_library(job_id, track))
        self._confirm_tasks.add(t)
        t.add_done_callback(self._confirm_tasks.discard)
        return True

    async def _confirm_in_library(self, job_id: str, track: TrackRef) -> None:
        """After the post-download rescan, wait for it to settle and check the track is indexed.

        Sets ``job.library_confirmed`` (True/False) and publishes it so the queue can show whether
        the file actually made it into Navidrome — not just that a download finished.
        """
        try:
            # Give the rescan time to settle: poll scanStatus, then fall back to a fixed wait.
            for _ in range(15):  # ~30s max
                try:
                    status = await self.navidrome.get_scan_status()
                except Exception:
                    break
                if not status.get("scanning"):
                    break
                await asyncio.sleep(2)

            match = await library_quality(
                self.navidrome,
                artist=track.artist,
                title=track.title,
                album=track.album,
                duration_s=track.duration_s,
            )
            confirmed = match is not None

            async with self.session_factory() as session:
                job = await session.get(Job, job_id)
                if job is None:
                    return
                job.library_confirmed = confirmed
                await session.commit()
                await self._publish(
                    job,
                    message=(
                        "Confirmada en Navidrome"
                        if confirmed
                        else "Descargada, pero aún no aparece en Navidrome"
                    ),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Navidrome confirmation failed for job %s", job_id)
