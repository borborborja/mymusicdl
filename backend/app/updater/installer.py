"""Build the pip command that upgrades a tool *inside the mounted venv* so the upgrade persists."""
from __future__ import annotations

from backend.app.config import Settings


def pip_update_cmd(settings: Settings, pkg: str) -> list[str]:
    return [settings.tool_bin("python"), "-m", "pip", "install", "-U", pkg]
