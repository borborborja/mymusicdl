"""Async SQLAlchemy engine + session factory + table bootstrap."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.config import get_settings
from backend.app.db.base import Base
from backend.app.logging import get_logger

log = get_logger(__name__)

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create tables from the ORM metadata if they don't exist (idempotent)."""
    _settings.ensure_dirs()
    # Import models so they are registered on Base.metadata.
    from backend.app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)


# Lightweight, idempotent column adds for tables that predate a new field. ``create_all`` only
# creates missing tables — it never ALTERs existing ones — so a DB created before a column was
# introduced needs this. (Alembic remains available for anything more involved.)
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "jobs": {
        "origin": "VARCHAR(16) DEFAULT 'web'",
        "library_confirmed": "BOOLEAN",
        "origin_chat": "VARCHAR(128)",
    },
}


def _ensure_columns(conn) -> None:
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    for table, columns in _ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in present:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                log.info("Added column %s.%s", table, name)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — yields a session and closes it afterwards."""
    async with SessionLocal() as session:
        yield session
