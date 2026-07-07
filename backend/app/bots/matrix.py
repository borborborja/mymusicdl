"""Matrix bot — client-server API /sync long-polling over httpx (no E2E encryption).

For a self-hosted family setup the bot lives in a dedicated, unencrypted room: invite the bot user
(it auto-joins), then send a song name. It replies with a numbered list; reply with a number to
download. Commands are limited to an allowlist of Matrix user IDs.

Note: this speaks plain (unencrypted) Matrix. In an end-to-end-encrypted room the bot can't read
messages — keep its room unencrypted, which is the default for a new non-E2E room.
"""

from __future__ import annotations

import asyncio
import contextlib
from urllib.parse import quote

import httpx

from backend.app.bots.base import BotAdapter, BotStatus
from backend.app.bots.core import BotCore, split_limit
from backend.app.logging import get_logger

log = get_logger(__name__)

_HELP = (
    "🎵 mymusicdl\n"
    "Envíame el nombre de una canción o «artista - título» y responde con el número para descargar.\n"
    "✅ = ya en tu biblioteca · ⬆️ = tienes una versión mejorable.\n"
    "Comandos:\n"
    "• !buscar <texto> [N] — canciones (N = nº de resultados, máx. 20)\n"
    "• !album <texto> [N] — álbumes; responde con el número para descargarlo entero (pista a pista)\n"
    "• !ayuda"
)


class MatrixBot(BotAdapter):
    name = "matrix"

    def __init__(
        self,
        core: BotCore,
        *,
        homeserver: str | None,
        user_id: str | None,
        access_token: str | None,
        allowed_users: set[str],
        room_id: str | None,
        source: str | None,
    ) -> None:
        self.core = core
        self.homeserver = (homeserver or "").rstrip("/")
        self.user_id = user_id
        self.token = access_token
        self.allowed = set(allowed_users or set())
        self.room_id = room_id or None
        self.source = source
        self._http: httpx.AsyncClient | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._connected = False
        self._identity: str | None = user_id
        self._error: str | None = None
        self._since: str | None = None
        self._txn = 0

    @property
    def configured(self) -> bool:
        return bool(self.homeserver and self.token)

    # ── transport ──
    def _url(self, path: str) -> str:
        return f"{self.homeserver}/_matrix/client/v3{path}"

    async def _send(self, room_id: str, body: str) -> None:
        assert self._http is not None
        self._txn += 1
        txn = f"mmdl{self._txn}"
        await self._http.put(
            self._url(f"/rooms/{quote(room_id, safe='')}/send/m.room.message/{txn}"),
            json={"msgtype": "m.text", "body": body},
        )

    async def _safe_send(self, room_id: str, body: str) -> None:
        with contextlib.suppress(Exception):
            await self._send(room_id, body)

    # ── lifecycle ──
    async def start(self) -> None:
        if not self.configured:
            return
        self._http = httpx.AsyncClient(
            timeout=40.0, headers={"Authorization": f"Bearer {self.token}"}
        )
        try:
            who = await self._http.get(self._url("/account/whoami"))
            who.raise_for_status()
            self.user_id = who.json().get("user_id") or self.user_id
            self._identity = self.user_id
            self._connected = True
            self._error = None
        except Exception as exc:  # noqa: BLE001 — bad token / unreachable homeserver
            self._error = f"whoami falló: {exc}"
            log.warning("Matrix whoami failed: %s", exc)
            await self._http.aclose()
            self._http = None
            return
        # Initial sync with timeout=0 to grab a fresh token and skip room history.
        try:
            resp = await self._http.get(self._url("/sync"), params={"timeout": 0})
            resp.raise_for_status()
            self._since = resp.json().get("next_batch")
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())
        log.info("Matrix bot started as %s", self.user_id)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._connected = False

    def status(self) -> BotStatus:
        return BotStatus(
            name=self.name,
            enabled=self.enabled,
            configured=self.configured,
            source=self.source,
            running=self._running,
            connected=self._connected,
            identity=self._identity,
            allowed_count=len(self.allowed),
            error=self._error,
        )

    # ── sync ──
    async def _sync_loop(self) -> None:
        while self._running:
            try:
                params = {"timeout": 25000}
                if self._since:
                    params["since"] = self._since
                resp = await self._http.get(self._url("/sync"), params=params)
                resp.raise_for_status()
                data = resp.json()
                self._connected = True
                self._error = None
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self._error = str(exc)
                self._connected = False
                await asyncio.sleep(3)
                continue
            self._since = data.get("next_batch", self._since)
            try:
                await self._process_sync(data)
            except Exception:
                log.exception("matrix sync handling failed")

    async def _process_sync(self, data: dict) -> None:
        rooms = data.get("rooms") or {}
        # Auto-join rooms we've been invited to (commands are still allowlist-gated).
        for invited_room in rooms.get("invite") or {}:
            with contextlib.suppress(Exception):
                await self._http.post(self._url(f"/join/{quote(invited_room, safe='')}"))
        for rid, room in (rooms.get("join") or {}).items():
            if self.room_id and rid != self.room_id:
                continue
            for ev in (room.get("timeline") or {}).get("events") or []:
                if ev.get("type") != "m.room.message":
                    continue
                content = ev.get("content") or {}
                if content.get("msgtype") != "m.text":
                    continue
                sender = ev.get("sender")
                if sender == self.user_id:
                    continue  # ignore our own echoes
                body = (content.get("body") or "").strip()
                if body:
                    await self._handle(rid, sender, body)

    def _is_allowed(self, sender) -> bool:
        if not self.allowed:
            return False
        return sender in self.allowed

    async def _handle(self, room_id: str, sender: str, body: str) -> None:
        if not self._is_allowed(sender):
            await self._send(
                room_id, f"🚫 No autorizado. Pide al administrador que añada tu usuario: {sender}"
            )
            return
        low = body.lower()
        if low in ("!help", "!ayuda", "/help", "/ayuda"):
            await self._send(room_id, _HELP)
            return
        if body.isdigit():
            await self._download_number(room_id, int(body))
            return
        if low.startswith("!album"):
            await self._search_albums(room_id, body[6:].strip())
            return
        query = body[7:].strip() if low.startswith("!buscar") else body
        await self._search_songs(room_id, query)

    async def _search_songs(self, room_id: str, raw: str) -> None:
        if not raw:
            await self._send(room_id, "Escribe el nombre de una canción para buscar.")
            return
        query, limit = split_limit(raw, 6)
        await self._send(room_id, f"🔎 Buscando «{query}»…")
        try:
            tracks = await self.core.search_songs(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            await self._send(room_id, f"Error en la búsqueda: {exc}")
            return
        if not tracks:
            await self._send(room_id, "Sin resultados.")
            return
        items = [self.core.song_item(t) for t in tracks]
        await self.core.save_selection(self.name, room_id, "songs", items)
        lines = []
        for i, it in enumerate(items):
            mark = " ✅" if it["in_library"] else (" ⬆️" if it["can_upgrade"] else "")
            extra = f" · {it['album']}" if it["album"] else ""
            lines.append(f"{i + 1}. {it['label']}{extra}{mark}")
        lines.append("Responde con el número para descargar.")
        await self._send(room_id, "\n".join(lines))

    async def _search_albums(self, room_id: str, raw: str) -> None:
        if not raw:
            await self._send(room_id, "Escribe el nombre de un álbum o artista para buscar.")
            return
        query, limit = split_limit(raw, 6)
        await self._send(room_id, f"🔎 Buscando álbumes «{query}»…")
        try:
            albums = await self.core.search_albums(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            await self._send(room_id, f"Error en la búsqueda: {exc}")
            return
        if not albums:
            await self._send(room_id, "Sin resultados.")
            return
        items = [self.core.album_item(a) for a in albums]
        await self.core.save_selection(self.name, room_id, "albums", items)
        lines = []
        for i, it in enumerate(items):
            meta = " · ".join(str(x) for x in (it.get("year"), f"{it['total_tracks']} pistas") if x)
            lines.append(f"{i + 1}. {it['label']}" + (f" ({meta})" if meta else ""))
        lines.append("Responde con el número para descargar el álbum entero (pista a pista).")
        await self._send(room_id, "\n".join(lines))

    async def _download_number(self, room_id: str, number: int) -> None:
        sel = await self.core.load_selection(self.name, room_id)
        items = (sel or {}).get("items") or []
        idx = number - 1
        if not sel or idx < 0 or idx >= len(items):
            await self._send(room_id, "Selección caducada, vuelve a buscar.")
            return
        if sel.get("mode") == "albums":
            it = items[idx]
            queued, skipped = await self.core.enqueue_album(
                it["provider"], it["id"], origin=self.name
            )
            if not queued and not skipped:
                await self._send(room_id, "No hay fuentes disponibles para ese álbum.")
                return
            extra = f" ({skipped} ya en cola)" if skipped else ""
            await self._send(room_id, f"💿 {queued} pista(s) de «{it['label']}» en cola{extra}.")
            return
        item = items[idx]
        status = await self.core.enqueue_song_item(item, origin=self.name, chat_id=room_id)
        msg = {
            "queued": f"🎵 En cola: {item['label']}",
            "duplicate": f"⏳ Ya estaba en cola: {item['label']}",
            "no_source": "No hay ninguna fuente disponible para esa pista.",
        }[status]
        await self._send(room_id, msg)

    async def on_job_terminal(self, job: dict) -> None:
        room_id = job.get("origin_chat")
        if not room_id:
            return
        title = job.get("title") or "pista"
        if job.get("status") == "done":
            await self._safe_send(room_id, f"✅ Descargado: {title}")
        else:
            await self._safe_send(room_id, f"❌ Error: {title}\n{(job.get('error') or '')[:200]}")
