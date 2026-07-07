"""Pure-logic unit tests: matcher, cache, query builders, error classification, probe."""

from __future__ import annotations

import time

import pytest

from backend.app.downloads.errors import humanize_error, is_transient
from backend.app.downloads.probe import duration_mismatch
from backend.app.metadata.cache import TTLCache
from backend.app.metadata.musicbrainz import _lucene, _lucene_escape
from backend.app.metadata.spotify import _fielded
from backend.app.navidrome.matcher import _song_isrcs, library_quality, norm, quality_from_song
from backend.app.providers.base import Quality


# ── TTL cache ──
def test_ttlcache_hit_and_expire():
    c = TTLCache(ttl_s=0.15)
    c.set("k", 42)
    assert c.get("k") == 42
    time.sleep(0.2)
    assert c.get("k") is None


def test_ttlcache_invalidate_and_clear():
    c = TTLCache(ttl_s=60)
    c.set("a", 1)
    c.invalidate("a")
    assert c.get("a") is None
    c.set("b", 2)
    c.clear()
    assert c.get("b") is None


# ── norm / ISRC helpers ──
def test_norm_strips_accents_feat_and_punct():
    assert norm("Café  (feat. X)!!") == "cafe"
    assert norm("Radiohead") == "radiohead"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("GBAYE0000001", {"GBAYE0000001"}),
        (["gbaye0000001", "  "], {"GBAYE0000001"}),
        (None, set()),
        ("", set()),
    ],
)
def test_song_isrcs(raw, expected):
    assert _song_isrcs({"isrc": raw} if raw is not None else {}) == expected


def test_quality_from_song_lossless_vs_lossy():
    assert quality_from_song({"suffix": "flac"}).quality == Quality.FLAC_16
    assert quality_from_song({"suffix": "mp3", "bitRate": 320}).quality == Quality.MP3_320
    assert quality_from_song({"suffix": "mp3", "bitRate": 128}).quality == Quality.MP3_128


# ── library_quality matching (fake Navidrome) ──
class _FakeNav:
    def __init__(self, songs):
        self.songs = songs

    async def search3(self, query, song_count=25):
        return {"song": self.songs}


async def test_library_quality_isrc_match_beats_title_variant():
    nav = _FakeNav(
        [
            {
                "id": "2",
                "title": "Creep (Remastered)",
                "artist": "Radiohead",
                "suffix": "flac",
                "isrc": "GBAYE9200001",
            }
        ]
    )
    m = await library_quality(nav, artist="Radiohead", title="Creep", isrc="GBAYE9200001")
    assert m and m["navidrome_id"] == "2"


async def test_library_quality_isrc_mismatch_rejected():
    nav = _FakeNav(
        [
            {
                "id": "1",
                "title": "Creep",
                "artist": "Radiohead",
                "suffix": "flac",
                "isrc": "XXDIFFERENT01",
                "duration": 238,
            }
        ]
    )
    m = await library_quality(
        nav, artist="Radiohead", title="Creep", duration_s=238, isrc="GBAYE9200001"
    )
    assert m is None


async def test_library_quality_fuzzy_fallback_without_isrc():
    nav = _FakeNav(
        [
            {
                "id": "3",
                "title": "Creep",
                "artist": "Radiohead",
                "suffix": "mp3",
                "bitRate": 320,
                "duration": 238,
            }
        ]
    )
    m = await library_quality(nav, artist="Radiohead", title="Creep", duration_s=238)
    assert m and m["navidrome_id"] == "3"


# ── query builders ──
def test_spotify_fielded():
    assert _fielded("creep", "track", artist="radiohead") == "track:creep artist:radiohead"
    # no filters → verbatim passthrough (advanced syntax preserved)
    assert _fielded("artist:radiohead track:creep", "track") == "artist:radiohead track:creep"
    # ':' in a value is sanitized
    assert "::" not in _fielded("a:b", "track", artist="c:d")


def test_musicbrainz_lucene_word_by_word_and_escape():
    q = _lucene("Barcelona", "recording", artist="mercury caballé")
    assert 'recording:"Barcelona"' in q
    assert 'artist:"mercury"' in q and 'artist:"caballé"' in q  # non-adjacent words
    assert _lucene_escape('a"b\\c') == 'a\\"b\\\\c'
    assert _lucene("free text", "recording") == "free text"  # no filters → verbatim


# ── error classification ──
@pytest.mark.parametrize(
    "text,transient",
    [
        ("HTTP Error 429: Too Many Requests", True),
        ("Temporary failure in name resolution", True),
        ("Sin salida durante 300s — descarga colgada", True),
        ("No results found", False),
        ("Permission denied", False),
    ],
)
def test_is_transient(text, transient):
    assert is_transient(text) is transient


def test_humanize_error_maps_known_and_passes_unknown():
    assert (
        "rate limit" in humanize_error("HTTP Error 429").lower()
        or "limit" in humanize_error("HTTP Error 429").lower()
    )
    assert humanize_error("totally novel error") == "totally novel error"


# ── probe duration mismatch ──
@pytest.mark.parametrize(
    "expected,actual,flag",
    [
        (238, 30, True),  # 30s clip vs full song → wrong
        (238, 245, False),  # small variance → ok
        (238, None, False),  # unknown → no flag
        (None, 100, False),
        (200, 260, True),  # 60s off (>30 and >25%)
        (200, 225, False),  # 25s off → ok
    ],
)
def test_duration_mismatch(expected, actual, flag):
    assert duration_mismatch(expected, actual) is flag
