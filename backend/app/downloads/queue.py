"""Durable-ish download queue.

Job *state* lives in the SQLite ``jobs`` table; this class is the in-memory signaling channel the
worker pool blocks on. On startup ``rehydrate`` re-enqueues anything left ``queued``/``running`` by
a previous (crashed) container so no download is silently lost.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Job
from backend.app.logging import get_logger

log = get_logger(__name__)


class DownloadQueue:
    def __init__(self) -> None:
        self._q: asyncio.Queue[str] = asyncio.Queue()

    async def put(self, job_id: str) -> None:
        await self._q.put(job_id)

    async def get(self) -> str:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    async def rehydrate(self, session: AsyncSession) -> int:
        """Reset interrupted download jobs to queued and re-enqueue them in creation order."""
        await session.execute(
            update(Job)
            .where(Job.kind == "download", Job.status == "running")
            .values(status="queued", stage=None, progress_pct=0.0)
        )
        await session.commit()
        res = await session.execute(
            select(Job.id)
            .where(Job.kind == "download", Job.status == "queued")
            .order_by(Job.created_at)
        )
        ids = [row[0] for row in res.all()]
        for job_id in ids:
            await self._q.put(job_id)
        if ids:
            log.info("Rehydrated %d pending download job(s)", len(ids))
        return len(ids)
