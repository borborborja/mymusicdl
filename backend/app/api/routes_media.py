"""Browser playback of the exact local download, with range support and scoped tickets."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backend.app.db.engine import get_session
from backend.app.db.models import Job, LibraryItem
from backend.app.deps import AuthDep, SettingsDep
from backend.app.library.files import AUDIO_TYPES, library_file

router = APIRouter()
_TICKET_TTL = 3600


def _signature(resource: str, expires: int, secret: str) -> str:
    return hmac.new(
        secret.encode(), f"media:{resource}:{expires}".encode(), hashlib.sha256
    ).hexdigest()


def _ticket(resource: str, secret: str) -> str:
    expires = int(time.time()) + _TICKET_TTL
    return f"{expires}.{_signature(resource, expires, secret)}"


def _valid_ticket(token: str, resource: str, secret: str) -> bool:
    try:
        raw, signature = token.split(".", 1)
        expires = int(raw)
        return int(time.time()) < expires <= int(time.time()) + _TICKET_TTL and hmac.compare_digest(
            signature, _signature(resource, expires, secret)
        )
    except (ValueError, OverflowError):
        return False


async def _file(kind: str, item_id: str, settings, session):
    if kind == "jobs":
        item = await session.get(Job, item_id)
        if item is not None and (item.kind != "download" or item.status != "done"):
            raise HTTPException(409, "La descarga todavía no está terminada.")
        path = item.result_path if item else None
    else:
        if not item_id.isdecimal():
            raise HTTPException(404, "Pista no encontrada.")
        item = await session.get(LibraryItem, int(item_id))
        path = item.file_path if item else None
    if item is None:
        raise HTTPException(404, "Pista no encontrada.")
    try:
        return library_file(settings.music_path, path)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/jobs/{item_id}/playback")
async def job_playback(
    item_id: str, _auth: AuthDep, settings: SettingsDep, session=Depends(get_session)
):
    await _file("jobs", item_id, settings, session)
    token = _ticket(f"jobs/{item_id}", settings.app_secret)
    return {"url": f"/api/media/jobs/{item_id}?token={token}"}


@router.post("/library/items/{item_id}/playback")
async def library_playback(
    item_id: str, _auth: AuthDep, settings: SettingsDep, session=Depends(get_session)
):
    await _file("library", item_id, settings, session)
    token = _ticket(f"library/{item_id}", settings.app_secret)
    return {"url": f"/api/media/library/{item_id}?token={token}"}


@router.api_route("/media/{kind}/{item_id}", methods=["GET", "HEAD"])
async def media(
    kind: Literal["jobs", "library"],
    item_id: str,
    settings: SettingsDep,
    token: str = Query(default=""),
    session=Depends(get_session),
):
    if not _valid_ticket(token, f"{kind}/{item_id}", settings.app_secret):
        raise HTTPException(401, "Reabre el reproductor para renovar el acceso al archivo.")
    path = await _file(kind, item_id, settings, session)
    return FileResponse(
        path,
        media_type=AUDIO_TYPES[path.suffix.lower()],
        filename=path.name,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
