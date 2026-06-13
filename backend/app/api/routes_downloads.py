"""Enqueue downloads (single track or a batch). Albums are expanded to individual tracks client-side
and arrive here as a list of items — we never download an album as a single blob."""
from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from backend.app.db.engine import get_session
from backend.app.db.models import Job
from backend.app.deps import AuthDep, SettingsDep, get_queue, get_registry
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
    if not req.items:
        raise HTTPException(status_code=400, detail="No items to download")

    batch_id = str(uuid4()) if len(req.items) > 1 else None
    jobs: list[Job] = []
    for item in req.items:
        provider = registry.get(item.provider)
        if provider is None:
            raise HTTPException(status_code=400, detail=f"Unknown provider '{item.provider}'")
        if not provider.enabled:
            raise HTTPException(
                status_code=409, detail=f"Provider '{item.provider}' is not enabled (missing credentials)"
            )
        track = item.track.model_dump()
        track.setdefault("provider_id", item.provider)
        job = Job(
            id=str(uuid4()),
            kind="download",
            status="queued",
            provider=item.provider,
            track_json=json.dumps(track),
            requested_quality=item.quality,
            dest_dir=settings.music_library_path,
            title=f"{item.track.artist} - {item.track.title}",
            batch_id=batch_id,
        )
        session.add(job)
        jobs.append(job)

    await session.commit()
    for job in jobs:
        await queue.put(job.id)
    return [JobDTO.model_validate(j) for j in jobs]
