"""Fetch the latest GitHub release (tag + markdown body) for a tool's changelog."""

from __future__ import annotations

import httpx

from backend.app.logging import get_logger

log = get_logger(__name__)


async def latest_release(
    repo: str | None, token: str | None = None
) -> tuple[str | None, str | None]:
    """Return (tag_name, body) from GitHub's releases/latest, or (None, None)."""
    if not repo:
        return None, None
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/releases/latest", headers=headers
            )
            if resp.status_code != 200:
                return None, None
            data = resp.json()
            return data.get("tag_name"), data.get("body")
    except httpx.HTTPError:
        return None, None
