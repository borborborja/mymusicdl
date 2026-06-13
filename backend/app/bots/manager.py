"""Bot manager — owns the adapters, resolves their config, and routes completion pings.

Config precedence per bot: environment variables first, else an encrypted row in the ``credentials``
table (provider ``bot:telegram`` / ``bot:matrix``) set from the Settings page. The manager also
subscribes to the progress broker and forwards terminal download events to the bot that queued them
(``origin``), so the chat user gets a "done/failed" message.
"""
from __future__ import annotations

import asyncio
import contextlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.bots.base import BotAdapter
from backend.app.bots.core import BotCore
from backend.app.bots.matrix import MatrixBot
from backend.app.bots.telegram import TelegramBot
from backend.app.config import Settings
from backend.app.db.models import Credential
from backend.app.logging import get_logger
from backend.app.security import decrypt_secret, encrypt_secret

log = get_logger(__name__)

BOT_NAMES = ("telegram", "matrix")


def _parse_int_csv(value) -> set[int]:
    if not value:
        return set()
    if isinstance(value, (list, set, tuple)):
        parts = value
    else:
        parts = str(value).replace(";", ",").split(",")
    out: set[int] = set()
    for part in parts:
        part = str(part).strip()
        if part:
            with contextlib.suppress(ValueError):
                out.add(int(part))
    return out


def _parse_str_csv(value) -> set[str]:
    if not value:
        return set()
    if isinstance(value, (list, set, tuple)):
        return {str(x).strip() for x in value if str(x).strip()}
    return {p.strip() for p in str(value).replace(";", ",").split(",") if p.strip()}


class BotManager:
    def __init__(self, *, settings: Settings, session_factory, broker, queue, registry, aggregator) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.broker = broker
        self.core = BotCore(
            aggregator=aggregator,
            registry=registry,
            settings=settings,
            queue=queue,
            session_factory=session_factory,
        )
        self.adapters: dict[str, BotAdapter] = {}
        self._notify_task: asyncio.Task | None = None

    # ── config resolution ──
    def _env_config(self, name: str) -> dict:
        s = self.settings
        if name == "telegram" and s.telegram_bot_token:
            return {"token": s.telegram_bot_token, "allowed_users": s.telegram_allowed_users}
        if name == "matrix" and s.matrix_homeserver and s.matrix_access_token:
            return {
                "homeserver": s.matrix_homeserver,
                "user_id": s.matrix_user_id,
                "access_token": s.matrix_access_token,
                "allowed_users": s.matrix_allowed_users,
                "room_id": s.matrix_room_id,
            }
        return {}

    async def _db_config(self, name: str) -> dict:
        async with self.session_factory() as session:  # type: AsyncSession
            cred = await session.get(Credential, f"bot:{name}")
            if cred is None or not cred.enabled:
                return {}
            try:
                return json.loads(decrypt_secret(cred.data_json, self.settings.app_secret))
            except Exception:  # noqa: BLE001
                log.warning("Failed to decrypt bot config for %s", name, exc_info=True)
                return {}

    async def _resolve(self, name: str) -> tuple[dict, str | None]:
        env = self._env_config(name)
        if env:
            return env, "env"
        db = await self._db_config(name)
        if db:
            return db, "db"
        return {}, None

    def _make_adapter(self, name: str, cfg: dict, source: str | None) -> BotAdapter:
        if name == "telegram":
            return TelegramBot(
                self.core,
                token=cfg.get("token"),
                allowed_users=_parse_int_csv(cfg.get("allowed_users")),
                source=source,
            )
        return MatrixBot(
            self.core,
            homeserver=cfg.get("homeserver"),
            user_id=cfg.get("user_id"),
            access_token=cfg.get("access_token"),
            allowed_users=_parse_str_csv(cfg.get("allowed_users")),
            room_id=cfg.get("room_id"),
            source=source,
        )

    async def _build(self, name: str) -> BotAdapter:
        cfg, source = await self._resolve(name)
        return self._make_adapter(name, cfg, source)

    # ── lifecycle ──
    async def start(self) -> None:
        for name in BOT_NAMES:
            adapter = await self._build(name)
            self.adapters[name] = adapter
            if adapter.enabled:
                with contextlib.suppress(Exception):
                    await adapter.start()
        self._notify_task = asyncio.create_task(self._notify_loop())

    async def stop(self) -> None:
        if self._notify_task is not None:
            self._notify_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._notify_task
            self._notify_task = None
        for adapter in self.adapters.values():
            with contextlib.suppress(Exception):
                await adapter.stop()

    async def reload(self, name: str) -> None:
        """Rebuild and restart a single bot after its config changed (no full app restart)."""
        old = self.adapters.get(name)
        if old is not None:
            with contextlib.suppress(Exception):
                await old.stop()
        adapter = await self._build(name)
        self.adapters[name] = adapter
        if adapter.enabled:
            with contextlib.suppress(Exception):
                await adapter.start()

    # ── completion notifications ──
    async def _notify_loop(self) -> None:
        q = self.broker.subscribe()
        try:
            while True:
                ev = await q.get()
                if ev.get("type") != "job":
                    continue
                job = ev.get("job") or {}
                if job.get("kind") != "download" or job.get("status") not in ("done", "error"):
                    continue
                adapter = self.adapters.get(job.get("origin"))
                if adapter is not None:
                    with contextlib.suppress(Exception):
                        await adapter.on_job_terminal(job)
        except asyncio.CancelledError:
            pass
        finally:
            self.broker.unsubscribe(q)

    # ── settings API helpers ──
    def status(self) -> list[dict]:
        return [self.adapters[name].status().to_dict() for name in BOT_NAMES if name in self.adapters]

    async def save_config(self, name: str, data: dict) -> None:
        """Persist bot config (encrypted) to the DB and hot-reload the bot."""
        if name not in BOT_NAMES:
            raise ValueError(f"Unknown bot '{name}'")
        encrypted = encrypt_secret(json.dumps(data), self.settings.app_secret)
        async with self.session_factory() as session:
            cred = await session.get(Credential, f"bot:{name}")
            if cred is None:
                session.add(
                    Credential(provider=f"bot:{name}", enabled=True, data_json=encrypted, status="ok")
                )
            else:
                cred.data_json, cred.enabled, cred.status = encrypted, True, "ok"
            await session.commit()
        await self.reload(name)

    async def delete_config(self, name: str) -> None:
        """Disable a bot's DB config and hot-reload (env config, if any, still applies)."""
        if name not in BOT_NAMES:
            raise ValueError(f"Unknown bot '{name}'")
        async with self.session_factory() as session:
            cred = await session.get(Credential, f"bot:{name}")
            if cred is not None:
                cred.enabled = False
                await session.commit()
        await self.reload(name)
