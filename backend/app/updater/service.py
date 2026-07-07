"""Updater coordinator.

Periodically (and on demand) compares each tracked tool's installed version (in the mounted venv)
against PyPI, fetches the GitHub changelog, and exposes an in-app "update" that runs
``pip install -U`` inside that venv — streaming pip output to the SSE broker as a job.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from backend.app.config import Settings
from backend.app.db.base import utcnow
from backend.app.db.models import Job
from backend.app.db.repo import upsert_tool
from backend.app.downloads.progress import ProgressBroker
from backend.app.downloads.runner import SubprocessError, stream_subprocess
from backend.app.logging import get_logger
from backend.app.providers.base import ProgressEvent
from backend.app.schemas.jobs import JobDTO
from backend.app.updater.changelog import latest_release
from backend.app.updater.installer import pip_update_cmd
from backend.app.updater.versions import installed_version, is_newer, latest_version

log = get_logger(__name__)

# pypi package name → GitHub repo for changelog. streamrip/tiddl power the (optional) paid sources.
TRACKED_TOOLS = [
    {"name": "spotdl", "repo": "spotDL/spotify-downloader", "managed": True},
    {"name": "yt-dlp", "repo": "yt-dlp/yt-dlp", "managed": True},
    {"name": "streamrip", "repo": "nathom/streamrip", "managed": True},
    {"name": "tiddl", "repo": "oskvr37/tiddl", "managed": True},
]


class Updater:
    def __init__(
        self, *, settings: Settings, session_factory, broker: ProgressBroker, queue=None
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.broker = broker
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        try:
            await asyncio.sleep(10)  # let the app settle / venv bootstrap finish
            while self._running:
                try:
                    await self.check_all()
                except Exception:
                    log.exception("periodic version check failed")
                try:
                    await self._prune_jobs()
                except Exception:
                    log.exception("periodic job prune failed")
                await asyncio.sleep(max(1, self.settings.version_check_interval_hours) * 3600)
        except asyncio.CancelledError:
            pass

    async def _prune_jobs(self) -> None:
        from backend.app.db.repo import prune_old_jobs

        async with self.session_factory() as session:
            removed = await prune_old_jobs(session, self.settings.job_retention_days)
        if removed:
            log.info("Pruned %d old finished job(s)", removed)

    async def check_all(self) -> None:
        async with self.session_factory() as session:
            for tool in TRACKED_TOOLS:
                name = tool["name"]
                inst = await installed_version(self.settings, name)
                latest = await latest_version(name)
                tag, body = await latest_release(tool["repo"], self.settings.github_token)
                await upsert_tool(
                    session,
                    name,
                    installed_version=inst,
                    latest_version=latest,
                    update_available=is_newer(inst, latest),
                    repo=tool["repo"],
                    latest_tag=tag,
                    changelog=body,
                    last_checked_at=utcnow(),
                    managed=tool["managed"],
                )
        await self.broker.publish({"type": "tools"})
        log.info("Version check complete")

    async def start_update(self, name: str) -> str:
        job_id = str(uuid4())
        async with self.session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    kind="tool_update",
                    status="running",
                    provider=name,
                    title=f"Update {name}",
                    stage="installing",
                )
            )
            await session.commit()
        asyncio.create_task(self._run_update(job_id, name))
        return job_id

    async def _publish_job(self, job: Job, message: str | None = None) -> None:
        payload = {"type": "job", "job": JobDTO.model_validate(job).model_dump(mode="json")}
        if message:
            payload["message"] = message
        await self.broker.publish(payload)

    async def _run_update(self, job_id: str, name: str) -> None:
        cmd = pip_update_cmd(self.settings, name)

        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return

            def parse(line: str) -> ProgressEvent:
                return ProgressEvent(job_id=job_id, stage="installing", message=line)

            try:
                async for ev in stream_subprocess(
                    cmd, job_id=job_id, parse=parse, settings=self.settings
                ):
                    await self._publish_job(job, message=ev.message)

                inst = await installed_version(self.settings, name)
                latest = await latest_version(name)
                await upsert_tool(
                    session,
                    name,
                    installed_version=inst,
                    latest_version=latest,
                    update_available=is_newer(inst, latest),
                    last_checked_at=utcnow(),
                )
                job.status, job.stage, job.progress_pct = "done", "done", 100.0
                await session.commit()
                await self._publish_job(job)
                await self.broker.publish({"type": "tools"})
            except SubprocessError as exc:
                job.status, job.error, job.stage = "error", str(exc)[:4000], "error"
                await session.commit()
                await self._publish_job(job)
            except Exception as exc:  # noqa: BLE001
                job.status, job.error, job.stage = "error", repr(exc)[:4000], "error"
                await session.commit()
                await self._publish_job(job)
