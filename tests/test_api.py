"""API-route tests via httpx ASGITransport with dependency overrides (no network, no lifespan)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.app.db.engine import get_session
from backend.app.deps import get_aggregator, get_queue, get_registry
from backend.app.main import create_app
from backend.app.schemas.search import SearchResponseDTO, TrackResultDTO


class _FakeAggregator:
    def __init__(self):
        self.last_kwargs = None

    async def search(self, **kwargs):
        self.last_kwargs = kwargs
        if not (kwargs.get("query") or kwargs.get("artist") or kwargs.get("album")):
            raise ValueError("Empty search")
        return SearchResponseDTO(
            kind=kwargs["kind"],
            tracks=[TrackResultDTO(title="Creep", artist="Radiohead")],
        )


@pytest_asyncio.fixture
async def client(session_factory, queue, registry):
    app = create_app()
    agg = _FakeAggregator()

    async def _get_session_override():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_aggregator] = lambda: agg
    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_queue] = lambda: queue
    app.dependency_overrides[get_registry] = lambda: registry
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._agg = agg  # expose for assertions
        yield c


async def test_search_threads_fielded_params(client):
    resp = await client.get(
        "/api/search", params={"q": "creep", "artist": "radiohead", "kind": "song"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "song" and body["tracks"][0]["title"] == "Creep"
    assert client._agg.last_kwargs["artist"] == "radiohead"
    assert client._agg.last_kwargs["query"] == "creep"


async def test_search_empty_is_400(client):
    resp = await client.get("/api/search", params={"kind": "song"})
    assert resp.status_code == 400


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (httpx.ReadTimeout(""), 504, "tardó demasiado"),
        (httpx.ConnectError("private upstream details"), 502, "No se pudo consultar"),
    ],
)
async def test_search_upstream_failure_is_actionable(client, error, status, message):
    client._agg.search = AsyncMock(side_effect=error)
    response = await client.get("/api/search", params={"q": "Song"})
    assert response.status_code == status
    assert message in response.json()["detail"]
    assert "Vuelve a intentarlo" in response.json()["detail"]
    assert "private upstream details" not in response.text


async def test_downloads_enqueue_and_dedup(client, queue):
    payload = {
        "items": [
            {
                "provider": "spotdl",
                "quality": 1,
                "track": {
                    "title": "Creep",
                    "artist": "Radiohead",
                    "album": "Pablo Honey",
                    "isrc": "GB1",
                },
            }
        ]
    }
    r1 = await client.post("/api/downloads", json=payload)
    assert r1.status_code == 200 and len(r1.json()) == 1
    # Same track still queued → deduped → 0 new jobs returned.
    r2 = await client.post("/api/downloads", json=payload)
    assert r2.status_code == 200 and len(r2.json()) == 0
    assert len(queue.puts) == 1


async def test_downloads_unknown_provider_400(client, registry):
    # Make the registry report the provider as missing.
    registry.get = lambda name: None
    resp = await client.post(
        "/api/downloads",
        json={
            "items": [{"provider": "nope", "quality": 1, "track": {"title": "X", "artist": "Y"}}]
        },
    )
    assert resp.status_code == 400


async def test_downloads_invalid_quality_rejected(client, queue):
    response = await client.post(
        "/api/downloads",
        json={
            "items": [
                {"provider": "spotdl", "quality": 5, "track": {"title": "Song", "artist": "Artist"}}
            ]
        },
    )
    assert response.status_code == 422
    assert not queue.puts


async def test_negative_list_limits_rejected(client):
    for path in ("/api/jobs", "/api/library/items", "/api/search"):
        assert (await client.get(path, params={"limit": -1})).status_code == 422


async def test_tool_update_cannot_be_retried_as_download(client, session_factory, queue):
    from backend.app.db.models import Job

    async with session_factory() as session:
        session.add(Job(id="tool-job", kind="tool_update", provider="yt-dlp", status="error"))
        await session.commit()
    response = await client.post("/api/jobs/tool-job/retry")
    assert response.status_code == 400
    assert not queue.puts


async def test_retry_clears_old_result_and_confirmation(client, session_factory, queue):
    from backend.app.db.models import Job

    async with session_factory() as session:
        session.add(
            Job(
                id="retry-job",
                kind="download",
                provider="ytdlp",
                status="error",
                result_path="/music/old.mp3",
                library_confirmed=True,
            )
        )
        await session.commit()
    response = await client.post("/api/jobs/retry-job/retry")
    assert response.status_code == 200
    assert response.json()["result_path"] is None
    assert response.json()["library_confirmed"] is None
    assert queue.puts == ["retry-job"]


async def test_pending_sync_survives_history_cleanup(client, session_factory):
    from backend.app.db.models import Job

    async with session_factory() as session:
        session.add(
            Job(id="pending-sync", kind="download", status="done", library_status="pending")
        )
        session.add(
            Job(
                id="confirmed-sync",
                kind="download",
                status="done",
                library_status="confirmed",
                library_confirmed=True,
            )
        )
        await session.commit()
    assert (await client.delete("/api/jobs/pending-sync")).status_code == 409
    assert (await client.post("/api/jobs/clear")).json()["deleted"] == 1
    assert (await client.get("/api/jobs/pending-sync")).status_code == 200
    assert (await client.get("/api/jobs/confirmed-sync")).status_code == 404
