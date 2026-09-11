"""Regression coverage for filesystem boundaries, job lifecycle and provider commands."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.app import main
from backend.app.config import Settings
from backend.app.db.models import Job, LibraryItem
from backend.app.deps import settings_dep
from backend.app.downloads import preview
from backend.app.downloads import worker as worker_module
from backend.app.downloads.paths import build_dest, validate_layout
from backend.app.downloads.progress import ProgressBroker
from backend.app.downloads.queue import DownloadQueue
from backend.app.downloads.runner import SubprocessError, stream_subprocess
from backend.app.downloads.service import EnqueueItem, enqueue_tracks
from backend.app.downloads.worker import WorkerPool
from backend.app.providers.base import ProgressEvent, Quality, TrackRef
from backend.app.providers.spotdl_provider import SpotdlProvider
from backend.app.security import is_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/youtube.com",
        "https://youtube.com.evil.example/a",
        "https://youtube.com@127.0.0.1/a",
        "file:///tmp/youtu.be",
        "--config-locations=youtube.com",
        "https://youtube.com:bad/a",
    ],
)
def test_untrusted_youtube_urls_are_not_followed(url):
    assert not is_youtube_url(url)
    assert preview._target("Artist", "Song", url) == "ytsearch1:Artist Song"


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/abc",
        "https://www.youtube.com/watch?v=abc",
        "https://music.youtube.com/watch?v=abc",
    ],
)
def test_youtube_urls_are_accepted(url):
    assert is_youtube_url(url)


async def test_spa_does_not_serve_outside_static(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("SPA")
    (tmp_path / "private.txt").write_text("private content")
    (static / "linked.txt").symlink_to(tmp_path / "private.txt")
    (static / "robots.txt").write_text("public")
    monkeypatch.setattr(main, "STATIC_DIR", static)
    async with AsyncClient(
        transport=ASGITransport(app=main.create_app()), base_url="http://test"
    ) as client:
        for path in ("/%2e%2e/private.txt", "/%2F" + str(tmp_path / "private.txt"), "/linked.txt"):
            response = await client.get(path)
            assert response.status_code == 404
            assert "private content" not in response.text
        assert (await client.get("/robots.txt")).text == "public"
        assert (await client.get("/albums/example")).text == "SPA"
        assert (await client.get("/api/missing")).status_code == 404


def test_download_rejects_symlink_escape(tmp_path):
    music, outside = tmp_path / "music", tmp_path / "outside"
    music.mkdir()
    outside.mkdir()
    (music / "Artist").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        build_dest(str(music), "{artist}/{title}", artist="Artist", album=None, title="Song")


@pytest.mark.parametrize("layout", ["{title}/audio", "{artist}/{title}/"])
def test_title_must_identify_the_file(layout):
    with pytest.raises(ValueError):
        validate_layout(layout)


async def make_worker(session_factory, tmp_path, monkeypatch, download):
    settings = Settings(_env_file=None, music_library_path=str(tmp_path), download_max_retries=2)
    provider = SimpleNamespace(
        id="ytdlp", enabled=True, default_quality=Quality.MP3_320, download=download
    )
    pool = WorkerPool(
        settings=settings,
        queue=DownloadQueue(),
        broker=ProgressBroker(),
        registry=SimpleNamespace(get=lambda _: provider),
        navidrome=None,
        session_factory=session_factory,
    )
    monkeypatch.setattr(worker_module, "ffprobe_audio", AsyncMock(return_value=None))
    monkeypatch.setattr(worker_module, "tag_audio", AsyncMock())
    return pool


async def add_job(session_factory, title="Song", **kwargs):
    job_id = str(uuid4())
    async with session_factory() as session:
        session.add(
            Job(
                id=job_id,
                kind="download",
                provider="ytdlp",
                status="queued",
                track_json=json.dumps(TrackRef("ytdlp", title, "Artist", "Album").to_dict()),
                requested_quality=1,
                **kwargs,
            )
        )
        await session.commit()
    return job_id


async def read_job(session_factory, job_id):
    async with session_factory() as session:
        return await session.get(Job, job_id)


async def test_zero_exit_without_audio_is_error(session_factory, tmp_path, monkeypatch):
    async def download(track, **kwargs):
        yield ProgressEvent(kwargs["job_id"], "done", 100)

    pool = await make_worker(session_factory, tmp_path, monkeypatch, download)
    job_id = await add_job(session_factory)
    await pool._process(job_id)
    job = await read_job(session_factory, job_id)
    assert job.status == "error"
    assert not job.result_path
    async with session_factory() as session:
        assert not (await session.scalars(select(LibraryItem))).all()


async def test_concurrent_album_tracks_keep_their_own_files(session_factory, tmp_path, monkeypatch):
    async def download(track, **kwargs):
        path = Path(kwargs["dest_dir"]) / f"{kwargs['filename']}.mp3"
        path.write_bytes(track.title.encode() * 30)
        await asyncio.sleep(0.01)
        yield ProgressEvent(kwargs["job_id"], "done", 100)

    pool = await make_worker(session_factory, tmp_path, monkeypatch, download)
    ids = [await add_job(session_factory, title=title) for title in ("Short", "Much Longer Song")]
    await asyncio.gather(*(pool._process(job_id) for job_id in ids))
    paths = []
    for job_id in ids:
        job = await read_job(session_factory, job_id)
        assert job.status == "done"
        title = json.loads(job.track_json)["title"]
        assert Path(job.result_path).read_bytes() == title.encode() * 30
        paths.append(job.result_path)
    assert len(set(paths)) == 2


async def test_existing_named_audio_can_be_recorded_on_retry(
    session_factory, tmp_path, monkeypatch
):
    async def download(track, **kwargs):
        yield ProgressEvent(kwargs["job_id"], "done", 100)

    pool = await make_worker(session_factory, tmp_path, monkeypatch, download)
    dest = tmp_path / "Artist" / "Album"
    dest.mkdir(parents=True)
    expected = dest / "Song.mp3"
    expected.write_bytes(b"existing audio")
    (dest / "Other.mp3").write_bytes(b"other" * 100)
    job_id = await add_job(session_factory)
    await pool._process(job_id)
    job = await read_job(session_factory, job_id)
    assert job.status == "done"
    assert job.result_path == str(expected)


@pytest.mark.parametrize("user_cancel", [False, True])
async def test_cancel_during_retry_backoff(session_factory, tmp_path, monkeypatch, user_cancel):
    async def download(track, **kwargs):
        raise SubprocessError(1, "HTTP Error 429")
        yield  # async generator

    pool = await make_worker(session_factory, tmp_path, monkeypatch, download)
    job_id = await add_job(session_factory)
    events = pool.broker.subscribe()
    task = asyncio.create_task(pool._process(job_id))
    try:
        while True:
            event = await asyncio.wait_for(events.get(), timeout=2)
            if (event.get("job", {}).get("stage") or "").startswith("retrying"):
                break
        if user_cancel:
            assert pool.cancel(job_id)
            await asyncio.wait_for(task, timeout=2)
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        job = await read_job(session_factory, job_id)
        assert job.status == ("canceled" if user_cancel else "queued")
        assert not pool._active
        assert not pool._cancelled
        if not user_cancel:
            assert await asyncio.wait_for(pool.queue.get(), timeout=1) == job_id
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pool.broker.unsubscribe(events)


async def test_invalid_destination_does_not_strand_job(session_factory, tmp_path, monkeypatch):
    async def download(track, **kwargs):
        pytest.fail("provider should not run")
        yield

    pool = await make_worker(session_factory, tmp_path, monkeypatch, download)
    (tmp_path / "Artist").write_text("not a directory")
    job_id = await add_job(session_factory)
    await pool._process(job_id)
    assert (await read_job(session_factory, job_id)).status == "error"


async def test_enqueue_is_atomic_for_simultaneous_requests(session_factory, registry, settings):
    queue = DownloadQueue()
    item = EnqueueItem("spotdl", 1, {"title": "Song", "artist": "Artist"})

    async def submit():
        async with session_factory() as session:
            return await enqueue_tracks(session, queue, registry, settings, [item])

    results = await asyncio.gather(submit(), submit())
    assert sum(len(result.queued) for result in results) == 1
    assert queue.qsize() == 1


async def test_enqueue_preserves_quality_upgrades(session_factory, registry, settings):
    queue = DownloadQueue()
    async with session_factory() as session:
        result = await enqueue_tracks(
            session,
            queue,
            registry,
            settings,
            [
                EnqueueItem("tidal", quality, {"title": "Song", "artist": "Artist"})
                for quality in (1, 2)
            ],
        )
    assert len(result.queued) == 2


async def test_preview_requires_configured_password(monkeypatch):
    app = main.create_app()
    app.dependency_overrides[settings_dep] = lambda: Settings(
        _env_file=None, app_shared_password="test-password"
    )
    resolve = AsyncMock(return_value="https://example.com/audio")
    monkeypatch.setattr("backend.app.api.routes_preview.resolve_stream_url", resolve)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/preview?artist=A&title=B")).status_code == 401
        resolve.assert_not_called()
        assert (
            await client.get(
                "/api/preview?artist=A&title=B", headers={"X-App-Password": "test-password"}
            )
        ).status_code == 200


async def test_runner_never_logs_command_secrets(caplog):
    caplog.set_level(logging.INFO)
    cmd = [sys.executable, "-c", "print('ok')", "--client-secret", "dummy-sensitive-value"]
    async for _ in stream_subprocess(
        cmd, job_id="test", parse=lambda _: None, settings=Settings(_env_file=None)
    ):
        pass
    assert "dummy-sensitive-value" not in caplog.text


async def test_runner_cancellation_reaps_subprocess(tmp_path):
    started = asyncio.Event()
    pid_file = tmp_path / "pid"

    def parse(line):
        started.set()
        return None

    async def run():
        async for _ in stream_subprocess(
            [
                sys.executable,
                "-u",
                "-c",
                "import os,time,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); print('ready'); time.sleep(60)",
                str(pid_file),
            ],
            job_id="cancel",
            parse=parse,
            settings=Settings(_env_file=None),
        ):
            pass

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        pid = int(pid_file.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_preview_timeout_reaps_child(monkeypatch):
    proc = SimpleNamespace(communicate=AsyncMock(side_effect=TimeoutError), returncode=None)
    monkeypatch.setattr(preview.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    terminate = AsyncMock()
    monkeypatch.setattr(preview, "terminate_process", terminate)
    assert (
        await preview.resolve_stream_url(Settings(_env_file=None), artist="Timeout", title="Unique")
        is None
    )
    terminate.assert_awaited_once_with(proc)


@pytest.mark.parametrize(
    "url",
    [
        "https://open.spotify.com/album/abc",
        "https://open.spotify.com/playlist/abc",
        "http://localhost/internal",
    ],
)
async def test_spotdl_only_follows_single_track_urls(monkeypatch, url):
    captured = []

    async def stream(cmd, **kwargs):
        captured.extend(cmd)
        yield ProgressEvent("job", "done")

    monkeypatch.setattr("backend.app.providers.spotdl_provider.stream_subprocess", stream)
    provider = SpotdlProvider(Settings(_env_file=None))
    async for _ in provider.download(
        TrackRef("spotdl", "Song", "Artist", source_url=url),
        quality=Quality.MP3_320,
        dest_dir="/music",
        job_id="job",
    ):
        pass
    assert captured[2] == "Artist - Song"


async def test_free_provider_cannot_claim_lossless(session_factory, settings):
    from backend.app.downloads.service import EnqueueError

    provider = SpotdlProvider(settings)
    registry = SimpleNamespace(get=lambda _: provider)
    queue = DownloadQueue()
    async with session_factory() as session:
        with pytest.raises(EnqueueError, match="does not support"):
            await enqueue_tracks(
                session,
                queue,
                registry,
                settings,
                [EnqueueItem("spotdl", 2, {"title": "Song", "artist": "Artist"})],
            )
    assert queue.qsize() == 0


async def test_spotify_album_fetches_all_pages():
    from backend.app.metadata.spotify import SpotifyMetadata

    metadata = SpotifyMetadata(Settings(_env_file=None))
    metadata._get = AsyncMock(
        side_effect=[
            {
                "id": "album",
                "name": "Album",
                "tracks": {"items": [{"id": "one", "name": "One"}], "next": "next-page"},
            },
            {"items": [{"id": "two", "name": "Two"}], "next": None},
        ]
    )
    try:
        _, tracks = await metadata.get_album_tracks("album")
        assert [track.title for track in tracks] == ["One", "Two"]
        metadata._get.assert_awaited_with("/albums/album/tracks", {"offset": 1, "limit": 50})
    finally:
        await metadata.aclose()


async def test_updater_deduplicates_and_serializes_installations(session_factory, monkeypatch):
    from backend.app.updater.service import Updater

    updater = Updater(
        settings=Settings(_env_file=None), session_factory=session_factory, broker=ProgressBroker()
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    active = 0
    max_active = 0

    async def install(job_id, name):
        nonlocal active, max_active
        active += 1
        max_active = max(active, max_active)
        entered.set()
        try:
            await release.wait()
        finally:
            active -= 1

    monkeypatch.setattr(updater, "_install_update", install)
    first, duplicate = await asyncio.gather(
        updater.start_update("yt-dlp"), updater.start_update("yt-dlp")
    )
    assert first == duplicate
    second = await updater.start_update("spotdl")
    await asyncio.wait_for(entered.wait(), timeout=2)
    await updater.stop()
    assert max_active == 1
    assert not updater._updates
    assert not updater._update_names
    for job_id in (first, second):
        assert (await read_job(session_factory, job_id)).status == "canceled"


async def test_restart_marks_interrupted_tool_updates_failed(session_factory):
    async with session_factory() as session:
        session.add(Job(id="update", kind="tool_update", status="running", provider="spotdl"))
        await session.commit()
        queue = DownloadQueue()
        await queue.rehydrate(session)
        await session.refresh(await session.get(Job, "update"))
    assert (await read_job(session_factory, "update")).status == "error"
    assert queue.qsize() == 0


async def test_library_match_prefers_best_existing_quality():
    from backend.app.navidrome.matcher import library_quality

    nav = SimpleNamespace(
        search3=AsyncMock(
            return_value={
                "song": [
                    {
                        "id": "mp3",
                        "title": "Song",
                        "artist": "Artist",
                        "suffix": "mp3",
                        "bitRate": 320,
                    },
                    {
                        "id": "flac",
                        "title": "Song",
                        "artist": "Artist",
                        "suffix": "flac",
                        "bitRate": 900,
                    },
                ]
            }
        )
    )
    match = await library_quality(nav, artist="Artist", title="Song")
    assert match["navidrome_id"] == "flac"


async def test_telegram_http_errors_do_not_expose_token():
    import httpx

    from backend.app.bots.telegram import TelegramBot

    bot = TelegramBot(
        SimpleNamespace(), token="dummy-private-token", allowed_users=set(), source=None
    )
    bot._http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(401, request=req))
    )
    try:
        with pytest.raises(RuntimeError) as exc:
            await bot._call("getMe")
        assert "dummy-private-token" not in str(exc.value)
        assert "401" in str(exc.value)
    finally:
        await bot._http.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/playlist?list=abc",
        "https://www.youtube.com/@artist",
        "https://youtube.com/channel/abc",
    ],
)
def test_youtube_playlists_are_not_downloaded_as_tracks(url):
    from backend.app.security import youtube_track_url

    assert youtube_track_url(url) is None
    assert preview._target("Artist", "Song", url) == "ytsearch1:Artist Song"


def test_youtube_video_discards_playlist_parameters():
    from backend.app.security import youtube_track_url

    assert (
        youtube_track_url("https://www.youtube.com/watch?v=abc&list=playlist")
        == "https://www.youtube.com/watch?v=abc"
    )


async def test_download_flow_runs_cli_records_audio_and_rescans(
    session_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(worker_module, "tag_audio", AsyncMock())
    from backend.app.providers.ytdlp_provider import YtdlpProvider

    tools = tmp_path / "tools" / "bin"
    tools.mkdir(parents=True)
    executable = tools / "yt-dlp"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys,wave\n"
        "target=sys.argv[sys.argv.index('-o')+1].replace('%(ext)s','wav')\n"
        "with wave.open(target,'wb') as audio:\n"
        " audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(b'\\0\\0'*8000)\n"
        "print('DLP|100%|8KiB/s|00:00',flush=True)\n"
    )
    executable.chmod(0o755)
    settings = Settings(
        _env_file=None,
        tools_venv=str(tmp_path / "tools"),
        music_library_path=str(tmp_path / "music"),
        default_format="wav",
    )
    provider = YtdlpProvider(settings)
    registry = SimpleNamespace(get=lambda _: provider)
    queue = DownloadQueue()
    nav = SimpleNamespace(
        start_scan=AsyncMock(),
        get_scan_status=AsyncMock(return_value={"scanning": False}),
        search3=AsyncMock(return_value={"song": []}),
    )
    pool = WorkerPool(
        settings=settings,
        queue=queue,
        broker=ProgressBroker(),
        registry=registry,
        navidrome=nav,
        session_factory=session_factory,
    )
    async with session_factory() as session:
        result = await enqueue_tracks(
            session,
            queue,
            registry,
            settings,
            [EnqueueItem("ytdlp", 1, {"title": "Song", "artist": "Artist", "album": "Album"})],
        )
    job_id = await queue.get()
    assert job_id == result.queued[0].id
    await pool._process(job_id)
    job = await read_job(session_factory, job_id)
    assert job.status == "done"
    assert Path(job.result_path).read_bytes().startswith(b"RIFF")
    assert Path(job.result_path).is_relative_to(tmp_path / "music")
    async with session_factory() as session:
        stored = (await session.scalars(select(LibraryItem))).one()
        assert stored.file_path == job.result_path
        assert stored.title == "Song"
    await pool.library_sync.run_once()
    nav.start_scan.assert_awaited_once()
    await pool.stop()
