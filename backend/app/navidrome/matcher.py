"""Match a candidate track against the Navidrome library and read its stored quality.

Powers the "already in library @ <quality>" badge and the re-download-to-better-quality decision.
"""

from __future__ import annotations

import re
import unicodedata

from backend.app.providers.base import Quality, QualityOption

_LOSSLESS_SUFFIXES = {"flac", "alac", "wav", "aiff", "ape", "wv"}


def norm(s: str | None) -> str:
    """Lowercase, strip accents/punctuation/feat-clauses, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[\(\[]\s*feat[^\)\]]*[\)\]]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def _song_isrcs(song: dict) -> set[str]:
    """ISRCs Navidrome reports for a song (OpenSubsonic ``isrc`` — string or list), upper-cased."""
    raw = song.get("isrc")
    if not raw:
        return set()
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    return {str(v).strip().upper() for v in values if str(v).strip()}


def quality_from_song(song: dict) -> QualityOption:
    suffix = (song.get("suffix") or "").lower()
    bitrate = song.get("bitRate")
    if suffix in _LOSSLESS_SUFFIXES:
        tier = Quality.FLAC_16  # Subsonic can't distinguish 16- vs 24-bit reliably
    else:
        tier = Quality.MP3_320 if (bitrate or 0) >= 256 else Quality.MP3_128
    return QualityOption(quality=tier, fmt=suffix or "?", bitrate_kbps=bitrate, note="in library")


def _match_result(song: dict) -> dict:
    return {
        "navidrome_id": song.get("id"),
        "suffix": song.get("suffix"),
        "bitrate_kbps": song.get("bitRate"),
        "quality": quality_from_song(song),
    }


async def library_quality(
    navidrome,
    *,
    artist: str,
    title: str,
    album: str | None = None,
    duration_s: int | None = None,
    isrc: str | None = None,
) -> dict | None:
    """Return {navidrome_id, suffix, bitrate_kbps, quality} for a library match, else None.

    ISRC is the strong signal when both sides have it (Navidrome exposes it via OpenSubsonic): a
    matching ISRC confirms the recording even if the title differs (remaster/edit suffixes), and a
    differing ISRC rules a candidate out (avoids false positives across distinct recordings that
    share title/artist/duration). When either side lacks an ISRC we fall back to the fuzzy
    normalized-title + artist + duration match.
    """
    if navidrome is None:
        return None
    try:
        result = await navidrome.search3(f"{artist} {title}", song_count=25)
    except Exception:
        return None

    songs = result.get("song", []) or []
    want_isrc = (isrc or "").strip().upper() or None
    na, nt = norm(artist), norm(title)
    for song in songs:
        cand_isrcs = _song_isrcs(song)
        if want_isrc and cand_isrcs:
            # Both sides have an ISRC — trust it exclusively for this candidate.
            if want_isrc in cand_isrcs:
                return _match_result(song)
            continue
        if norm(song.get("title", "")) != nt:
            continue
        if na and na not in norm(song.get("artist", "")):
            continue
        if duration_s and song.get("duration"):
            if abs(int(song["duration"]) - duration_s) > 12:
                continue
        return _match_result(song)
    return None
