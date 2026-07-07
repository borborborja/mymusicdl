"""Version probing: installed (from the mounted tools venv) vs latest (PyPI)."""

from __future__ import annotations

import asyncio

import httpx
from packaging.version import InvalidVersion
from packaging.version import parse as parse_version

from backend.app.config import Settings
from backend.app.logging import get_logger

log = get_logger(__name__)


async def installed_version(settings: Settings, pkg: str) -> str | None:
    """Read the package version from inside the tools venv (its interpreter, not the app's)."""
    python = settings.tool_bin("python")
    code = (
        "import importlib.metadata as m\n"
        "try:\n"
        f"    print(m.version({pkg!r}))\n"
        "except Exception:\n"
        "    print('')\n"
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            python,
            "-c",
            code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except FileNotFoundError:
        return None
    version = out.decode().strip()
    return version or None


async def latest_version(pkg: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://pypi.org/pypi/{pkg}/json")
            if resp.status_code != 200:
                return None
            return resp.json().get("info", {}).get("version")
    except httpx.HTTPError:
        return None


def is_newer(installed: str | None, latest: str | None) -> bool:
    if not installed or not latest:
        return False
    try:
        return parse_version(latest) > parse_version(installed)
    except InvalidVersion:
        return latest != installed
