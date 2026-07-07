"""Settings + provider credentials. Adding a credential flips a paid provider on without a restart."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from backend.app.db.engine import get_session
from backend.app.db.models import Credential
from backend.app.db.repo import get_setting, set_setting
from backend.app.deps import AuthDep, SettingsDep, get_aggregator
from backend.app.downloads.paths import DEFAULT_LAYOUT, validate_layout
from backend.app.schemas.settings import (
    ConcurrencyIn,
    CredentialDTO,
    CredentialIn,
    LayoutIn,
    SettingsDTO,
)
from backend.app.security import encrypt_secret

router = APIRouter()

# Metadata catalog credentials live in the same table as paid providers but aren't in the provider
# registry (Spotify drives search, not downloads). Keep the list here so the routes can special-case.
_METADATA_PROVIDERS = {"spotify"}


@router.get("/settings", response_model=SettingsDTO)
async def get_settings_route(
    request: Request,
    settings: SettingsDep,
    session=Depends(get_session),
    aggregator=Depends(get_aggregator),
):
    registry = request.app.state.registry
    res = await session.execute(select(Credential))
    creds = [
        CredentialDTO(provider=c.provider, enabled=c.enabled, status=c.status)
        for c in res.scalars().all()
    ]
    concurrency_raw = await get_setting(session, "download_concurrency")
    concurrency = int(concurrency_raw) if concurrency_raw else settings.download_concurrency
    layout = await get_setting(session, "download_layout") or settings.download_layout
    return SettingsDTO(
        metadata=aggregator.metadata_name(),
        providers=registry.infos(),
        credentials=creds,
        download_concurrency=concurrency,
        download_layout=layout,
        music_library_path=settings.music_library_path,
    )


@router.put("/settings/concurrency")
async def set_concurrency_route(
    body: ConcurrencyIn, _auth: AuthDep, request: Request, session=Depends(get_session)
):
    await set_setting(session, "download_concurrency", str(body.value))
    applied = await request.app.state.worker.set_concurrency(body.value)
    return {"download_concurrency": applied}


@router.put("/settings/layout")
async def set_layout_route(body: LayoutIn, _auth: AuthDep, session=Depends(get_session)):
    template = body.template.strip() or DEFAULT_LAYOUT
    try:
        validate_layout(template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await set_setting(session, "download_layout", template)
    return {"download_layout": template}


@router.put("/settings/credentials/{provider}")
async def set_credential(
    provider: str,
    body: CredentialIn,
    _auth: AuthDep,
    settings: SettingsDep,
    request: Request,
    session=Depends(get_session),
):
    registry = request.app.state.registry
    is_metadata = provider in _METADATA_PROVIDERS
    if not is_metadata and registry.get(provider) is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    encrypted = encrypt_secret(json.dumps(body.data), settings.app_secret)
    cred = await session.get(Credential, provider)
    if cred is None:
        session.add(
            Credential(provider=provider, enabled=True, data_json=encrypted, status="untested")
        )
    else:
        cred.data_json, cred.enabled, cred.status = encrypted, True, "untested"
    await session.commit()
    if is_metadata:
        _apply_spotify(request, body.data)
    else:
        registry.set_credentials(provider, body.data)
    return {"provider": provider, "enabled": True}


@router.delete("/settings/credentials/{provider}")
async def delete_credential(
    provider: str, _auth: AuthDep, request: Request, session=Depends(get_session)
):
    cred = await session.get(Credential, provider)
    if cred is not None:
        cred.enabled = False
        await session.commit()
    if provider in _METADATA_PROVIDERS:
        _apply_spotify(request, None)
    else:
        request.app.state.registry.set_credentials(provider, None)
    return {"provider": provider, "enabled": False}


def _apply_spotify(request: Request, data: dict | None) -> None:
    """Apply Spotify creds to both the search catalog and the spotdl downloader."""
    request.app.state.aggregator.set_spotify_credentials(data)
    sp = request.app.state.registry.get("spotdl")
    if sp is not None and hasattr(sp, "set_spotify_credentials"):
        sp.set_spotify_credentials(data)
