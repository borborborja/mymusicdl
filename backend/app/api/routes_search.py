"""Search by artist / album / song, with optional provider + lossless filters."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.app.deps import get_aggregator
from backend.app.schemas.search import SearchResponseDTO

router = APIRouter()


@router.get("/search", response_model=SearchResponseDTO)
async def search(
    q: str = "",
    kind: str = "song",
    limit: int = 20,
    providers: str | None = None,
    lossless_only: bool = False,
    artist: str | None = None,
    album: str | None = None,
    year: str | None = None,
    aggregator=Depends(get_aggregator),
):
    providers_filter = {p for p in providers.split(",") if p} if providers else None
    try:
        return await aggregator.search(
            kind=kind,
            query=q,
            limit=min(limit, 40),
            providers_filter=providers_filter,
            lossless_only=lossless_only,
            artist=artist,
            album=album,
            year=year,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Metadata source error: {exc}") from exc


@router.get("/search/source")
async def search_source(aggregator=Depends(get_aggregator)):
    """Which catalog source is active (spotify when credentials present, else musicbrainz)."""
    return {"metadata": aggregator.metadata_name()}
