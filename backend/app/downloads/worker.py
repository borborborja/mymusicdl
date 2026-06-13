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
from backend.app.downloads.progress import ProgressBroker
from backend.app.downloads.queue import DownloadQueue
from backend.app.downloads.runner import SubprocessError
from backend.app.logging import get_logger
from backend.app.providers.base import Quality, TrackRef
from backend.app.providers.registry import ProviderRegistry
from backend.app.schemas.jobs import JobDTO

log = get_logger(__name__)

_AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac"}


def _pick_new_audio(dest: str, before: set[str]) -> str | None:
    """Return the path of the largest newly-created audio file in ``dest``."""
    try:
        after = set(os.listdir(dest))
    except FileNotFoundError:
        return None
    candidates = []
    for name in after - before:
        ext = os.path.splitext(name)[1].lower()
        if ext in _AUDIO_EXTS:
            full = os.path.join(dest, name)
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

    async def start(self) -> None:
        n = max(1, self.settings.download_concurrency)
        self._tasks = [asyncio.create_task(self._run(i)) for i in range(n)]
        log.info("Worker pool started (%d workers)", n)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

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

            dest = job.dest_dir or self.settings.music_library_path
            os.makedirs(dest, exist_ok=True)
            before = set(os.listdir(dest))

            job.status, job.stage, job.progress_pct, job.error = "running", "resolving", 0.0, None
            await session.commit()
            await self._publish(job)

            async def consume() -> None:
                last_pct = -10.0
                async for ev in provider.download(
                    track, quality=quality, dest_dir=dest, job_id=job_id
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
                # Pool shutdown mid-job → leave it queued so the next boot resumes it.
                job.status, job.stage = "queued", None
                with contextlib.suppress(Exception):
                    await session.commit()
                raise
            except SubprocessError as exc:
                job.status, job.error, job.stage = "error", str(exc)[:4000], "error"
                await session.commit()
                await self._publish(job)
                return
            except Exception as exc:  # noqa: BLE001
                job.status, job.error, job.stage = "error", repr(exc)[:4000], "error"
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
