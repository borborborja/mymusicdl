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


class ConcurrencyIn(BaseModel):
    value: int = Field(ge=1, le=16)


class LayoutIn(BaseModel):
    template: str


class SettingsDTO(BaseModel):
    metadata: str
    providers: list[dict] = Field(default_factory=list)
    credentials: list[CredentialDTO] = Field(default_factory=list)
    download_concurrency: int = 2
    download_layout: str = "{artist}/{album}/{title}"
    music_library_path: str = ""
