"""SQLAlchemy 2.0 models.

Five tables underpin every feature:
  library_items  — tracks we've downloaded / detected in Navidrome, with their quality
  jobs           — durable queue of download / tool-update / rescan / version-check work
  tools          — tracked downloader CLIs: installed vs latest version + changelog
  settings       — key/value app config overrides
  credentials    — per-provider secrets; presence flips a paid provider to "enabled"
  bot_selections — a chat's last search results, so "reply with N" survives a restart
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base, utcnow


class LibraryItem(Base):
    __tablename__ = "library_items"
    __table_args__ = (
        UniqueConstraint(
            "artist", "title", "album", "quality_tier", name="uq_library_track_quality"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    navidrome_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(512))
    artist: Mapped[str] = mapped_column(String(512))
    album: Mapped[str | None] = mapped_column(String(512), nullable=True)
    isrc: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    mbid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_path: Mapped[str] = mapped_column(Text)
    fmt: Mapped[str] = mapped_column(String(16))
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_tier: Mapped[int] = mapped_column(Integer)  # Quality enum 0..4
    source_provider: Mapped[str] = mapped_column(String(32))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    kind: Mapped[str] = mapped_column(
        String(24), index=True
    )  # download|tool_update|rescan|version_check
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    track_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # serialized TrackRef
    requested_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dest_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # None = not checked yet; True/False = confirmed present / not found in Navidrome after rescan.
    library_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)  # human label for the UI
    origin: Mapped[str] = mapped_column(
        String(16), default="web"
    )  # web|telegram|matrix (who queued it)
    # Chat/room id of the bot that queued it, so terminal-status pings survive a restart
    # (they no longer live in an in-memory dict on the adapter). Null for web/album-batch jobs.
    origin_chat: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Tool(Base):
    __tablename__ = "tools"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)  # pypi package name
    installed_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_available: Mapped[bool] = mapped_column(Boolean, default=False)
    repo: Mapped[str | None] = mapped_column(String(128), nullable=True)  # "owner/repo"
    latest_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    managed: Mapped[bool] = mapped_column(Boolean, default=True)  # in mounted venv (updatable)


class AppSetting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BotSelection(Base):
    """Last search results a bot showed a chat, so "reply with N" survives a restart.

    One row per (platform, chat_id); ``payload`` is a JSON blob of {mode, items} the adapter uses to
    resolve a numeric pick back to a download.
    """

    __tablename__ = "bot_selections"

    platform: Mapped[str] = mapped_column(String(16), primary_key=True)  # telegram|matrix
    chat_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)  # JSON {mode: songs|albums, items: [...]}
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Credential(Base):
    __tablename__ = "credentials"

    provider: Mapped[str] = mapped_column(
        String(32), primary_key=True
    )  # tidal|qobuz|deezer|spotify
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    data_json: Mapped[str] = mapped_column(Text)  # encrypted blob (see security.crypto)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ok|invalid|untested
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
