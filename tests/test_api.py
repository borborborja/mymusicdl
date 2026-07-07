"""API-route tests via httpx ASGITransport with dependency overrides (no network, no lifespan)."""

from __future__ import annotations

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
