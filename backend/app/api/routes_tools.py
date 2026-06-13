"""Tool versions, changelog, and in-app updates."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.app.db.engine import get_session
from backend.app.db.models import Job
from backend.app.db.repo import list_tools
from backend.app.deps import AuthDep
from backend.app.schemas.jobs import JobDTO
from backend.app.schemas.tools import ToolDTO
from backend.app.updater.service import TRACKED_TOOLS

router = APIRouter()


@router.get("/tools", response_model=list[ToolDTO])
async def get_tools(session=Depends(get_session)):
    return await list_tools(session)


@router.post("/tools/check")
async def check_tools(_auth: AuthDep, request: Request):
    await request.app.state.updater.check_all()
    return {"status": "checked"}


@router.post("/tools/{name}/update", response_model=JobDTO)
async def update_tool(name: str, _auth: AuthDep, request: Request, session=Depends(get_session)):
    if name not in {t["name"] for t in TRACKED_TOOLS}:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{name}'")
    job_id = await request.app.state.updater.start_update(name)
    return await session.get(Job, job_id)
