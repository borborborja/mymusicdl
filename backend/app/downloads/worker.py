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
from weakref import WeakValueDictionary

from backend.app.config import Settings
from backend.app.db.models import Job
from backend.app.downloads.errors import humanize_error, is_transient
from backend.app.downloads.paths import build_dest
from backend.app.downloads.probe import duration_mismatch, ffprobe_audio
from backend.app.downloads.progress import ProgressBroker
from backend.app.downloads.queue import DownloadQueue
from backend.app.downloads.runner import SubprocessError
from backend.app.downloads.tagging import tag_audio
from backend.app.library.sync import LibrarySync
from backend.app.logging import get_logger
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
    """Return the single nonempty new audio file; ambiguous output is not success."""
    candidates = []
    for full in _audio_files(dest) - before:
        try:
            if os.path.getsize(full) > 0 and not os.path.islink(full):
                candidates.append(full)
        except OSError:
            continue
    return candidates[0] if len(candidates) == 1 else None


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
        invalidate_library=None,
        on_library_confirmed=None,
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
        self._dest_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self.library_sync = LibrarySync(
            settings=settings,
            session_factory=session_factory,
            navidrome=navidrome,
            broker=broker,
            invalidate=invalidate_library,
            on_confirmed=on_library_confirmed,
            destination_locks=self._dest_locks,
        )
        self._next_idx = 0

    async def _effective_concurrency(self) -> int:
        """Persisted runtime override (Settings UI) wins over the env-driven default."""
        from backend.app.db.repo import get_setting

        try:
            async with self.session_factory() as session:
                raw = await get_setting(session, "download_concurrency")
            if raw is not None:
                return max(1, min(16, int(raw)))
        except Exception:
            log.warning(
                "Could not read download_concurrency override; using default", exc_info=True
            )
        return max(1, min(16, self.settings.download_concurrency))

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
        await self.library_sync.start()
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
            await asyncio.gather(*surplus, return_exceptions=True)
        log.info("Worker pool resized to %d workers", n)
        return n

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.library_sync.stop()

    def stats(self) -> dict:
        """Live pool snapshot for the health endpoint."""
        return {"workers": len(self._tasks), "active": len(self._active)}

    def cancel(self, job_id: str) -> bool:
        """Request cancellation of a running job. Returns True if it was active."""
        task = self._active.get(job_id)
        if task is not None:
            self._cancelled.add(job_id)
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
        # Own the whole job, including retries, filesystem work and finalization, so cancel
        # and pool shutdown cannot leave a running row stranded between subprocess attempts.
        task = asyncio.create_task(self._process_job(job_id))
        self._active[job_id] = task
        try:
            await task
        except asyncio.CancelledError:
            user_cancel = job_id in self._cancelled
            async with self.session_factory() as session:
                job = await session.get(Job, job_id)
                if job is not None and job.status in ("queued", "running"):
                    job.status = "canceled" if user_cancel else "queued"
                    job.stage = "canceled" if user_cancel else None
                    job.progress_pct = 0.0
                    await session.commit()
                    await self._publish(job)
                    if not user_cancel:
                        await self.queue.put(job_id)
            if not user_cancel or asyncio.current_task().cancelling():
                raise
        except Exception as exc:
            log.exception("download job %s crashed", job_id)
            async with self.session_factory() as session:
                job = await session.get(Job, job_id)
                if job is not None and job.status in ("queued", "running"):
                    job.status, job.stage = "error", "error"
                    job.error = humanize_error(str(exc))[:4000]
                    await session.commit()
                    await self._publish(job)
        finally:
            self._active.pop(job_id, None)
            self._cancelled.discard(job_id)

    async def _process_job(self, job_id: str) -> None:
        async with contextlib.AsyncExitStack() as stack, self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.kind != "download" or job.status != "queued":
                return

            provider = self.registry.get(job.provider or "")
            if provider is None or not provider.enabled:
                job.status, job.error, job.stage = (
                    "error",
                    f"Provider '{job.provider}' unavailable",
                    "error",
                )
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
            dest = os.path.realpath(dest)
            # Providers share album directories. Serialize that destination so one job cannot
            # claim another job's file (or overwrite it while it is being inspected).
            lock = self._dest_locks.setdefault(dest, asyncio.Lock())
            await stack.enter_async_context(lock)
            await session.refresh(job)
            if job.status != "queued":
                return
            os.makedirs(dest, exist_ok=True)
            expected = os.path.join(dest, f"{filename}.{self.settings.default_format}")
            if os.path.islink(expected):
                raise RuntimeError("El archivo de destino es un enlace simbólico")
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

            # Retry loop: a *transient* failure (429 / network / hung) is retried with exponential
            # backoff up to download_max_retries; anything else is terminal on the first hit.
            max_retries = max(0, int(self.settings.download_max_retries))
            attempt = 0
            while True:
                try:
                    await consume()
                    break
                except SubprocessError as exc:
                    if attempt < max_retries and is_transient(str(exc)):
                        attempt += 1
                        delay = min(30, 3 * 2 ** (attempt - 1))  # 3s, 6s, 12s, … capped 30s
                        log.warning(
                            "download job %s transient failure, retry %d/%d in %ds",
                            job_id,
                            attempt,
                            max_retries,
                            delay,
                        )
                        job.stage = f"retrying ({attempt}/{max_retries})"
                        with contextlib.suppress(Exception):
                            await session.commit()
                        await self._publish(job, message=f"Reintentando ({attempt}/{max_retries})…")
                        await asyncio.sleep(delay)
                        continue
                    log.warning("download job %s failed: %s", job_id, exc)
                    job.status, job.error, job.stage = (
                        "error",
                        humanize_error(str(exc))[:4000],
                        "error",
                    )
                    await session.commit()
                    await self._publish(job)
                    return
                except Exception as exc:  # noqa: BLE001
                    log.exception("download job %s crashed", job_id)
                    job.status, job.error, job.stage = (
                        "error",
                        humanize_error(repr(exc))[:4000],
                        "error",
                    )
                    await session.commit()
                    await self._publish(job)
                    return

            # ── success ──
            if provider.id in {"spotdl", "ytdlp"}:
                expected = os.path.join(dest, f"{filename}.{self.settings.default_format}")
                if os.path.islink(expected):
                    raise RuntimeError("El archivo de destino es un enlace simbólico")
                job.result_path = (
                    expected if os.path.isfile(expected) and os.path.getsize(expected) > 0 else None
                )
            else:
                job.result_path = _pick_new_audio(dest, before)
            if job.result_path is None:
                raise RuntimeError(
                    "La herramienta terminó sin producir una única pista de audio válida"
                )

            job.stage = "tagging"
            await session.commit()
            await self._publish(job)
            await tag_audio(job.result_path, track)

            # Probe the real file: record its actual bitrate, and flag a gross duration mismatch
            # (usually a wrong-source resolution) as a non-fatal warning on the job.
            measured_bitrate: int | None = None
            if job.result_path:
                probe = await ffprobe_audio(job.result_path)
                if probe:
                    measured_bitrate = probe["bitrate_kbps"]
                    if duration_mismatch(track.duration_s, probe["duration_s"]):
                        job.error = (
                            f"⚠️ Duración inesperada: {probe['duration_s']}s frente a "
                            f"{track.duration_s}s esperados — revisa que sea la pista correcta."
                        )
                        log.warning(
                            "job %s duration mismatch: got %ss, expected %ss",
                            job_id,
                            probe["duration_s"],
                            track.duration_s,
                        )
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
                    measured_bitrate=measured_bitrate,
                )
            except Exception:
                log.exception("library bookkeeping failed for job %s", job_id)
                raise
            job.status, job.progress_pct, job.stage = "done", 100.0, "done"
            job.library_status = "pending" if self.navidrome is not None else "unconfigured"
            job.library_confirmed = None
            job.library_attempts = 0
            job.library_prepared = True
            job.library_error = (
                None
                if self.navidrome is not None
                else "Navidrome no está configurado. Puedes escuchar el archivo aquí."
            )
            job.library_next_retry_at = None
            await session.commit()
            await self._publish(job)

        self.library_sync.wake()

    async def recheck(self, job_id: str) -> bool:
        await self.library_sync.retry(job_id)
        return True
