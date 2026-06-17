# Verification

How to prove a change works **before** reporting it done. Pick the rows that match what you touched
and run them. "It imports" is not "it works" for behavioral changes.

## Quick reference

| Change type | Command(s) | Pass = |
|---|---|---|
| Any backend Python | `python -c "from backend.app.main import create_app; create_app()"` | no traceback |
| Backend lint/format | `ruff check backend && black --check backend` | clean |
| Provider registry | `python -c "from backend.app.providers.registry import build_registry; from backend.app.config import get_settings; print([p.id for p in build_registry(get_settings()).all()])"` | lists providers, no error |
| Any frontend TS/TSX | `cd frontend && npm run build` | `tsc -b` + vite build succeed |
| Dockerfile / Python deps | `docker build -t mymusicdl:test .` | image builds |
| compose changes | `docker compose config` (with a `.env` present) | renders, no error |
| Behavior / runtime | start backend, hit `/api/health`, exercise the flow (below) | expected JSON / file |

## Setup for runtime checks

```bash
source .venv/bin/activate
# local dev paths so it writes under the repo, not /data and /music
export APP_DATA_DIR=./data MUSIC_LIBRARY_PATH=./music TOOLS_VENV=./data/toolsvenv
uvicorn backend.app.main:app --port 8080 --timeout-graceful-shutdown 3
```

Smoke test the app is alive and self-reporting correctly:

```bash
curl -s localhost:8080/api/health | python -m json.tool
# expect: app=ok, music_writable=true, providers=[…], navidrome_ok=true|false|null
```

## Per-area checklists

### Download path (`downloads/`, `providers/`, `runner.py`, `worker.py`)
The real test is an end-to-end download:
1. Backend running with the tools venv populated (`spotdl`, `yt-dlp` installed).
2. `GET /api/search?kind=song&query=...` → pick a hit.
3. `POST /api/downloads` with the provider + quality + track → returns job id(s).
4. Watch `GET /api/events` (SSE) or `GET /api/jobs` → status goes `queued → running → done`.
5. Confirm a single, tagged audio file appeared in `MUSIC_LIBRARY_PATH` (check with `ffprobe`).
6. If Navidrome is configured, confirm the rescan fired and the library badge flips to "owned".
- **Cancellation:** start a download, cancel it, confirm status `canceled` and **no orphan
  `yt-dlp`/`ffmpeg` process** survives (the process group must be killed — `runner.py`).
- **Crash safety:** kill the backend mid-download; on restart the job should be re-queued
  (`queue.rehydrate`), not stuck `running`.

### Metadata / library (`metadata/`, `navidrome/`)
- `GET /api/search` returns hits with cover URLs and per-source qualities.
- With Navidrome reachable, already-owned tracks carry the library badge + stored quality.
- With no Spotify creds, search still works via MusicBrainz fallback (just no artist photos).

### DB / schema (`db/`)
- Fresh DB: delete `data/mymusicdl.db`, boot, confirm tables created, no error.
- **Additive column:** boot against a DB created *before* your column to confirm `_ensure_columns`
  adds it (this is the case that silently breaks if you forget — golden rule #10).

### Credentials / settings (`security.py`, `routes_settings.py`)
- Save a (dummy) paid credential via `PUT /api/settings/...`; confirm it's stored **encrypted**
  (the `credentials.data_json` value is a Fernet token, not plaintext) and the provider flips enabled.
- Restart; confirm the credential is re-applied on boot (`_load_credentials`).
- Set a different `APP_SECRET` and confirm decryption fails loudly (expected).

### Bots (`bots/`)
- `GET /api/bots` returns status for telegram + matrix (configured / connected / error).
- With a real token + your ID in the allowlist: send a song name, get result buttons, pick one,
  see it queue (badged 📱 in the web Queue) and get a completion ping.
- With an empty allowlist: an outsider is denied and told their own ID. (Don't fail open.)

### Frontend (`frontend/`)
- `npm run build` is the gate (typecheck + build). For UI behavior, run `npm run dev` (proxies
  `/api` → 8080) and click through search → results → album → queue.

## Before you say "done"
- [ ] Ran the checks for every area you touched (not just imports).
- [ ] No golden rule (see [CLAUDE.md](../CLAUDE.md)) was broken.
- [ ] No secret/infra value leaked into a tracked file.
- [ ] Lint/format and the relevant build are green.
