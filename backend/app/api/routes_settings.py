"""Settings + provider credentials. Adding a credential flips a paid provider on without a restart."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from backend.app.db.engine import get_session
from backend.app.db.models import Credential
from backend.app.deps import AuthDep, SettingsDep, get_aggregator
from backend.app.schemas.settings import CredentialDTO, CredentialIn, SettingsDTO
from backend.app.security import encrypt_secret

router = APIRouter()


@router.get("/settings", response_model=SettingsDTO)
async def get_settings_route(request: Request, session=Depends(get_session), aggregator=Depends(get_aggregator)):
    registry = request.app.state.registry
    res = await session.execute(select(Credential))
    creds = [
        CredentialDTO(provider=c.provider, enabled=c.enabled, status=c.status)
        for c in res.scalars().all()
    ]
    return SettingsDTO(
        metadata=aggregator.metadata_name(), providers=registry.infos(), credentials=creds
    )


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
    if registry.get(provider) is None:
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
    request.app.state.registry.set_credentials(provider, None)
    return {"provider": provider, "enabled": False}
