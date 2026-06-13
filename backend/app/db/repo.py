"""Small repository helpers shared across services.

Kept intentionally thin: routers/services mostly use the session directly; these wrap the few
queries that are reused in more than one place.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import AppSetting, LibraryItem, Tool


# ── settings (key/value) ──
async def get_setting(session: AsyncSession, key: str) -> str | None:
    row = await session.get(AppSetting, key)
    return row.value if row else None


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    await session.commit()


# ── tools ──
async def list_tools(session: AsyncSession) -> list[Tool]:
    res = await session.execute(select(Tool).order_by(Tool.name))
    return list(res.scalars().all())


async def upsert_tool(session: AsyncSession, name: str, **fields) -> Tool:
    row = await session.get(Tool, name)
    if row is None:
        row = Tool(name=name, **fields)
        session.add(row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    await session.commit()
    return row


# ── library ──
async def find_library_matches(
    session: AsyncSession, *, artist: str, title: str, album: str | None = None
) -> list[LibraryItem]:
    """Best-effort match by normalized artist+title (+album when given)."""
    from backend.app.navidrome.matcher import norm

    stmt = select(LibraryItem)
    res = await session.execute(stmt)
    out: list[LibraryItem] = []
    for item in res.scalars().all():
        if norm(item.artist) == norm(artist) and norm(item.title) == norm(title):
            if album and norm(item.album or "") != norm(album):
                continue
            out.append(item)
    return out
