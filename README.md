# mymusicdl

Self-hosted **family music downloader** that adds well-tagged **single tracks** to a
[Navidrome](https://www.navidrome.org/) library. Search by artist / album / song, see which
qualities are available per source, download one track or a batch, and let the app tell you what's
**already in the library and at what quality** (so you can re-download to something better).

The downloaded file is written **directly into the Navidrome library path** (a shared
`rclone → pCloud` mount), and Navidrome is asked to rescan.

> Status: **initial scaffold**. The free path (`spotdl` + `yt-dlp`) is wired end-to-end-ready.
> Paid lossless sources (Tidal / Qobuz / Deezer via `streamrip`, plus `tiddl` for Tidal) are
> implemented as **adapters that stay disabled until you add credentials**.

## Architecture

```
React + Vite + Tailwind SPA  ──/api──▶  FastAPI (uvicorn)
                                          ├─ metadata/   Spotify → MusicBrainz search
                                          ├─ providers/  spotdl · yt-dlp · (streamrip · tiddl)
                                          ├─ downloads/  asyncio worker pool + SQLite queue + SSE
                                          ├─ navidrome/  Subsonic client (search3/getSong/startScan)
                                          ├─ updater/    PyPI version + GitHub changelog + pip -U
                                          └─ db/         SQLite (SQLAlchemy 2.0 async)
```

- **No Redis / no Celery.** Jobs are rows in SQLite consumed by an in-process `asyncio` worker pool;
  progress is streamed to the browser over **SSE** (`/api/events`).
- **Tools live in a mounted venv** (`$TOOLS_VENV`, default `/data/toolsvenv`) so in-app
  `pip install -U` survives container recreation by Watchtower.
- **Auth** is delegated to the edge (Cloudflare Access via the Dockflare access group). An optional
  `APP_SHARED_PASSWORD` adds a simple shared-secret gate on top.

## Repository layout

```
backend/app/   FastAPI backend (api, providers, metadata, navidrome, downloads, library, updater, db)
frontend/      React + Vite + Tailwind SPA (built into the image, served as static files)
scripts/       entrypoint.sh (bootstrap tools venv + run) and bootstrap_tools.sh
compose.yaml   Homelab stack (homelab conventions)
Dockerfile     Multi-stage: build SPA → python+ffmpeg runtime
```

## Local development

Backend:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# downloader tools into a local tools venv (or just pip install them in .venv for dev)
python -m venv ./data/toolsvenv && ./data/toolsvenv/bin/pip install spotdl yt-dlp
cp .env.example .env            # tweak APP_DATA_DIR=./data, MUSIC_LIBRARY_PATH=./music, etc.
uvicorn backend.app.main:app --reload --port 8080
```

Frontend (dev server proxies `/api` → `:8080`):

```bash
cd frontend && npm install && npm run dev
```

Tables are created automatically on startup from the SQLAlchemy models. Alembic is wired
(`alembic/env.py` targets the models' metadata) for when you want versioned migrations —
run `alembic revision --autogenerate -m "..."`.

## Docker / homelab deploy

```bash
# on the homelab host, at /opt/stacks/mymusicdl/
cp .env.example .env            # fill Navidrome + (optional) Spotify creds + APP_SECRET
docker compose up --build -d
docker compose logs -f mymusicdl
```

`compose.yaml` mounts `../../dades/mymusicdl/music` → `/music`. **This must be the same host
path the Navidrome container mounts** (the `rclone → pCloud` mount) so a freshly downloaded file is
immediately visible; after each download the app calls Subsonic `startScan`.

## Enabling paid lossless sources later

The `streamrip` (Tidal/Qobuz/Deezer) and `tiddl` (Tidal) adapters ship disabled. Add credentials —
via the **Settings** page or the `TIDAL_TOKEN` / `QOBUZ_TOKEN` / `DEEZER_ARL` env vars — and the
provider registry starts surfacing them in search and quality badges. No code changes needed.

## Updating the downloader tools

The **Tools** page shows installed vs. latest (PyPI), renders the GitHub changelog, and offers an
in-app update that runs `pip install -U` inside the mounted tools venv. Because that venv is on a
host volume the upgrade persists across restarts.
