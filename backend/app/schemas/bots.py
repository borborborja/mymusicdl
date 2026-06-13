"""Messaging-bot status + config DTOs."""
from __future__ import annotations

from pydantic import BaseModel, Field


class BotStatusDTO(BaseModel):
    name: str
    enabled: bool = False
    configured: bool = False
    source: str | None = None  # "env" | "db" | None
    running: bool = False
    connected: bool = False
    identity: str | None = None
    allowed_count: int = 0
    error: str | None = None


class BotConfigIn(BaseModel):
    # Telegram: {"token": "...", "allowed_users": "111,222"}
    # Matrix:   {"homeserver": "...", "user_id": "...", "access_token": "...",
    #            "allowed_users": "@a:hs,@b:hs", "room_id": "!opt:hs"}
    data: dict[str, str] = Field(default_factory=dict)
