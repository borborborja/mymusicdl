"""Tool (downloader CLI) DTO."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ToolDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    installed_version: str | None = None
    latest_version: str | None = None
    update_available: bool = False
    repo: str | None = None
    latest_tag: str | None = None
    changelog: str | None = None
    last_checked_at: datetime | None = None
    managed: bool = True
