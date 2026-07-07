"""List / inspect / cancel / retry jobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.app.db.engine import get_session
from backend.app.db.models import Job
from backend.app.deps import AuthDep, get_queue
from backend.app.schemas.jobs import JobDTO
from sqlalchemy import delete, select

router = APIRouter()

_TERMINAL = ("done", "error", "canceled")


@router.get("/jobs", response_model=list[JobDTO])
async def list_jobs(
    status: str | None = None,
    kind: str | None = None,
    limit: int = 100,
    session=Depends(get_session),
):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(min(limit, 500))
    if status:
        stmt = stmt.where(Job.status == status)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get("/jobs/{job_id}", response_model=JobDTO)
async def get_job(job_id: str, session=Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobDTO)
async def cancel_job(job_id: str, _auth: AuthDep, request: Request, session=Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "queued":
        job.status, job.stage = "canceled", "canceled"
        await session.commit()
    elif job.status == "running":
        request.app.state.worker.cancel(job_id)
        # the worker flips the row to "canceled" once the subprocess is torn down
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobDTO)
async def retry_job(
    job_id: str, _auth: AuthDep, session=Depends(get_session), queue=Depends(get_queue)
):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("error", "canceled"):
        raise HTTPException(status_code=400, detail="Only failed or canceled jobs can be retried")
    job.status, job.error, job.progress_pct, job.stage = "queued", None, 0.0, None
    await session.commit()
    await queue.put(job.id)
    return job


@router.post("/jobs/{job_id}/recheck", response_model=JobDTO)
async def recheck_job(job_id: str, _auth: AuthDep, request: Request, session=Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    await request.app.state.worker.recheck(job_id)
    return job


@router.post("/jobs/clear")
async def clear_finished_jobs(_auth: AuthDep, session=Depends(get_session)):
    """Remove all finished (done/error/canceled) jobs; keep queued/running ones."""
    res = await session.execute(delete(Job).where(Job.status.in_(_TERMINAL)))
    await session.commit()
    return {"deleted": res.rowcount or 0}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, _auth: AuthDep, session=Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in _TERMINAL:
        raise HTTPException(status_code=400, detail="Cancela el trabajo antes de borrarlo")
    await session.delete(job)
    await session.commit()
    return {"deleted": job_id}
