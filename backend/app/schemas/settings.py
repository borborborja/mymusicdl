"""Settings / credential DTOs."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CredentialIn(BaseModel):
    # e.g. {"token": "..."} for Tidal/Qobuz, {"arl": "..."} for Deezer
    data: dict[str, str]


class CredentialDTO(BaseModel):
    provider: str
    enabled: bool = False
    status: str | None = None


class SettingsDTO(BaseModel):
    metadata: str
    providers: list[dict] = Field(default_factory=list)
    credentials: list[CredentialDTO] = Field(default_factory=list)
