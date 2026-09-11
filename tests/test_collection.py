"""Discovery release acceptance: coherent catalogs, shared selections, failures and audio tickets."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.db.base import utcnow
from backend.app.db.engine import get_session
from backend.app.db.models import CatalogTrack, DiscoveryCache, Job
from backend.app.deps import settings_dep
from backend.app.downloads.progress import ProgressBroker
from backend.app.downloads.service import EnqueueItem
from backend.app.library.catalog import Catalog
from backend.app.library.discovery import Discovery, ListenBrainz
from backend.app.library.family import Family
from backend.app.main import create_app
from backend.app.metadata.aggregator import SearchAggregator, _dedup_artists, _dedup_tracks
from backend.app.metadata.base import ArtistRef
from backend.app.providers.base import TrackRef
from backend.app.schemas.collection import ArtistChoice, CollectionTrack, PreferenceChange


async def test_search_outage_is_unknown_and_does_not_cache_absence(env):
    nav = SimpleNamespace(search3=AsyncMock(side_effect=httpx.ConnectError("private URL")))
    aggregator = SearchAggregator(
        settings=env.settings,
        registry=SimpleNamespace(enabled=lambda: []),
        navidrome=nav,
        session_factory=env.db,
    )
    track = TrackRef(provider_id="musicbrainz", title="Song", artist="Artist")
    try:
        result = await aggregator._decorate(track, None, False)
        assert result.library.availability_known is False
        nav.search3.side_effect = None
        nav.search3.return_value = {"song": []}
        result = await aggregator._decorate(track, None, False)
        assert result.library.availability_known is True
        assert result.library.in_library is False
        aggregator.navidrome = None
        aggregator.invalidate_library()
        result = await aggregator._decorate(track, None, False)
        assert result.library.availability_known is False
    finally:
        await aggregator.aclose()

    env.nav.fail_offset = 0
    response = await env.api.get("/api/library/match", params={"title": "Song", "artist": "Artist"})
    assert response.status_code == 200
    assert response.json()["availability_known"] is False
    assert "private" not in response.text


class Nav:
    def __init__(self, n=601):
        self.songs = [
            {
                "id": str(i),
                "title": f"Song {i:04}",
                "artist": f"Artist {i % 15}",
                "album": "Album",
                "path": f"Artist/Song {i}.mp3",
                "duration": 3,
                "musicBrainzId": str(uuid4()),
                "suffix": "mp3",
                "bitRate": 128,
            }
            for i in range(n)
        ]
        self.fail_offset = None
        self.scan = False
        self.calls = []

    async def search3(self, query, *, song_count, song_offset=0, **kw):
        self.calls.append(song_offset)
        if self.fail_offset is not None and song_offset >= self.fail_offset:
            raise httpx.ConnectError("upstream private URL")
        # A server that caps pages below the client's requested count.
        return {"song": self.songs[song_offset : song_offset + min(song_count, 73)]}

    async def get_scan_status(self):
        return {"scanning": self.scan, "count": len(self.songs)}


@pytest_asyncio.fixture
async def env(session_factory, queue, registry, tmp_path):
    settings = Settings(
        _env_file=None,
        navidrome_url="http://nav.test",
        navidrome_user="family",
        navidrome_password="private-nav-password",
        app_secret="ticket-secret",
        app_shared_password="family-password",
        music_library_path=str(tmp_path),
    )
    nav, broker = Nav(), ProgressBroker()
    catalog = Catalog(
        settings=settings, session_factory=session_factory, navidrome=nav, broker=broker
    )
    family = Family(
        settings=settings,
        session_factory=session_factory,
        catalog=catalog,
        broker=broker,
        queue=queue,
        registry=registry,
    )
    discovery = Discovery(
        settings=settings,
        session_factory=session_factory,
        broker=broker,
        client=SimpleNamespace(recommendations=AsyncMock(return_value=[]), aclose=AsyncMock()),
    )
    app = create_app()
    app.state.catalog, app.state.family, app.state.discovery = catalog, family, discovery
    app.state.navidrome, app.state.settings = nav, settings
    app.state.aggregator = SimpleNamespace(
        _musicbrainz=SimpleNamespace(artist_choices=AsyncMock(return_value=[]))
    )

    async def session_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[settings_dep] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-App-Password": "family-password"},
    ) as api:
        yield SimpleNamespace(
            catalog=catalog,
            family=family,
            discovery=discovery,
            nav=nav,
            api=api,
            db=session_factory,
            queue=queue,
            settings=settings,
        )


async def test_complete_catalog_pagination_and_server_filters(env):
    await env.catalog.sync()
    ids = []
    for offset in range(0, 601, 100):
        result = (
            await env.api.get("/api/catalog/tracks", params={"offset": offset, "limit": 100})
        ).json()
        assert result["total"] == 601
        assert result["status"]["stale"] is False
        ids.extend(t["track"]["catalog_id"] for t in result["items"])
    assert len(ids) == len(set(ids)) == 601
    assert env.nav.calls[-1] == 601
    found = (await env.api.get("/api/catalog/tracks", params={"q": "song 0600"})).json()
    assert [c["track"]["title"] for c in found["items"]] == ["Song 0600"]
    assert (await env.api.get("/api/catalog/tracks", params={"q": "%"})).json()["total"] == 0


async def test_failed_refresh_preserves_snapshot_and_changes_availability_to_unknown(env):
    await env.catalog.sync()
    env.nav.songs[0]["title"] = "Partial change"
    env.nav.fail_offset = 73
    await env.catalog.sync()
    data = (await env.api.get("/api/catalog/tracks", params={"q": "Song 0000"})).json()
    assert len(data["items"]) == 1
    assert data["items"][0]["availability"] == "unknown"
    assert data["status"]["error"] and "private" not in json.dumps(data)
    env.nav.fail_offset = None
    await env.catalog.sync()
    assert (await env.api.get("/api/catalog/tracks", params={"q": "Partial change"})).json()[
        "total"
    ] == 1


async def test_canceled_and_overlapping_scans_do_not_replace_catalog(env):
    await env.catalog.sync()
    initial = await env.catalog.status()
    env.nav.scan = True
    await env.catalog.sync()
    assert (await env.catalog.status())["updated_at"] == initial["updated_at"]
    env.nav.scan = False
    env.nav.search3 = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await env.catalog.sync()
    async with env.db() as session:
        assert await session.scalar(select(func.count()).select_from(CatalogTrack)) == 601
    assert not env.catalog.refreshing


async def test_recordings_and_homonyms_are_not_merged():
    artists = [
        ArtistRef(id="a", name="Same", provider="musicbrainz"),
        ArtistRef(id="b", name="Same", provider="musicbrainz"),
    ]
    assert len(_dedup_artists(artists)) == 2
    tracks = [
        TrackRef("musicbrainz", "Song", "Artist", ext_ids={"mbid": str(uuid4())}) for _ in range(2)
    ]
    assert len(_dedup_tracks(tracks)) == 2
    assert (
        EnqueueItem("ytdlp", 1, tracks[0].to_dict()).dedup_key
        != EnqueueItem("ytdlp", 1, tracks[1].to_dict()).dedup_key
    )


async def test_shared_save_favorite_and_restart_never_enqueue(env):
    track = CollectionTrack(title="Song", artist="Artist", ext_ids={"mbid": str(uuid4())})
    await asyncio.gather(
        env.family.preference(PreferenceChange(track=track, saved=True)),
        env.family.preference(PreferenceChange(track=track, favorite=True)),
    )
    assert env.queue.puts == []
    replacement = Family(
        settings=env.settings,
        session_factory=env.db,
        catalog=env.catalog,
        broker=env.family.broker,
        queue=env.queue,
        registry=env.family.registry,
    )
    card = (await replacement.selected("saved"))["items"][0]
    assert card["saved"] and card["favorite"]
    await replacement.preference(PreferenceChange(track=track, saved=False))
    assert (await replacement.selected("favorite"))["items"][0]["favorite"]


async def test_artist_cap_is_atomic_and_homonyms_have_independent_ids(env):
    choices = [ArtistChoice(id=uuid4(), name="Same") for _ in range(6)]
    results = await asyncio.gather(*(env.family.artist(c) for c in choices), return_exceptions=True)
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert len(await env.discovery.seeds()) == 5
    await env.family.remove_artist(str(choices[0].id))
    await env.family.artist(choices[-1])
    assert len(await env.discovery.seeds()) == 5


async def test_pending_to_downloading_to_confirmed_keeps_identity(env):
    song = env.nav.songs[0]
    track = CollectionTrack(
        title=song["title"],
        artist=song["artist"],
        album="Album",
        ext_ids={"mbid": song["musicBrainzId"]},
    )
    card = await env.family.preference(PreferenceChange(track=track, saved=True))
    response = await env.api.post(
        f"/api/family/tracks/{card['id']}/download", json={"provider": "ytdlp", "quality": 1}
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    assert (await env.family.cards([track]))[0]["availability"] == "downloading"
    again = await env.api.post(f"/api/family/tracks/{card['id']}/download", json={})
    assert again.json()["job_id"] == job_id and len(env.queue.puts) == 1
    async with env.db() as session:
        job = await session.get(Job, job_id)
        job.status, job.library_status = "done", "pending"
        await session.commit()
    assert (await env.family.cards([track]))[0]["availability"] == "pending"
    await env.catalog.sync()
    async with env.db() as session:
        job = await session.get(Job, job_id)
        job.library_confirmed = True
        await session.commit()
    final = (await env.family.cards([track]))[0]
    assert final["id"] == card["id"] and final["availability"] == "available"
    async with env.db() as session:
        await session.delete(await session.get(Job, job_id))
        await session.commit()
    assert (await env.family.selected("saved"))["items"][0]["availability"] == "available"


async def test_confirmed_file_updates_catalog_without_full_resync(env):
    env.nav.songs = []
    await env.catalog.sync()
    await env.catalog.accept_song({"id": "new", "title": "New", "artist": "Artist"})
    assert (await env.api.get("/api/catalog/tracks")).json()["total"] == 1


async def test_discovery_cache_outage_retains_old_suggestions_and_dismissal(env):
    artist = ArtistChoice(id=uuid4(), name="Seed")
    await env.family.artist(artist)
    tracks = [
        CollectionTrack(
            title=f"Song {i}",
            artist=f"Artist {i // 4}",
            ext_ids={"mbid": str(uuid4())},
            seed_id=str(artist.id),
        ).model_dump()
        for i in range(50)
    ]
    env.discovery.client.recommendations.return_value = tracks
    await env.discovery.refresh()
    snapshot = await env.discovery.snapshot()
    cards = await env.family.suggestions(snapshot["tracks"])
    assert len(cards) == 20
    assert max(sum(c["track"]["artist"] == a["track"]["artist"] for c in cards) for a in cards) <= 2
    await env.family.preference(
        PreferenceChange(track=CollectionTrack(**cards[0]["track"]), dismissed=True)
    )
    async with env.db() as session:
        cache = await session.get(DiscoveryCache, "family")
        cache.updated_at = utcnow() - timedelta(days=2)
        await session.commit()
    env.discovery.client.recommendations.side_effect = httpx.ReadTimeout("private URL")
    await env.discovery.refresh()
    stale = await env.discovery.snapshot()
    assert stale["stale"] and stale["error"] and len(stale["tracks"]) == 50
    assert cards[0]["id"] not in {c["id"] for c in await env.family.suggestions(stale["tracks"])}
    await env.family.preference(
        PreferenceChange(track=CollectionTrack(**cards[0]["track"]), dismissed=False)
    )
    assert cards[0]["id"] in {c["id"] for c in await env.family.suggestions(stale["tracks"])}


async def test_suggestions_for_changed_seeds_are_not_published(env):
    choice = ArtistChoice(id=uuid4(), name="Old")
    await env.family.artist(choice)

    async def changed(artists):
        await env.family.remove_artist(str(choice.id))
        return [{"title": "Old suggestion"}]

    env.discovery.client.recommendations.side_effect = changed
    await env.discovery.refresh()
    assert (await env.discovery.snapshot())["tracks"] == []


async def test_disabled_external_discovery_never_calls_network(env):
    await env.family.artist(ArtistChoice(id=uuid4(), name="Seed"))
    env.settings.discovery_external_enabled = False
    await env.discovery.refresh()
    assert not (await env.discovery.snapshot())["enabled"]
    env.discovery.client.recommendations.assert_not_called()


async def test_listenbrainz_uses_only_seed_and_bulk_metadata_requests():
    requests = []
    seed, recording, artist = str(uuid4()), str(uuid4()), str(uuid4())

    async def handle(request):
        requests.append(request)
        if "lb-radio" in request.url.path:
            return httpx.Response(200, json={artist: [{"recording_mbid": recording}]})
        return httpx.Response(
            200,
            json={
                recording: {
                    "recording": {"name": "Song", "length": 3100},
                    "artist": {"name": "Artist", "artists": [{"artist_mbid": artist}]},
                    "release": {"name": "Album"},
                }
            },
        )

    client = ListenBrainz()
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url="https://api.listenbrainz.org", transport=httpx.MockTransport(handle)
    )
    try:
        results = await client.recommendations([SimpleNamespace(id=seed, name="Seed")])
        assert results[0]["ext_ids"]["mbid"] == recording
        assert len(requests) == 2
        assert all(
            r.method == "GET" and "authorization" not in r.headers and not r.content
            for r in requests
        )
        assert requests[1].url.params["recording_mbids"] == recording
        assert "pop_begin" in requests[0].url.params
    finally:
        await client.aclose()


async def test_preferences_and_playback_require_auth(env):
    payload = {"track": {"title": "Song", "artist": "Artist"}, "saved": True}
    response = await env.api.put(
        "/api/family/tracks", json=payload, headers={"X-App-Password": "wrong"}
    )
    assert response.status_code == 401
    await env.catalog.sync()
    card = (await env.api.get("/api/catalog/tracks")).json()["items"][0]
    key = card["catalog_id"]
    assert (
        await env.api.post(
            f"/api/catalog/tracks/{key}/playback", headers={"X-App-Password": "wrong"}
        )
    ).status_code == 401
    assert (await env.api.get(f"/api/catalog/audio/{key}")).status_code == 401
    ticket = (await env.api.post(f"/api/catalog/tracks/{key}/playback")).json()["url"]
    other = (await env.api.get("/api/catalog/tracks")).json()["items"][1]["catalog_id"]
    assert (await env.api.get(ticket.replace(key, other))).status_code == 401
    assert "private-nav-password" not in ticket


async def test_catalog_ids_do_not_cross_server_accounts(env):
    await env.catalog.sync()
    card = (await env.api.get("/api/catalog/tracks")).json()["items"][0]
    env.catalog.server_key = "different-account"
    assert (await env.api.get("/api/catalog/tracks")).json()["total"] == 0
    assert (
        await env.api.post(f"/api/catalog/tracks/{card['catalog_id']}/playback")
    ).status_code == 404
    response = await env.api.put("/api/family/tracks", json={"track": card["track"], "saved": True})
    assert response.status_code == 400


async def test_paging_rejects_mixed_snapshot_generations(env):
    await env.catalog.sync()
    first = (await env.api.get("/api/catalog/tracks")).json()
    generation = first["status"]["generation"]
    assert generation
    await env.catalog.accept_song({"id": "another", "title": "Another"})
    response = await env.api.get(
        "/api/catalog/tracks", params={"offset": 40, "snapshot": generation}
    )
    assert response.status_code == 409
    assert (await env.api.get("/api/catalog/tracks")).json()["total"] == 602


async def test_removed_file_keeps_pending_preference_but_is_not_playable(env):
    await env.catalog.sync()
    card = (await env.api.get("/api/catalog/tracks")).json()["items"][0]
    await env.api.put("/api/family/tracks", json={"track": card["track"], "saved": True})
    env.nav.songs = []
    await env.catalog.sync()
    saved = (await env.api.get("/api/family/tracks")).json()["items"][0]
    assert saved["saved"] and saved["availability"] == "missing"
    assert saved["catalog_id"] is None
    assert (
        await env.api.post(f"/api/catalog/tracks/{card['catalog_id']}/playback")
    ).status_code == 404


async def test_local_copy_remains_playable_after_job_history_is_deleted(env, tmp_path):
    from backend.app.db.models import LibraryItem

    path = tmp_path / "old.mp3"
    path.write_bytes(b"local audio")
    track = CollectionTrack(title="Original", artist="Artist", album="Album")
    await env.family.preference(PreferenceChange(track=track, saved=True))
    async with env.db() as session:
        session.add(
            LibraryItem(
                title=track.title,
                artist=track.artist,
                album=track.album,
                file_path=str(path),
                fmt="mp3",
                quality_tier=1,
                source_provider="ytdlp",
            )
        )
        await session.commit()
    card = (await env.family.selected("saved"))["items"][0]
    assert card["local_item_id"] is not None and card["job_id"] is None
    ticket = (await env.api.post(f"/api/library/items/{card['local_item_id']}/playback")).json()
    assert (await env.api.get(ticket["url"])).content == b"local audio"


async def test_nav_audio_error_body_is_not_forwarded_to_browser(env):
    await env.catalog.sync()
    card = (await env.api.get("/api/catalog/tracks")).json()["items"][0]
    env.nav.base_url = "http://nav.test"
    env.nav._auth_params = lambda: {"t": "secret-token"}
    env.nav._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"password": "upstream secret"})
        )
    )
    try:
        ticket = (await env.api.post(f"/api/catalog/tracks/{card['catalog_id']}/playback")).json()
        response = await env.api.get(ticket["url"])
        assert response.status_code == 502
        assert "upstream secret" not in response.text and "secret-token" not in response.text
    finally:
        await env.nav._http.aclose()


async def test_fresh_discovery_cache_does_not_request_external_data(env):
    await env.family.artist(ArtistChoice(id=uuid4(), name="Seed"))
    await env.discovery.refresh()
    env.discovery.client.recommendations.reset_mock()
    await env.discovery.start()
    try:
        for _ in range(4):
            await env.discovery.snapshot()
        await asyncio.sleep(0.02)
        env.discovery.client.recommendations.assert_not_called()
    finally:
        await env.discovery.stop()


async def test_new_collection_tables_can_be_added_to_existing_database(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from backend.app.db.base import Base
    from backend.app.db.engine import _ensure_columns

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE settings (key VARCHAR(64) PRIMARY KEY, value TEXT NOT NULL, updated_at DATETIME)"
            )
        )
        conn.execute(
            text("INSERT INTO settings(key, value) VALUES ('download_layout', 'existing-layout')")
        )
        Base.metadata.create_all(conn)
        _ensure_columns(conn)
        Base.metadata.create_all(conn)
        _ensure_columns(conn)
        assert {
            "catalog_tracks",
            "catalog_state",
            "family_tracks",
            "family_artists",
            "discovery_cache",
        } <= set(inspect(conn).get_table_names())
        assert conn.execute(text("SELECT value FROM settings")).scalar_one() == "existing-layout"
    engine.dispose()


async def test_mp3_recording_identity_survives_tagging(tmp_path):
    import shutil
    import subprocess

    from backend.app.downloads.tagging import tag_audio

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required")
    path = tmp_path / "identity.mp3"
    recording, artist = str(uuid4()), str(uuid4())
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=0.1", str(path)],
        check=True,
        capture_output=True,
    )
    await tag_audio(
        str(path),
        TrackRef("ytdlp", "Song", "Artist", ext_ids={"mbid": recording, "artist_mbid": artist}),
    )
    metadata = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "ffmetadata", "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.lower()
    assert f"musicbrainz_trackid={recording}" in metadata
    assert f"musicbrainz_artistid={artist}" in metadata


async def test_same_metadata_does_not_claim_a_different_recording(env, tmp_path):
    from backend.app.db.models import LibraryItem

    wrong, wanted = str(uuid4()), str(uuid4())
    path = tmp_path / "wrong.mp3"
    path.write_bytes(b"other recording")
    async with env.db() as session:
        session.add(
            LibraryItem(
                title="Song",
                artist="Artist",
                album="Album",
                mbid=wrong,
                file_path=str(path),
                fmt="mp3",
                quality_tier=1,
                source_provider="ytdlp",
            )
        )
        await session.commit()
    card = (
        await env.family.cards(
            [
                CollectionTrack(
                    title="Song", artist="Artist", album="Album", ext_ids={"mbid": wanted}
                )
            ]
        )
    )[0]
    assert card["local_item_id"] is None and card["availability"] != "available"


async def test_selecting_a_file_preserves_its_exact_playback_target(env):
    recording = str(uuid4())
    env.nav.songs = [
        {
            "id": str(i),
            "title": "Song",
            "artist": "Artist",
            "album": f"Edition {i}",
            "musicBrainzId": recording,
        }
        for i in range(2)
    ]
    await env.catalog.sync()
    cards = (await env.api.get("/api/catalog/tracks")).json()["items"]
    assert len(cards) == 2
    assert cards[0]["id"] == cards[1]["id"]  # preferences belong to the recording
    assert cards[0]["catalog_id"] != cards[1]["catalog_id"]  # audio belongs to the chosen file
    assert all(c["catalog_id"] == c["track"]["catalog_id"] for c in cards)
