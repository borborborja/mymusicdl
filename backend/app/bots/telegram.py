"""Telegram bot — Bot API long-polling over httpx (no extra dependency).

Send the bot a song name; it replies with a few matches as inline buttons. Tap one and it queues
the best available quality and pings you when the download finishes. Commands are restricted to an
allowlist of numeric user IDs; an unauthorised user is told their own ID so an admin can add it.
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx

from backend.app.bots.base import BotAdapter, BotStatus
from backend.app.bots.core import BotCore, split_limit
from backend.app.logging import get_logger

log = get_logger(__name__)

_API = "https://api.telegram.org"

_HELP = (
    "🎵 mymusicdl\n"
    "Envíame el nombre de una canción o «artista - título» y te muestro resultados para descargar.\n"
    "Toca un resultado para descargarlo. ✅ = ya en tu biblioteca · ⬆️ = tienes una versión mejorable.\n\n"
    "Comandos:\n"
    "• /buscar <texto> [N] — canciones (N = nº de resultados, máx. 20)\n"
    "• /album <texto> [N] — álbumes; toca uno para descargarlo entero (pista a pista)\n"
    "• /estado, /ayuda"
)


class TelegramBot(BotAdapter):
    name = "telegram"

    def __init__(
        self, core: BotCore, *, token: str | None, allowed_users: set[int], source: str | None
    ) -> None:
        self.core = core
        self.token = token
        self.allowed = set(allowed_users or set())
        self.source = source
        self._http: httpx.AsyncClient | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._connected = False
        self._identity: str | None = None
        self._error: str | None = None
        self._offset: int | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token)

    # ── transport ──
    def _url(self, method: str) -> str:
        return f"{_API}/bot{self.token}/{method}"

    async def _call(self, method: str, **params) -> object:
        assert self._http is not None
        resp = await self._http.post(self._url(method), json=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "telegram error"))
        return data.get("result")

    async def _send(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        params: dict = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            params["reply_markup"] = reply_markup
        await self._call("sendMessage", **params)

    async def _safe_send(self, chat_id: int, text: str) -> None:
        with contextlib.suppress(Exception):
            await self._send(chat_id, text)

    # ── lifecycle ──
    async def start(self) -> None:
        if not self.configured:
            return
        self._http = httpx.AsyncClient(timeout=40.0)
        try:
            me = await self._call("getMe")
            self._identity = "@" + (me or {}).get("username", "")  # type: ignore[union-attr]
            self._connected = True
            self._error = None
        except (
            Exception
        ) as exc:  # noqa: BLE001 — bad token etc.; surface in status, don't crash boot
            self._error = f"getMe falló: {exc}"
            log.warning("Telegram getMe failed: %s", exc)
            await self._http.aclose()
            self._http = None
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        log.info("Telegram bot started as %s", self._identity)

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

    # ── polling ──
    async def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = await self._call(
                    "getUpdates",
                    offset=self._offset,
                    timeout=25,
                    allowed_updates=["message", "callback_query"],
                )
                self._connected = True
                self._error = None
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self._error = str(exc)
                self._connected = False
                await asyncio.sleep(3)
                continue
            for upd in updates or []:  # type: ignore[union-attr]
                self._offset = upd["update_id"] + 1
                try:
                    await self._handle(upd)
                except Exception:
                    log.exception("telegram update handling failed")

    def _is_allowed(self, user_id) -> bool:
        if not self.allowed:
            return (
                False  # empty allowlist → deny (we reply with the user's id so they can be added)
            )
        try:
            return int(user_id) in self.allowed
        except (TypeError, ValueError):
            return False

    async def _handle(self, upd: dict) -> None:
        if "callback_query" in upd:
            cq = upd["callback_query"]
            await self._call("answerCallbackQuery", callback_query_id=cq["id"])
            chat_id = cq["message"]["chat"]["id"]
            user_id = (cq.get("from") or {}).get("id")
            if not self._is_allowed(user_id):
                await self._send(chat_id, f"🚫 No autorizado. Tu ID de Telegram: {user_id}")
                return
            data = cq.get("data") or ""
            if data.startswith("dl:"):
                with contextlib.suppress(ValueError):
                    await self._download_song(chat_id, int(data[3:]))
            elif data.startswith("al:"):
                with contextlib.suppress(ValueError):
                    await self._download_album(chat_id, int(data[3:]))
            return

        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            return
        chat_id = msg["chat"]["id"]
        user_id = (msg.get("from") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if not text:
            return
        if not self._is_allowed(user_id):
            await self._send(
                chat_id,
                f"🚫 No autorizado.\nTu ID de Telegram es {user_id}. "
                "Pide al administrador que lo añada a la allowlist.",
            )
            return
        await self._handle_text(chat_id, text)

    async def _handle_text(self, chat_id: int, text: str) -> None:
        low = text.lower()
        if low in ("/start", "/help", "/ayuda"):
            await self._send(chat_id, _HELP)
            return
        if low in ("/estado", "/status"):
            await self._send(
                chat_id, f"✅ Conectado como {self._identity}. Envíame una canción para buscar."
            )
            return
        if low.startswith("/album"):
            await self._search_albums(chat_id, text[6:].strip())
            return
        query = text[7:].strip() if low.startswith("/buscar") else text
        await self._search_songs(chat_id, query)

    async def _search_songs(self, chat_id: int, raw: str) -> None:
        if not raw:
            await self._send(chat_id, "Escribe el nombre de una canción para buscar.")
            return
        query, limit = split_limit(raw, 6)
        await self._send(chat_id, f"🔎 Buscando «{query}»…")
        try:
            tracks = await self.core.search_songs(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            await self._send(chat_id, f"Error en la búsqueda: {exc}")
            return
        if not tracks:
            await self._send(chat_id, "Sin resultados.")
            return
        items = [self.core.song_item(t) for t in tracks]
        await self.core.save_selection(self.name, str(chat_id), "songs", items)
        lines, buttons = [], []
        for i, it in enumerate(items):
            mark = " ✅" if it["in_library"] else (" ⬆️" if it["can_upgrade"] else "")
            extra = f" · {it['album']}" if it["album"] else ""
            lines.append(f"{i + 1}. {it['label']}{extra}{mark}")
            buttons.append(
                [{"text": f"⬇️ {i + 1}. {it['label'][:40]}", "callback_data": f"dl:{i}"}]
            )
        await self._send(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": buttons})

    async def _search_albums(self, chat_id: int, raw: str) -> None:
        if not raw:
            await self._send(chat_id, "Escribe el nombre de un álbum o artista para buscar.")
            return
        query, limit = split_limit(raw, 6)
        await self._send(chat_id, f"🔎 Buscando álbumes «{query}»…")
        try:
            albums = await self.core.search_albums(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            await self._send(chat_id, f"Error en la búsqueda: {exc}")
            return
        if not albums:
            await self._send(chat_id, "Sin resultados.")
            return
        items = [self.core.album_item(a) for a in albums]
        await self.core.save_selection(self.name, str(chat_id), "albums", items)
        lines, buttons = [], []
        for i, it in enumerate(items):
            meta = " · ".join(str(x) for x in (it.get("year"), f"{it['total_tracks']} pistas") if x)
            lines.append(f"{i + 1}. {it['label']}" + (f" ({meta})" if meta else ""))
            buttons.append(
                [{"text": f"💿 {i + 1}. {it['label'][:40]}", "callback_data": f"al:{i}"}]
            )
        lines.append("Toca un álbum para descargarlo entero (pista a pista).")
        await self._send(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": buttons})

    async def _selection(self, chat_id: int, mode: str) -> list[dict] | None:
        sel = await self.core.load_selection(self.name, str(chat_id))
        if not sel or sel.get("mode") != mode:
            return None
        return sel.get("items") or []

    async def _download_song(self, chat_id: int, idx: int) -> None:
        items = await self._selection(chat_id, "songs")
        if items is None or idx < 0 or idx >= len(items):
            await self._send(chat_id, "Selección caducada, vuelve a buscar.")
            return
        item = items[idx]
        job = await self.core.enqueue_song_item(item, origin=self.name, chat_id=str(chat_id))
        if job is None:
            await self._send(chat_id, "No hay ninguna fuente disponible para esa pista.")
            return
        await self._send(chat_id, f"🎵 En cola: {item['label']}")

    async def _download_album(self, chat_id: int, idx: int) -> None:
        items = await self._selection(chat_id, "albums")
        if items is None or idx < 0 or idx >= len(items):
            await self._send(chat_id, "Selección caducada, vuelve a buscar.")
            return
        it = items[idx]
        n = await self.core.enqueue_album(it["provider"], it["id"], origin=self.name)
        if not n:
            await self._send(chat_id, "No hay fuentes disponibles para ese álbum.")
            return
        await self._send(chat_id, f"💿 {n} pista(s) de «{it['label']}» en cola.")

    async def on_job_terminal(self, job: dict) -> None:
        chat_id = job.get("origin_chat")
        if not chat_id:
            return
        title = job.get("title") or "pista"
        if job.get("status") == "done":
            await self._safe_send(int(chat_id), f"✅ Descargado: {title}")
        else:
            await self._safe_send(
                int(chat_id), f"❌ Error: {title}\n{(job.get('error') or '')[:200]}"
            )
