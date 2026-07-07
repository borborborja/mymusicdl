"""Preview endpoint: resolve a playable audio stream URL for a track (see downloads.preview)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.deps import SettingsDep
from backend.app.downloads.preview import resolve_stream_url

router = APIRouter()


@router.get("/preview")
async def preview(
    settings: SettingsDep,
    artist: str,
    title: str,
    source_url: str | None = None,
):
    url = await resolve_stream_url(settings, artist=artist, title=title, source_url=source_url)
    if not url:
        raise HTTPException(status_code=404, detail="No se pudo resolver una vista previa.")
    return {"url": url}
