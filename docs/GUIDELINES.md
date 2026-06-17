# Coding guidelines & recipes

Style rules, then **copy-paste recipes** for the changes you're most likely to make. Following the
recipe keeps a change small and prevents the classic "it imports but the feature is half-wired" bug.

## Style

- **Python 3.12**, `from __future__ import annotations` at the top of every module, full type hints.
- **Line length 100.** Format with `black`, lint with `ruff` (both configured in `pyproject.toml`).
- **Module docstring explaining *why*** the module exists (look at any existing module — match that
  voice and density). Comments explain intent, not mechanics.
- **Routers stay thin.** `api/` validates input and calls a subsystem; logic lives in
  `downloads/`, `providers/`, `metadata/`, `navidrome/`, `library/`, `updater/`, `bots/`.
- **Singletons via `app.state`.** Long-lived objects are built in `lifespan` and read with
  `request.app.state.<name>`. Don't construct per-request HTTP clients/pools for these.
- **Async all the way down.** DB access uses the async session (`SessionLocal` / `get_session`).
  Never block the event loop (no `requests`, no sync `time.sleep`, no blocking file IO in hot paths).
- **Frontend:** React function components + hooks, Tailwind utility classes, TypeScript strict.
  API calls go through `frontend/src/lib/api.ts`; shared types in `frontend/src/lib/types.ts`.
- **No new heavy dependencies** without a reason. The project is intentionally lean (raw `httpx` over
  SDKs, asyncio over Celery). Match that philosophy.

## Recipe: add a download provider

1. Create `backend/app/providers/<name>_provider.py` subclassing `Provider` (see `base.py`).
   Set `id`, `label`, `requires_credentials`. Implement `get_qualities()` and `download()` (an async
   generator — drive the CLI through `downloads/runner.py::stream_subprocess` with a `parse` callback
   that turns CLI output lines into `ProgressEvent`s). Paid sources also override `search()`.
2. Register it in `backend/app/providers/registry.py::build_registry()`. If paid, gate it on a
   credential (see how Tidal/Qobuz/Deezer pass `creds[...]`).
3. If it needs a new CLI tool, add it to `scripts/bootstrap_tools.sh` (the mounted venv) — **not** to
   `pyproject.toml` (golden rule #3).
4. Reuse the `Quality` tiers as-is. Don't invent new quality numbers.
5. Verify: `python -c "from backend.app.providers.registry import build_registry; from backend.app.config import get_settings; print([p.id for p in build_registry(get_settings()).all()])"`.

## Recipe: add an API route

1. Add the handler to the relevant `backend/app/api/routes_*.py` (or a new file). Keep it thin; call
   into a subsystem. Read singletons via `request.app.state.*` or the typed deps in `deps.py`.
2. If it's a new module, include its router in `backend/app/main.py::create_app()` under `/api`.
3. Define request/response shape as a Pydantic DTO in `backend/app/schemas/`.
4. Add the client call in `frontend/src/lib/api.ts` and any types in `lib/types.ts`.
5. Verify: import check + `curl` the endpoint against a running backend (see VERIFICATION).

## Recipe: add a config / env var

1. Add the field to `backend/app/config.py::Settings` with a safe default and a comment.
2. If it must reach the container, surface it in `compose.yaml` (`environment:` or via `env_file`)
   and document it in `.env.example` with a placeholder. **Never** put a real value in a tracked file.
3. If it's site-specific (hostname, network, path), follow the existing pattern: a generic default in
   compose + the real value in the user's `.env` (golden rule #6).

## Recipe: add / change a DB column

- **New table:** add the model in `db/models.py`; `create_all` creates it on next boot. Done.
- **New column on an existing table:** add the model field **and** an entry in `_ADDED_COLUMNS` in
  `backend/app/db/engine.py` (e.g. `"jobs": {"newcol": "VARCHAR(16) DEFAULT '...'"}`). Without this,
  installs with an existing DB won't get the column — `create_all` never ALTERs (golden rule #10).
- **Data migration / rename / constraint change:** use Alembic — `alembic revision --autogenerate -m
  "..."`, review the generated script, commit it. Don't hand-edit the SQLite file.
- Remember `library_items` has `UNIQUE(artist, title, album, quality_tier)` — preserve the intent
  (same track at a better tier = new row) if you touch it.

## Recipe: touch the frontend

1. Pages in `frontend/src/pages/`, reusable bits in `components/`, data layer in `lib/`.
2. Live job updates come from the SSE hook `lib/useEvents.ts` + the store in `store/jobs.ts` — reuse
   them rather than polling.
3. Always finish with `cd frontend && npm run build` (it typechecks via `tsc -b` then builds). A
   green build is the bar; a red `tsc` means the change is not done.

## Recipe: touch the bots

- Shared logic is in `bots/core.py` (`BotCore`); per-platform transport in `telegram.py` / `matrix.py`;
  config + lifecycle + completion routing in `manager.py`.
- Both bots **must** enqueue via `downloads/service.py::enqueue_tracks(..., origin=…)` so jobs are
  tagged and the web UI badges them. Don't write a second enqueue path.
- Respect the allowlist semantics (empty = deny all; tell an unknown user their own ID).

## Things that bite (learned the hard way)

- **`uvicorn --reload` hangs on shutdown** because the SSE `/api/events` stream never closes. Always
  run dev with `--timeout-graceful-shutdown 3`.
- **`spotdl`/`yt-dlp` not found at runtime** means the tools venv isn't on `PATH` — that's handled by
  `runner.py::tool_env()`; don't shell out to these tools without it.
- **A changed `APP_SECRET` "loses" all credentials** — it can't decrypt the old Fernet blobs. Expected.
- **Don't run destructive git (force-push, history rewrite), deploy, or flip repo/package visibility
  unless explicitly asked.** These are outward-facing and hard to undo.
