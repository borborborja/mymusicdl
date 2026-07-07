"""Messaging-bot status + configuration.

Config set here is stored encrypted in the DB and the affected bot is hot-reloaded — no restart.
A bot configured via ``.env`` takes precedence and is reported with ``source: "env"`` (read-only
here; change it in the environment).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.app.deps import AuthDep
from backend.app.schemas.bots import BotConfigIn, BotStatusDTO

router = APIRouter()


@router.get("/bots", response_model=list[BotStatusDTO])
async def list_bots(request: Request):
    return request.app.state.bots.status()


@router.put("/bots/{name}")
async def set_bot(name: str, body: BotConfigIn, _auth: AuthDep, request: Request):
    manager = request.app.state.bots
    data = {k: v for k, v in body.data.items() if v not in (None, "")}
    try:
        await manager.save_config(name, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    status = next((s for s in manager.status() if s["name"] == name), None)
    return {"ok": True, "status": status}


@router.delete("/bots/{name}")
async def delete_bot(name: str, _auth: AuthDep, request: Request):
    manager = request.app.state.bots
    try:
        await manager.delete_config(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
