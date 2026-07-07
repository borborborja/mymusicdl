"""Enqueue downloads (single track or a batch). Albums are expanded to individual tracks client-side
and arrive here as a list of items — we never download an album as a single blob."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.db.engine import get_session
from backend.app.deps import AuthDep, SettingsDep, get_queue, get_registry
from backend.app.downloads.service import EnqueueError, EnqueueItem, enqueue_tracks
from backend.app.schemas.jobs import DownloadRequest, JobDTO

router = APIRouter()


@router.post("/downloads", response_model=list[JobDTO])
async def create_downloads(
    req: DownloadRequest,
    _auth: AuthDep,
    settings: SettingsDep,
    session=Depends(get_session),
    queue=Depends(get_queue),
    registry=Depends(get_registry),
):
    items = [
        EnqueueItem(provider=i.provider, quality=i.quality, track=i.track.model_dump())
        for i in req.items
    ]
    try:
        result = await enqueue_tracks(session, queue, registry, settings, items, origin="web")
    except EnqueueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [JobDTO.model_validate(j) for j in result.queued]
