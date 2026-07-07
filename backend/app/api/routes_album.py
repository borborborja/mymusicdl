"""Expand an album into its individual tracks (each decorated with qualities + library status).

The UI lets the user pick tracks and download them one by one or as a batch — we never fetch a whole
album as a single blob."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.app.deps import get_aggregator
from backend.app.schemas.search import AlbumDetailDTO

router = APIRouter()


@router.get("/album/{provider}/{album_id}", response_model=AlbumDetailDTO)
async def album(
    provider: str,
    album_id: str,
    providers: str | None = None,
    lossless_only: bool = False,
    aggregator=Depends(get_aggregator),
):
    providers_filter = {p for p in providers.split(",") if p} if providers else None
    try:
        detail = await aggregator.get_album(
            provider, album_id, providers_filter=providers_filter, lossless_only=lossless_only
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Metadata source error: {exc}") from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Album not found")
    return detail
