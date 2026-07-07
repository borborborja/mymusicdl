"""Library status: live Navidrome quality lookup, recent downloads, and manual rescan."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.app.db.engine import get_session
from backend.app.db.models import LibraryItem
from backend.app.deps import AuthDep
from backend.app.navidrome.matcher import library_quality
from backend.app.schemas.search import LibraryMatchDTO, QualityOptionDTO

router = APIRouter()


class LibraryItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    artist: str
    album: str | None = None
    fmt: str
    bitrate_kbps: int | None = None
    quality_tier: int
    source_provider: str
    file_path: str
    downloaded_at: datetime | None = None


@router.get("/library/match", response_model=LibraryMatchDTO)
async def match(
    artist: str,
    title: str,
    album: str | None = None,
    duration_s: int | None = None,
    isrc: str | None = None,
    request: Request = None,  # type: ignore[assignment]
):
    navidrome = request.app.state.navidrome
    found = await library_quality(
        navidrome, artist=artist, title=title, album=album, duration_s=duration_s, isrc=isrc
    )
    if not found:
        return LibraryMatchDTO(in_library=False)
    return LibraryMatchDTO(
        in_library=True,
        navidrome_id=found.get("navidrome_id"),
        quality=QualityOptionDTO(**found["quality"].to_dict()),
    )


@router.get("/library/items", response_model=list[LibraryItemDTO])
async def items(limit: int = 100, session=Depends(get_session)):
    res = await session.execute(
        select(LibraryItem).order_by(LibraryItem.downloaded_at.desc()).limit(min(limit, 500))
    )
    return list(res.scalars().all())


@router.post("/library/rescan")
async def rescan(_auth: AuthDep, request: Request):
    navidrome = request.app.state.navidrome
    if navidrome is None:
        raise HTTPException(status_code=400, detail="Navidrome not configured")
    status = await navidrome.start_scan(full=True)
    return {"scanning": status}
