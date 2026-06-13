"""FastAPI application factory.

Lifespan builds the app-wide singletons (provider registry, Navidrome client, progress broker,
download queue + worker pool, search aggregator, updater) and starts the background workers.
The built React SPA (when present) is served as static files with client-side-routing fallback.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.db.engine import SessionLocal, init_db
from backend.app.db.models import Credential
from backend.app.logging import get_logger, setup_logging
from backend.app.security import decrypt_secret

log = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


async def _load_credentials(session, registry, settings) -> None:
    """Re-apply persisted provider credentials so paid sources survive a restart."""
    res = await session.execute(select(Credential).where(Credential.enabled.is_(True)))
    for cred in res.scalars().all():
        try:
            data = json.loads(decrypt_secret(cred.data_json, settings.app_secret))
            registry.set_credentials(cred.provider, data)
            log.info("Loaded credentials for provider '%s'", cred.provider)
        except Exception:
            log.warning("Failed to load credentials for '%s'", cred.provider, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    log.info("Starting mymusicdl (data=%s music=%s)", settings.app_data_dir, settings.music_library_path)

    await init_db()

    # Lazily import subsystems to keep import-time side effects out of module load.
    from backend.app.downloads.progress import ProgressBroker
    from backend.app.downloads.queue import DownloadQueue
    from backend.app.downloads.worker import WorkerPool
    from backend.app.metadata.aggregator import SearchAggregator
    from backend.app.navidrome.client import build_navidrome
    from backend.app.providers.registry import build_registry
    from backend.app.updater.service import Updater

    broker = ProgressBroker()
    registry = build_registry(settings)
    navidrome = build_navidrome(settings)
    queue = DownloadQueue()
    aggregator = SearchAggregator(
        settings=settings, registry=registry, navidrome=navidrome, session_factory=SessionLocal
    )
    worker = WorkerPool(
        settings=settings,
        queue=queue,
        broker=broker,
        registry=registry,
        navidrome=navidrome,
        session_factory=SessionLocal,
    )
    updater = Updater(settings=settings, session_factory=SessionLocal, broker=broker, queue=queue)

    app.state.settings = settings
    app.state.broker = broker
    app.state.registry = registry
    app.state.navidrome = navidrome
    app.state.queue = queue
    app.state.aggregator = aggregator
    app.state.worker = worker
    app.state.updater = updater

    # Reload persisted credentials, requeue interrupted jobs, then start workers.
    async with SessionLocal() as session:
        await _load_credentials(session, registry, settings)
        await queue.rehydrate(session)
    await worker.start()
    await updater.start()

    try:
        yield
    finally:
        log.info("Shutting down mymusicdl")
        await worker.stop()
        await updater.stop()
        if navidrome is not None:
            await navidrome.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="mymusicdl", version="0.1.0", lifespan=lifespan)

    # ── API routers ──
    from backend.app.api import (
        routes_album,
        routes_downloads,
        routes_events,
        routes_health,
        routes_jobs,
        routes_library,
        routes_search,
        routes_settings,
        routes_tools,
    )

    app.include_router(routes_health.router, prefix="/api", tags=["health"])
    app.include_router(routes_search.router, prefix="/api", tags=["search"])
    app.include_router(routes_album.router, prefix="/api", tags=["album"])
    app.include_router(routes_downloads.router, prefix="/api", tags=["downloads"])
    app.include_router(routes_jobs.router, prefix="/api", tags=["jobs"])
    app.include_router(routes_library.router, prefix="/api", tags=["library"])
    app.include_router(routes_tools.router, prefix="/api", tags=["tools"])
    app.include_router(routes_settings.router, prefix="/api", tags=["settings"])
    app.include_router(routes_events.router, prefix="/api", tags=["events"])

    # ── SPA static (built into the image at /static; absent in dev → Vite serves it) ──
    if STATIC_DIR.exists():
        assets = STATIC_DIR / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        index_file = STATIC_DIR / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("api"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = STATIC_DIR / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)

    return app


app = create_app()
