"""DB-backed tests: enqueue dedup and the bot brain (search/persist/enqueue across a restart)."""

from __future__ import annotations

from backend.app.bots.core import BotCore, split_limit
from backend.app.downloads.service import EnqueueItem, enqueue_tracks
from backend.app.schemas.search import (
    AlbumDetailDTO,
    AlbumResultDTO,
    LibraryMatchDTO,
    ProviderQualitiesDTO,
    QualityOptionDTO,
    TrackResultDTO,
)


# ── enqueue dedup ──
async def test_enqueue_dedup_active_and_within_batch(session_factory, queue, registry, settings):
    item = EnqueueItem(
        provider="spotdl",
        quality=1,
        track={"artist": "Radiohead", "title": "Creep", "album": "Pablo Honey", "isrc": "GB123"},
    )
    async with session_factory() as s:
        r1 = await enqueue_tracks(s, queue, registry, settings, [item], origin="web")
    assert len(r1.queued) == 1 and not r1.skipped

    async with session_factory() as s:  # same track still queued → skipped
        r2 = await enqueue_tracks(s, queue, registry, settings, [item], origin="web")
    assert not r2.queued and len(r2.skipped) == 1 and r2.skipped[0].reason == "duplicate"

    async with session_factory() as s:  # duplicate within one batch collapses
        dup = EnqueueItem(provider="ytdlp", quality=1, track={"artist": "A", "title": "B"})
        r3 = await enqueue_tracks(s, queue, registry, settings, [dup, dup], origin="web")
    assert len(r3.queued) == 1 and len(r3.skipped) == 1


# ── split_limit ──
def test_split_limit():
    assert split_limit("creep 10", 6) == ("creep", 10)
    assert split_limit("creep", 6) == ("creep", 6)
    assert split_limit("track 99", 6) == ("track 99", 6)  # out of range → ignored


# ── bot brain ──
def _q(tier):
    return QualityOptionDTO(tier=tier, label=f"t{tier}", lossless=tier >= 2, fmt="mp3")


def _track(title, tier=1, in_lib=False, up=False):
    return TrackResultDTO(
        title=title,
        artist="Jarabe de Palo",
        album="La flaca",
        isrc=f"ES{title}",
        providers=[ProviderQualitiesDTO(provider="spotdl", label="spotDL", qualities=[_q(tier)])],
        library=LibraryMatchDTO(in_library=in_lib, can_upgrade=up),
        best_tier=tier,
    )


class _FakeAgg:
    async def search(self, *, kind, query, artist=None, limit=6):
        class R:
            pass

        r = R()
        if kind == "song":
            r.tracks = [_track("La flaca", in_lib=True), _track("Depende", up=True)]
        else:
            r.albums = [
                AlbumResultDTO(
                    id="a1",
                    title="La flaca",
                    artist="Jarabe de Palo",
                    provider="musicbrainz",
                    total_tracks=2,
                )
            ]
        return r

    async def get_album(self, provider, album_id):
        return AlbumDetailDTO(
            album=AlbumResultDTO(
                id=album_id, title="La flaca", artist="Jarabe de Palo", provider=provider
            ),
            tracks=[_track("La flaca"), _track("Dos días")],
        )


def _core(session_factory, queue, registry, settings):
    return BotCore(
        aggregator=_FakeAgg(),
        registry=registry,
        settings=settings,
        queue=queue,
        session_factory=session_factory,
    )


async def test_bot_song_item_library_flags(session_factory, queue, registry, settings):
    core = _core(session_factory, queue, registry, settings)
    tracks = await core.search_songs("la flaca")
    items = [core.song_item(t) for t in tracks]
    assert items[0]["in_library"] and not items[0]["can_upgrade"]
    assert items[1]["can_upgrade"]


async def test_bot_selection_survives_restart(session_factory, queue, registry, settings):
    core = _core(session_factory, queue, registry, settings)
    tracks = await core.search_songs("la flaca")
    await core.save_selection("telegram", "555", "songs", [core.song_item(t) for t in tracks])

    core2 = _core(session_factory, queue, registry, settings)  # simulate a restart
    sel = await core2.load_selection("telegram", "555")
    assert sel and sel["mode"] == "songs" and len(sel["items"]) == 2
    status = await core2.enqueue_song_item(sel["items"][0], origin="telegram", chat_id="555")
    assert status == "queued"


async def test_bot_song_enqueue_sets_origin_chat(session_factory, queue, registry, settings):
    from sqlalchemy import select

    from backend.app.db.models import Job

    core = _core(session_factory, queue, registry, settings)
    tracks = await core.search_songs("la flaca")
    item = core.song_item(tracks[0])
    await core.enqueue_song_item(item, origin="telegram", chat_id="777")
    async with session_factory() as s:
        job = (await s.execute(select(Job).where(Job.origin == "telegram"))).scalars().first()
    assert job is not None and job.origin_chat == "777"


async def test_bot_album_enqueue_track_by_track_no_origin_chat(
    session_factory, queue, registry, settings
):
    from sqlalchemy import select

    from backend.app.db.models import Job

    core = _core(session_factory, queue, registry, settings)
    queued, skipped = await core.enqueue_album("musicbrainz", "a1", origin="matrix")
    assert queued == 2 and skipped == 0
    async with session_factory() as s:
        jobs = (await s.execute(select(Job).where(Job.origin == "matrix"))).scalars().all()
    assert len(jobs) == 2 and all(j.origin_chat is None for j in jobs)  # no per-track ping spam
