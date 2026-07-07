"""Health / readiness."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request

from backend.app.db.engine import get_session
from backend.app.deps import SettingsDep

router = APIRouter()


@router.get("/health")
async def health(request: Request, settings: SettingsDep, session=Depends(get_session)):
    navidrome = request.app.state.navidrome
    registry = request.app.state.registry

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

    return {
        "app": "ok",
        "navidrome_configured": navidrome is not None,
        "navidrome_ok": navidrome_ok,
        "music_path": settings.music_library_path,
        "music_writable": music_writable,
        "providers": registry.infos(),
    }
