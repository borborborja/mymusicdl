"""Shared fixtures: an in-memory DB and lightweight fakes for the download/enqueue path."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.config import Settings
from backend.app.db import models  # noqa: F401 — register tables on Base.metadata
from backend.app.db.base import Base


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


class FakeProvider:
    enabled = True


class FakeRegistry:
    def get(self, name):
        return FakeProvider()


class FakeQueue:
    def __init__(self):
        self.puts: list[str] = []

    async def put(self, job_id: str) -> None:
        self.puts.append(job_id)


@pytest_asyncio.fixture
def registry():
    return FakeRegistry()


@pytest_asyncio.fixture
def queue():
    return FakeQueue()


@pytest_asyncio.fixture
def settings():
    return Settings(music_library_path="/music")
