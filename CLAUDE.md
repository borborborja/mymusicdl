# CLAUDE.md — read this first

This file is the contract for **any AI agent or human** touching this repo. It is loaded
automatically by Claude Code. If you change code, you are responsible for keeping the
[golden rules](#-golden-rules-do-not-break-these) intact and for
[verifying](#how-to-verify-your-change) your change before claiming it works.

> **If you only read one section, read [Golden rules](#-golden-rules-do-not-break-these).**

---

## What this project is (30-second version)

**mymusicdl** is a self-hosted web app + chat bots that let a family add **well-tagged single
tracks** to a [Navidrome](https://www.navidrome.org/) music library. You search (artist / album /
song), see which qualities each source can deliver, download a track or a batch, and the app tells
you what's already in the library and at what quality. The downloaded file is written **directly into
the shared music volume Navidrome reads**, then Navidrome is asked to rescan.

- **Backend:** FastAPI + Python 3.12, async SQLAlchemy 2.0 over SQLite, no Redis/Celery.
- **Frontend:** React 19 + Vite 8 + Tailwind 4 (built into the image, served as static files).
- **Downloaders:** `spotdl` + `yt-dlp` (free, on by default); `streamrip` for Tidal/Qobuz/Deezer
  (paid, **disabled until credentials are added**). They run as **CLI subprocesses**, not libraries.
- **Bots:** Telegram + Matrix mirror the web app over chat (optional).

Full detail lives in [`docs/`](docs/) — see [the map below](#where-things-are).

---

## 🚨 Golden rules (DO NOT break these)

These are product/architecture invariants. Breaking one silently corrupts the library, leaks
secrets, or breaks deploys. If a task seems to require breaking one, **stop and ask the user.**

1. **Single tracks only — never whole-album blobs.** The entire point is well-tagged individual
   files. An album view expands into selectable tracks; downloading still happens track-by-track.
2. **The download destination (`MUSIC_LIBRARY_PATH` → `/music`) must stay the same volume Navidrome
   mounts.** After a successful download the app calls Subsonic `startScan`. Don't write elsewhere,
   don't skip the rescan.
3. **Downloader CLIs are NOT Python dependencies.** Never add `spotdl`/`yt-dlp`/`streamrip`/`tiddl`
   to `pyproject.toml`. They live in a **volume-mounted venv** (`$TOOLS_VENV`, default
   `/data/toolsvenv`) created by `scripts/bootstrap_tools.sh`, so in-app `pip install -U` persists
   across container recreation. Adding them to pyproject would break the auto-update feature.
4. **`APP_SECRET` encrypts all stored credentials** (Fernet, see `backend/app/security.py`).
   Changing it invalidates every saved Tidal/Qobuz/Deezer/bot credential. Treat it as load-bearing.
5. **Never commit secrets or data.** `.env` and `data/` are gitignored and must stay that way. Only
   `.env.example` (placeholders) is tracked. The git history was scrubbed once already — don't
   reintroduce real hostnames, IPs, tokens, or `.env` content.
6. **`compose.yaml` is generic for a public repo.** Every site-specific value (hostname, networks,
   bind IP, volume, data dir) comes from `.env`. Do **not** hardcode anyone's homelab values back in.
7. **`Quality` enum values (0–4) map 1:1 to streamrip's tiers.** Don't reorder or renumber them —
   stored `quality_tier` values in the DB and the paid adapters depend on the mapping.
8. **Paid providers stay disabled until credentials exist.** Enabling = a credential is present
   (env var or encrypted DB row), never a code change. Don't hardcode `enabled = True`.
9. **Bot allowlist semantics: empty allowlist = deny everyone.** An unauthorised user is told their
   own ID so the admin can add it. Don't "fail open".
10. **Additive DB columns need `_ensure_columns` (or Alembic).** Tables are created with
    `Base.metadata.create_all`, which **never ALTERs** an existing table. A new column on an existing
    table must be added to `_ADDED_COLUMNS` in `backend/app/db/engine.py` or it won't exist on
    upgraded installs. See [conventions](docs/CONVENTIONS.md).

---

## Where things are

```
backend/app/
  main.py            App factory + lifespan: builds all singletons onto app.state, starts workers.
  config.py          Settings (pydantic-settings, env-driven). All env vars are declared here.
  security.py        Fernet encrypt/decrypt of credentials, keyed by APP_SECRET.
  db/                engine.py (async engine + init_db + _ensure_columns), models.py (5 tables).
  providers/         THE pluggable core. base.py = Provider ABC + Quality/TrackRef/ProgressEvent.
                     spotdl_/ytdlp_ (free), streamrip_ (paid), registry.py (build + enable gating).
  downloads/         service.py (shared enqueue), queue.py, worker.py (asyncio pool), runner.py
                     (subprocess streaming), progress.py (pub/sub → SSE).
  metadata/          Search/catalog: spotify.py → musicbrainz.py fallback, aggregator.py.
  navidrome/         client.py (Subsonic API), matcher.py ("already in library @ quality").
  library/tracker.py Records downloads + triggers Navidrome rescan.
  updater/           Tool version checks (PyPI) + changelog (GitHub) + in-venv pip upgrades.
  bots/              base/core/telegram/matrix/manager — chat mirror of the web app.
  api/               Thin routers (search, album, downloads, jobs, library, tools, settings, bots,
                     events[SSE], health). All mounted under /api.
  schemas/           Pydantic DTOs for the API.
frontend/src/        React SPA: pages/, components/, lib/ (api.ts, types.ts, useEvents.ts).
scripts/             entrypoint.sh (bootstrap venv → uvicorn) + bootstrap_tools.sh.
docs/                The detailed docs this file points to.
```

Detailed docs:
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how a request/download flows end to end; the job
  lifecycle; the singletons; key invariants explained.
- [`docs/GUIDELINES.md`](docs/GUIDELINES.md) — coding style + step-by-step recipes for the common
  changes (add a provider, add a route, add an env var, add a DB column, touch the frontend).
- [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) — decisions the **user** designated (must be honored).
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — future goals to keep in mind when writing code now.
- [`docs/VERIFICATION.md`](docs/VERIFICATION.md) — exactly how to verify each kind of change.
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — build + deploy (homelab and generic) + the GHCR gotcha.

---

## How to run it locally

```bash
# Backend (Python 3.12)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m venv ./data/toolsvenv && ./data/toolsvenv/bin/pip install spotdl yt-dlp   # downloader CLIs
cp .env.example .env   # set APP_DATA_DIR=./data, MUSIC_LIBRARY_PATH=./music for local dev
uvicorn backend.app.main:app --reload --port 8080 --timeout-graceful-shutdown 3
#   ^ the --timeout-graceful-shutdown 3 is REQUIRED: the SSE /api/events stream holds a
#     connection open forever, so without it --reload hangs on "waiting for connections to close".

# Frontend (separate terminal; dev server proxies /api → :8080)
cd frontend && npm install && npm run dev
```

## How to verify your change

**Always** run the checks relevant to what you touched before saying it works. Minimum bars:

| You changed…            | Run this                                                                 |
|-------------------------|--------------------------------------------------------------------------|
| Any backend Python      | `python -c "from backend.app.main import create_app; create_app()"` (imports + wiring OK) |
| Backend logic/style     | `ruff check backend && black --check backend`                            |
| Any frontend TS/TSX     | `cd frontend && npm run build`  (runs `tsc -b` typecheck + vite build)    |
| Dockerfile / deps       | `docker build -t mymusicdl:test .`                                       |
| Behavior (run the app)  | start backend, `curl localhost:8080/api/health`, exercise the flow       |

The full per-change matrix (including the download e2e and bot checks) is in
[`docs/VERIFICATION.md`](docs/VERIFICATION.md). **Do not report a change as done without verifying.**

---

## Conventions for working in this repo

- **Match the surrounding code.** Comment density, naming, and idiom are consistent across the
  backend (module docstrings explaining *why*, `from __future__ import annotations`, type hints).
  New code should be indistinguishable from existing code.
- **Keep routers thin.** Business logic lives in the subsystem modules (`downloads/`, `metadata/`,
  `providers/`, …), not in `api/`. Routers validate input and call into those.
- **Line length 100**, Python 3.12 target (`ruff` + `black` configured in `pyproject.toml`).
- **Small, focused commits**; end commit messages with the `Co-Authored-By` trailer.
- **Don't push, deploy, or change repo/package visibility unless the user asks.**
- When in doubt about a product decision, check [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) — if it's
  not answered there, **ask the user** rather than guessing.
