"""Read real audio properties from a downloaded file with ffprobe.

Used to (a) record the *actual* bitrate/format in the library instead of inferring it from settings,
and (b) sanity-check that the produced file's duration roughly matches the requested track — a gross
mismatch usually means the downloader resolved the wrong source. ffprobe ships with ffmpeg in the
image.
"""

from __future__ import annotations

import asyncio
import json

from backend.app.logging import get_logger

log = get_logger(__name__)


async def ffprobe_audio(path: str) -> dict | None:
    """Return {'duration_s': int|None, 'bitrate_kbps': int|None} for ``path``, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,bit_rate",
            "-of",
            "json",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
    except (OSError, asyncio.TimeoutError) as exc:
        log.warning("ffprobe failed for %s: %s", path, exc)
        return None
    if proc.returncode != 0:
        return None
    try:
        fmt = (json.loads(out or b"{}").get("format")) or {}
    except (ValueError, TypeError):
        return None
    duration = fmt.get("duration")
    bit_rate = fmt.get("bit_rate")
    return {
        "duration_s": round(float(duration)) if duration else None,
        "bitrate_kbps": round(int(bit_rate) / 1000) if bit_rate else None,
    }


def duration_mismatch(expected_s: int | None, actual_s: int | None) -> bool:
    """True when the produced duration is grossly off the requested track (likely wrong source).

    Tolerant on purpose (>30s AND >25%) so normal variance — silent intros/outros, alt masters —
    doesn't trip it; only a wrong song or a short preview does.
    """
    if not expected_s or not actual_s:
        return False
    diff = abs(actual_s - expected_s)
    return diff > 30 and diff > 0.25 * expected_s
