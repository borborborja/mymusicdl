"""Regression tests for playing saved files and durable Navidrome delivery."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, inspect

from backend.app.api import routes_media
from backend.app.config import Settings
from backend.app.db.base import utcnow
from backend.app.db.engine import _ensure_columns, get_session
from backend.app.db.models import Job, LibraryItem
from backend.app.deps import settings_dep
from backend.app.downloads.tagging import tag_audio
from backend.app.library.sync import LibrarySync
from backend.app.main import create_app
from backend.app.providers.base import TrackRef


def write_audio(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000)
    return path


@pytest_asyncio.fixture
async def playback_client(session_factory, tmp_path):
    settings = Settings(
        _env_file=None,
        music_library_path=str(tmp_path),
        app_secret="media-test-secret",
        app_shared_password="media-password",
    )
    path = write_audio(tmp_path / "Artist" / "Album" / "Song.wav")
    async with session_factory() as session:
        for job_id in ("one", "two"):
            session.add(Job(id=job_id, kind="download", status="done", result_path=str(path)))
        session.add(
            LibraryItem(
                id=1,
                artist="Artist",
                title="Song",
                album="Album",
                file_path=str(path),
                fmt="wav",
                quality_tier=1,
                source_provider="ytdlp",
            )
        )
        await session.commit()
    app = create_app()

    async def db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = db
    app.dependency_overrides[settings_dep] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-App-Password": "media-password"},
    ) as client:
        yield client, path


async def test_saved_audio_streams_exact_bytes_and_ranges(playback_client):
    client, path = playback_client
    response = await client.post("/api/jobs/one/playback")
    assert response.status_code == 200
    url = response.json()["url"]
    full = await client.get(url)
    assert full.status_code == 200
    assert full.content == path.read_bytes()
    assert full.headers["content-type"] == "audio/wav"
    assert full.headers["cache-control"] == "private, no-store"
    partial = await client.get(url, headers={"Range": "bytes=0-43"})
    assert partial.status_code == 206
    assert partial.content == path.read_bytes()[:44]
    assert partial.headers["content-range"] == f"bytes 0-43/{path.stat().st_size}"
    assert (await client.head(url)).headers["content-length"] == str(path.stat().st_size)
    assert (await client.get(url, headers={"Range": "bytes=999999-"})).status_code == 416


async def test_media_tickets_need_auth_are_scoped_and_expire(playback_client, monkeypatch):
    client, _ = playback_client
    assert (
        await client.post("/api/jobs/one/playback", headers={"X-App-Password": ""})
    ).status_code == 401
    assert (await client.get("/api/media/jobs/one")).status_code == 401
    url = (await client.post("/api/jobs/one/playback")).json()["url"]
    assert (await client.get(url.replace("jobs/one", "jobs/two"))).status_code == 401
    now = routes_media.time.time()
    monkeypatch.setattr(routes_media.time, "time", lambda: now + 3601)
    assert (await client.get(url)).status_code == 401


async def test_library_playback_survives_job_history_deletion(playback_client, session_factory):
    client, path = playback_client
    async with session_factory() as session:
        await session.delete(await session.get(Job, "one"))
        await session.commit()
    url = (await client.post("/api/library/items/1/playback")).json()["url"]
    assert (await client.get(url)).content == path.read_bytes()


async def test_media_cannot_read_missing_or_escaped_files(
    playback_client, session_factory, tmp_path
):
    client, path = playback_client
    url = (await client.post("/api/jobs/one/playback")).json()["url"]
    path.unlink()
    assert (await client.get(url)).status_code == 404
    outside = tmp_path.parent / f"{tmp_path.name}-outside.wav"
    outside.write_bytes(b"private")
    try:
        path.symlink_to(outside)
        assert (await client.post("/api/jobs/one/playback")).status_code == 404
        assert (await client.get(url)).status_code == 404
    finally:
        outside.unlink()


async def test_media_rejects_running_download(playback_client, session_factory):
    client, _ = playback_client
    async with session_factory() as session:
        job = await session.get(Job, "one")
        job.status = "running"
        await session.commit()
    assert (await client.post("/api/jobs/one/playback")).status_code == 409


def test_old_database_gets_all_sync_columns():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE jobs (id VARCHAR PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO jobs VALUES ('old-job')")
        _ensure_columns(conn)
        _ensure_columns(conn)
        columns = {col["name"] for col in inspect(conn).get_columns("jobs")}
        assert {
            "library_status",
            "library_error",
            "library_attempts",
            "library_prepared",
            "library_next_retry_at",
        } <= columns
        assert conn.exec_driver_sql(
            "SELECT library_attempts, library_prepared FROM jobs"
        ).one() == (0, 0)
    engine.dispose()


@pytest_asyncio.fixture
async def sync_env(session_factory, tmp_path):
    path = write_audio(tmp_path / "Artist" / "Album" / "Song.wav")
    settings = Settings(
        _env_file=None,
        music_library_path=str(tmp_path),
        navidrome_scan_timeout_s=0.05,
        navidrome_sync_retry_s=1,
        navidrome_sync_max_attempts=3,
    )
    nav = SimpleNamespace(
        get_scan_status=AsyncMock(return_value={"scanning": False}),
        start_scan=AsyncMock(return_value={"scanning": True}),
        search3=AsyncMock(return_value={"song": []}),
    )
    broker = SimpleNamespace(publish=AsyncMock())
    invalidate = Mock()
    sync = LibrarySync(
        settings=settings,
        session_factory=session_factory,
        navidrome=nav,
        broker=broker,
        invalidate=invalidate,
    )
    async with session_factory() as session:
        session.add(
            Job(
                id="download",
                kind="download",
                status="done",
                result_path=str(path),
                provider="ytdlp",
                track_json=json.dumps(TrackRef("ytdlp", "Song", "Artist", "Album").to_dict()),
                library_status="pending",
                library_prepared=True,
            )
        )
        session.add(
            LibraryItem(
                id=1,
                title="Song",
                artist="Artist",
                album="Album",
                file_path=str(path),
                fmt="wav",
                quality_tier=1,
                source_provider="ytdlp",
            )
        )
        await session.commit()
    return sync, nav, path, invalidate


async def load_job(factory):
    async with factory() as session:
        return await session.get(Job, "download")


async def due(factory):
    async with factory() as session:
        job = await session.get(Job, "download")
        job.library_next_retry_at = utcnow() - timedelta(seconds=1)
        await session.commit()


async def test_exact_file_confirmed_and_cache_invalidated(sync_env, session_factory):
    sync, nav, _, invalidate = sync_env
    nav.search3.return_value = {"song": [{"id": "actual", "path": "Artist/Album/Song.wav"}]}
    await sync.run_once()
    job = await load_job(session_factory)
    assert job.library_confirmed is True
    assert job.library_status == "confirmed"
    assert job.library_attempts == 1
    assert job.library_error is None
    invalidate.assert_called_once()
    async with session_factory() as session:
        assert (await session.get(LibraryItem, 1)).navidrome_id == "actual"
    nav.start_scan.assert_awaited_once_with(full=False)


async def test_other_copy_does_not_confirm_download(sync_env, session_factory):
    sync, nav, _, _ = sync_env
    nav.search3.return_value = {
        "song": [
            {
                "id": "older-copy",
                "path": "Other/Album/Song.mp3",
                "title": "Song",
                "artist": "Artist",
            }
        ]
    }
    await sync.run_once()
    job = await load_job(session_factory)
    assert job.library_confirmed is False
    assert job.library_status == "pending"
    assert job.library_next_retry_at is not None
    assert "volumen" in job.library_error


async def test_delayed_remote_volume_retries_full_scan(sync_env, session_factory):
    sync, nav, _, _ = sync_env
    await sync.run_once()
    await sync.run_once()  # persisted delay must be respected
    assert nav.start_scan.await_count == 1
    await due(session_factory)
    nav.search3.return_value = {"song": [{"id": "new", "path": "Artist/Album/Song.wav"}]}
    await sync.run_once()
    assert (await load_job(session_factory)).library_status == "confirmed"
    nav.start_scan.assert_awaited_with(full=True)


async def test_scan_error_is_visible_redacted_and_retryable(sync_env, session_factory):
    sync, nav, _, _ = sync_env
    nav.start_scan.side_effect = RuntimeError("https://secret-server/rest/startScan?t=PRIVATE")
    await sync.run_once()
    job = await load_job(session_factory)
    assert job.status == "done"
    assert job.library_status == "pending"
    assert "PRIVATE" not in job.library_error
    assert "escaneo" in job.library_error
    nav.search3.assert_not_awaited()


async def test_scan_timeout_never_confirms_mid_scan(sync_env, session_factory):
    sync, nav, _, _ = sync_env
    nav.get_scan_status.return_value = {"scanning": True}
    await sync.run_once()
    assert (await load_job(session_factory)).library_status == "pending"
    nav.start_scan.assert_not_awaited()
    nav.search3.assert_not_awaited()


async def test_new_scan_happens_after_existing_scan(sync_env, session_factory):
    sync, nav, _, _ = sync_env
    nav.get_scan_status.side_effect = [
        {"scanning": True},
        {"scanning": False},
        {"scanning": True},
        {"scanning": False},
    ]
    nav.search3.return_value = {"song": [{"id": "new", "path": "Artist/Album/Song.wav"}]}
    await sync.run_once()
    assert (await load_job(session_factory)).library_status == "confirmed"
    assert nav.get_scan_status.await_count == 4


async def test_restart_recovers_interrupted_sync(sync_env, session_factory):
    sync, nav, _, _ = sync_env
    async with session_factory() as session:
        job = await session.get(Job, "download")
        job.library_status, job.library_attempts = "syncing", 1
        await session.commit()
    restarted = LibrarySync(
        settings=sync.settings, session_factory=session_factory, navidrome=nav, broker=sync.broker
    )
    nav.search3.return_value = {"song": [{"id": "new", "path": "Artist/Album/Song.wav"}]}
    await restarted.run_once()
    assert (await load_job(session_factory)).library_status == "confirmed"
    nav.start_scan.assert_awaited_with(full=True)


async def test_exhausted_sync_stops_and_can_be_manually_retried(sync_env, session_factory):
    sync, nav, _, _ = sync_env
    for _ in range(3):
        await due(session_factory)
        await sync.run_once()
    assert (await load_job(session_factory)).library_status == "error"
    await sync.run_once()
    assert nav.start_scan.await_count == 3
    await sync.retry("download")
    job = await load_job(session_factory)
    assert job.library_status == "pending"
    assert job.library_attempts == 0
    assert job.library_next_retry_at is None


async def test_missing_file_fails_before_scanning(sync_env, session_factory):
    sync, nav, path, _ = sync_env
    path.unlink()
    await sync.run_once()
    job = await load_job(session_factory)
    assert job.library_status == "error"
    assert "archivo" in job.library_error
    nav.start_scan.assert_not_awaited()


async def test_unconfigured_navidrome_does_not_spin_forever(sync_env, session_factory):
    sync, _, _, _ = sync_env
    sync.navidrome = None
    await sync.run_once()
    job = await load_job(session_factory)
    assert job.library_status == "unconfigured"
    with pytest.raises(ValueError, match="configurado"):
        await sync.retry("download")
    count = sync.broker.publish.await_count
    await sync.run_once()
    assert sync.broker.publish.await_count == count


async def test_multiple_downloads_share_one_scan(sync_env, session_factory):
    sync, nav, path, _ = sync_env
    async with session_factory() as session:
        session.add(
            Job(
                id="second",
                kind="download",
                status="done",
                result_path=str(path),
                library_prepared=True,
                track_json=json.dumps(TrackRef("ytdlp", "Song", "Artist", "Album").to_dict()),
            )
        )
        await session.commit()
    await sync.run_once()
    nav.start_scan.assert_awaited_once()


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is required for the real audio integration test"
)
async def test_tagging_preserves_audio_and_permissions(tmp_path):
    path = write_audio(tmp_path / "Song.wav")
    path.chmod(0o644)
    with wave.open(str(path), "rb") as audio:
        original_pcm = audio.readframes(audio.getnframes())
    await tag_audio(
        str(path),
        TrackRef(
            "ytdlp",
            "Títol correcte",
            "Artista correcte",
            "Àlbum correcte",
            album_artist="Various Artists",
        ),
    )
    with wave.open(str(path), "rb") as audio:
        assert audio.readframes(audio.getnframes()) == original_pcm
    metadata = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "ffmetadata", "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "title=Títol correcte" in metadata
    assert "artist=Artista correcte" in metadata
    assert "album=Àlbum correcte" in metadata
    assert path.stat().st_mode & 0o777 == 0o644
    assert not list(tmp_path.glob(".mymusicdl-tags-*"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
async def test_bad_audio_preserves_original_on_tagging_error(tmp_path):
    path = tmp_path / "bad.mp3"
    path.write_bytes(b"not valid audio")
    with pytest.raises(RuntimeError, match="etiquetas"):
        await tag_audio(str(path), TrackRef("ytdlp", "Song", "Artist"))
    assert path.read_bytes() == b"not valid audio"
    assert not list(tmp_path.glob(".mymusicdl-tags-*"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
@pytest.mark.parametrize("suffix", ["mp3", "flac", "m4a", "opus"])
async def test_tagging_replaces_source_metadata_for_supported_formats(tmp_path, suffix):
    path = tmp_path / f"Song.{suffix}"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.1",
            "-metadata",
            "title=Wrong title",
            "-metadata",
            "artist=Wrong uploader",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    await tag_audio(
        str(path),
        TrackRef(
            "ytdlp",
            "Selected Song",
            "Selected Artist",
            "Selected Album",
            album_artist="Compilation Artist",
        ),
    )
    metadata = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path)]
        + (["-map_metadata", "0:s:a:0"] if suffix == "opus" else [])
        + ["-f", "ffmetadata", "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.lower()
    assert "title=selected song" in metadata
    assert "artist=selected artist" in metadata
    assert "album=selected album" in metadata
    assert "album_artist=compilation artist" in metadata
    assert "wrong" not in metadata


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
async def test_legacy_download_is_retagged_before_scan(sync_env, session_factory):
    sync, nav, path, _ = sync_env
    async with session_factory() as session:
        job = await session.get(Job, "download")
        job.library_prepared = False
        job.library_status = None
        await session.commit()

    async def scan(**kwargs):
        metadata = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "ffmetadata", "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert "title=Song" in metadata
        return {"scanning": False}

    nav.start_scan.side_effect = scan
    nav.search3.return_value = {"song": [{"id": "new", "path": "Artist/Album/Song.wav"}]}
    await sync.run_once()
    job = await load_job(session_factory)
    assert job.library_prepared is True
    assert job.library_confirmed is True
