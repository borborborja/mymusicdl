"""Resolve a directly-playable audio stream URL for the source that *would* be downloaded.

Lets the UI preview the real track (via yt-dlp `-g`) before committing to a download — the honest
"is this the right file?" check, since the played audio is the same source spotdl/yt-dlp resolves.
Results are cached briefly (the URLs expire, but repeated previews of the same row are common).
"""

from __future__ import annotations

import asyncio

from backend.app.config import Settings
from backend.app.logging import get_logger
from backend.app.metadata.cache import TTLCache

log = get_logger(__name__)

# googlevideo URLs expire in a handful of minutes; keep the cache well under that.
_cache = TTLCache(ttl_s=120)


def _target(artist: str, title: str, source_url: str | None) -> str:
    url = source_url or ""
    if any(d in url for d in ("youtube.com", "youtu.be")):
        return url
    return f"ytsearch1:{artist} {title}".strip()


async def resolve_stream_url(
    settings: Settings, *, artist: str, title: str, source_url: str | None = None
) -> str | None:
    """Return a direct audio stream URL, or None if it can't be resolved."""
    target = _target(artist, title, source_url)
    if not target or target == "ytsearch1:":
        return None
    cached = _cache.get(target)
    if cached is not None:
        return cached or None  # "" cached = known-unresolvable

    cmd = [
        settings.tool_bin("yt-dlp"),
        "-f",
        "bestaudio",
        "-g",  # print the resolved media URL, don't download
        "--no-playlist",
        "--no-warnings",
        target,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
    except (OSError, asyncio.TimeoutError) as exc:
        log.warning("preview resolve failed for %r: %s", target, exc)
        return None
    url = ""
    if proc.returncode == 0 and out:
        # yt-dlp may print video+audio URLs on separate lines; take the first.
        url = out.decode("utf-8", "replace").strip().splitlines()[0] if out.strip() else ""
    _cache.set(target, url)
    return url or None
