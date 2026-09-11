"""Family catalog, preferences and discovery. All audio credentials stay server-side."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from starlette.background import BackgroundTask

from backend.app.api.routes_media import _ticket, _valid_ticket
from backend.app.db.engine import get_session
from backend.app.db.models import CatalogTrack, FamilyArtist
from backend.app.deps import AuthDep, SettingsDep
from backend.app.downloads.service import EnqueueError
from backend.app.library.catalog import searchable
from backend.app.schemas.collection import (
    ArtistChoice,
    CollectionTrack,
    DownloadChoice,
    PreferenceChange,
)

router = APIRouter()


@router.get("/catalog/tracks")
async def catalog_tracks(
    request: Request,
    q: str = "",
    artist: str = "",
    album: str = "",
    snapshot: str | None = None,
    sort: Literal["artist", "title", "recent"] = "artist",
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=100),
    session=Depends(get_session),
):
    catalog = request.app.state.catalog
    before = await catalog.status()
    if snapshot is not None and snapshot != before["generation"]:
        raise HTTPException(409, "La biblioteca ha cambiado. Vuelve a la primera página.")
    filters = [CatalogTrack.server_key == catalog.server_key, CatalogTrack.available.is_(True)]
    if q.strip():
        filters.extend(
            CatalogTrack.search_text.contains(searchable(word), autoescape=True)
            for word in q.split()
        )
    if artist:
        filters.append(CatalogTrack.artist == artist)
    if album:
        filters.append(CatalogTrack.album == album)
    order = {
        "artist": (CatalogTrack.artist, CatalogTrack.album, CatalogTrack.title),
        "title": (CatalogTrack.title,),
        "recent": (CatalogTrack.updated_at.desc(),),
    }[sort]
    rows = list(
        await session.scalars(
            select(CatalogTrack)
            .where(*filters)
            .order_by(*order, CatalogTrack.id)
            .offset(offset)
            .limit(limit)
        )
    )
    total = await session.scalar(select(func.count()).select_from(CatalogTrack).where(*filters))
    cards = await request.app.state.family.cards(
        [CollectionTrack(**json.loads(r.payload)["track"]) for r in rows]
    )
    after = await catalog.status()
    if after["generation"] != before["generation"]:
        raise HTTPException(409, "La biblioteca ha cambiado. Vuelve a la primera página.")
    return {"items": cards, "total": total, "offset": offset, "status": after}


@router.post("/catalog/refresh", status_code=202)
async def catalog_refresh(request: Request, _auth: AuthDep):
    if request.app.state.navidrome is None:
        raise HTTPException(409, "Navidrome no está configurado.")
    request.app.state.catalog.wake()
    return {"status": "pending"}


@router.get("/family/artist-search")
async def artist_search(request: Request, q: str = Query(min_length=1, max_length=200)):
    try:
        return await request.app.state.aggregator._musicbrainz.artist_choices(q)
    except httpx.HTTPError:
        raise HTTPException(
            502,
            "No se pudo consultar los artistas. Vuelve a intentarlo; tus selecciones se conservan.",
        ) from None


@router.get("/family/artists")
async def artists(session=Depends(get_session)):
    return [
        {"id": a.id, "name": a.name}
        for a in await session.scalars(select(FamilyArtist).order_by(FamilyArtist.name))
    ]


@router.put("/family/artists")
async def choose_artist(choice: ArtistChoice, request: Request, _auth: AuthDep):
    try:
        await request.app.state.family.artist(choice)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@router.delete("/family/artists/{artist_id}")
async def remove_artist(artist_id: str, request: Request, _auth: AuthDep):
    await request.app.state.family.remove_artist(artist_id)
    return {"ok": True}


@router.put("/family/tracks")
async def preference(change: PreferenceChange, request: Request, _auth: AuthDep):
    try:
        return await request.app.state.family.preference(change)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/family/tracks")
async def family_tracks(
    request: Request,
    mode: Literal["saved", "favorite", "dismissed"] = "saved",
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=100),
):
    return await request.app.state.family.selected(mode, offset=offset, limit=limit)


@router.post("/family/tracks/{track_id}/download")
async def download(track_id: str, choice: DownloadChoice, request: Request, _auth: AuthDep):
    try:
        return await request.app.state.family.download(track_id, choice)
    except (ValueError, EnqueueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/discovery")
async def discovery(
    request: Request,
    settings: SettingsDep,
    kind: Literal["local", "external"] = "local",
    session=Depends(get_session),
):
    catalog, family = request.app.state.catalog, request.app.state.family
    if kind == "external":
        result = await request.app.state.discovery.snapshot()
        result["items"] = await family.suggestions(result.pop("tracks"))
        return result
    # Daily deterministic sampling avoids loading the whole library and keeps rows stable.
    rows = await session.scalars(
        select(CatalogTrack)
        .where(CatalogTrack.server_key == catalog.server_key, CatalogTrack.available.is_(True))
        .order_by(func.substr(CatalogTrack.id, datetime.now(timezone.utc).day, 32), CatalogTrack.id)
        .limit(120)
    )
    counts, tracks = {}, []
    for row in rows:
        track = CollectionTrack(**json.loads(row.payload)["track"])
        if counts.get(track.artist, 0) >= 2:
            continue
        counts[track.artist] = counts.get(track.artist, 0) + 1
        track.reason = "De nuestra biblioteca"
        tracks.append(track)
        if len(tracks) == 20:
            break
    return {
        "enabled": settings.discovery_enabled,
        "items": await family.cards(tracks),
        "status": await catalog.status(),
    }


async def _catalog_file(track_id, request, session):
    row = await session.get(CatalogTrack, track_id)
    if not row or row.server_key != request.app.state.catalog.server_key or not row.available:
        raise HTTPException(404, "Pista no disponible en este catálogo.")
    if request.app.state.navidrome is None:
        raise HTTPException(503, "Navidrome no está disponible.")
    return row


@router.post("/catalog/tracks/{track_id}/playback")
async def playback(
    track_id: str,
    request: Request,
    settings: SettingsDep,
    _auth: AuthDep,
    session=Depends(get_session),
):
    await _catalog_file(track_id, request, session)
    token = _ticket(f"catalog/{track_id}", settings.app_secret)
    return {"url": f"/api/catalog/audio/{quote(track_id, safe='')}?token={token}"}


@router.api_route("/catalog/audio/{track_id}", methods=["GET", "HEAD"])
async def stream(
    track_id: str,
    request: Request,
    settings: SettingsDep,
    token: str = "",
    session=Depends(get_session),
):
    if not _valid_ticket(token, f"catalog/{track_id}", settings.app_secret):
        raise HTTPException(401, "Reabre el reproductor para renovar el acceso.")
    row = await _catalog_file(track_id, request, session)
    nav = request.app.state.navidrome
    params = {**nav._auth_params(), "id": row.navidrome_id}
    headers = {"Accept-Encoding": "identity"}
    if "range" in request.headers:
        headers["Range"] = request.headers["range"]
    # The download endpoint streams the original audio and supports byte ranges. Never redirect
    # a browser to a signed upstream URL, nor forward arbitrary response headers/cookies.
    upstream = None
    try:
        upstream = await nav._http.send(
            nav._http.build_request(
                request.method, f"{nav.base_url}/rest/download", params=params, headers=headers
            ),
            stream=True,
        )
        content_type = upstream.headers.get("content-type", "application/octet-stream")
        if upstream.status_code == 416:
            content_range = upstream.headers.get("content-range")
            await upstream.aclose()
            return Response(
                status_code=416, headers={"Content-Range": content_range} if content_range else {}
            )
        if upstream.status_code not in (200, 206) or not (
            content_type.startswith("audio/") or content_type.startswith("application/octet-stream")
        ):
            raise ValueError("Audio unavailable")
        safe_headers = {
            key: upstream.headers[key]
            for key in ("content-length", "content-range", "accept-ranges")
            if key in upstream.headers
        }
        safe_headers.update(
            {
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            }
        )
        if request.method == "HEAD":
            await upstream.aclose()
            return Response(
                status_code=upstream.status_code, headers=safe_headers, media_type=content_type
            )
    except (httpx.HTTPError, ValueError):
        if upstream is not None:
            await upstream.aclose()
        raise HTTPException(
            502, "No se pudo escuchar el archivo de Navidrome. Vuelve a intentarlo."
        ) from None

    async def chunks():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        chunks(),
        status_code=upstream.status_code,
        media_type=content_type,
        headers=safe_headers,
        background=BackgroundTask(upstream.aclose),
    )
