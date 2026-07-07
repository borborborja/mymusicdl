"""Health / readiness."""

from __future__ import annotations

import os
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from backend.app.db.base import utcnow
from backend.app.db.engine import get_session
from backend.app.db.models import Job
from backend.app.deps import SettingsDep

router = APIRouter()

# A running job whose progress hasn't updated in this long is likely stuck (the idle-timeout
# watchdog should normally catch it first; this surfaces the state to an operator regardless).
_STALE_RUNNING_S = 900


@router.get("/health")
async def health(request: Request, settings: SettingsDep, session=Depends(get_session)):
    navidrome = request.app.state.navidrome
    registry = request.app.state.registry
    worker = getattr(request.app.state, "worker", None)
    queue = getattr(request.app.state, "queue", None)

    navidrome_ok: bool | None = None
    if navidrome is not None:
        try:
            navidrome_ok = await navidrome.ping()
        except Exception:
            navidrome_ok = False

    music_writable = (
        os.access(settings.music_library_path, os.W_OK)
        if os.path.isdir(settings.music_library_path)
        else False
    )

    # Queue depth + hung-job detection (DB is the source of truth for job state).
    db_ok = True
    queued = running = stale = 0
    try:
        queued = (
            await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.kind == "download", Job.status == "queued")
            )
        ) or 0
        running = (
            await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.kind == "download", Job.status == "running")
            )
        ) or 0
        cutoff = utcnow() - timedelta(seconds=_STALE_RUNNING_S)
        stale = (
            await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.kind == "download",
                    Job.status == "running",
                    Job.updated_at < cutoff,
                )
            )
        ) or 0
    except Exception:
        db_ok = False

    pool = worker.stats() if worker is not None else {"workers": 0, "active": 0}

    return {
        "app": "ok",
        "db_ok": db_ok,
        "navidrome_configured": navidrome is not None,
        "navidrome_ok": navidrome_ok,
        "music_path": settings.music_library_path,
        "music_writable": music_writable,
        "queue": {
            "waiting": queue.qsize() if queue is not None else queued,
            "queued": queued,
            "running": running,
            "stale_running": stale,
            "workers": pool["workers"],
            "active": pool["active"],
        },
        "providers": registry.infos(),
    }
