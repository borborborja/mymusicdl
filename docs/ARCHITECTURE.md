# Architecture

How the pieces fit, how a download flows end to end, and the invariants that keep it correct.
Read this before changing anything in `downloads/`, `providers/`, `db/`, or `main.py`.

## Big picture

```
React SPA  ──/api──▶  FastAPI (uvicorn, single process)
                        │
   app.state singletons (built once in lifespan, backend/app/main.py):
        ProgressBroker ──── in-process pub/sub ──▶ SSE (/api/events) ──▶ browser
        ProviderRegistry ── spotdl · yt-dlp · (streamrip: tidal/qobuz/deezer)
        DownloadQueue ───── asyncio.Queue of job ids (durable mirror in SQLite `jobs`)
        WorkerPool ──────── N coroutines; each claims a job, runs a provider download
        SearchAggregator ── metadata search + Navidrome "already-owned" matching
        Navidrome client ── Subsonic API (search3 / getSong / startScan)
        Updater ─────────── PyPI version checks + GitHub changelog + in-venv pip upgrades
        BotManager ──────── Telegram + Matrix adapters (optional)
                        │
                  SQLite (async SQLAlchemy 2.0)  +  /music volume (shared with Navidrome)
```

There is **no Redis, no Celery, no external broker**. Concurrency is a pool of asyncio coroutines;
durability is the `jobs` table (re-hydrated on boot). This is deliberate — see
[CONVENTIONS](CONVENTIONS.md).

## App startup (`backend/app/main.py`)

`create_app()` builds the FastAPI app and registers routers under `/api`. The `lifespan`
async-context-manager does the real wiring, **in this order**:

1. `setup_logging()`, load `Settings` (`get_settings()`, cached).
2. `init_db()` — `Base.metadata.create_all` (creates missing tables) then `_ensure_columns`
   (idempotent additive column migration; `create_all` never ALTERs existing tables).
3. Construct the singletons (broker, registry, navidrome, queue, aggregator, worker, updater, bots)
   and stash them on `app.state.*`.
4. `_load_credentials()` — decrypt enabled `credentials` rows and apply them to the registry so paid
   providers survive a restart (rows whose provider starts with `bot:` are skipped — they belong to
   the BotManager).
5. `queue.rehydrate(session)` — re-enqueue jobs left `queued`/`running` from a previous run.
6. Start `worker`, `updater`, `bots`.

On shutdown it stops bots → worker → updater and closes the Navidrome client.

The built SPA is served from `/static` (present only in the Docker image). A catch-all route returns
`index.html` for client-side routing; anything under `/api` that misses returns a real 404.

**Implication for agents:** anything that needs to live for the whole process and be shared (a
client, a pool, a cache) is created in `lifespan` and read via `request.app.state.<name>` in routes.
Don't create per-request clients for these.

## The provider abstraction (`backend/app/providers/`)

This is the extensibility core. `base.py` defines:

- `Quality(IntEnum)` — tiers **0..4** (`MP3_128, MP3_320, FLAC_16, HIRES_96, HIRES_192`). **Mirrors
  streamrip's tiers 1:1.** Stored as `quality_tier` in the DB. Never renumber.
- `TrackRef` (frozen dataclass) — provider-agnostic identity of one track. Serialized into
  `jobs.track_json`; `to_dict`/`from_dict` must stay backward-compatible.
- `QualityOption`, `SearchHit`, `ProgressEvent` — DTOs passed around the download path.
- `Provider(ABC)` — `enabled` (gated by `requires_credentials` + presence of creds),
  `search()` (paid providers override with native catalog; free return `[]`), `get_qualities()`,
  and `download()` (an **async generator** yielding `ProgressEvent` while writing one audio file).

`registry.py` builds the providers from `Settings` and exposes only the enabled ones. Paid providers
are constructed with whatever credentials exist at boot; `set_credentials()` flips one on at runtime
(no restart). Free providers (`spotdl`, `yt-dlp`) are always enabled.

## The download lifecycle (the most important flow)

```
HTTP POST /api/downloads        bot "download this"
        │                              │
        └──────────┬───────────────────┘
                   ▼
   downloads/service.py :: enqueue_tracks(items, origin=…)
     • validates each provider is known + enabled (else EnqueueError, nothing queued)
     • writes ONE `jobs` row per track (status=queued, origin=web|telegram|matrix,
       dest_dir=MUSIC_LIBRARY_PATH, batch_id set when >1 item)
     • queue.put(job_id) for each
                   ▼
   downloads/worker.py :: WorkerPool._process(job_id)   (one of N coroutines)
     • re-load job; skip if not still `queued`
     • snapshot dest dir contents (to detect the new file later)
     • status→running; provider.download(track, quality, dest_dir, job_id) async-iterates:
         each ProgressEvent → update job.stage/pct (throttled) → broker.publish → SSE
       (the consume() runs as a child task so a single job can be cancelled)
     • on success: _pick_new_audio() picks the largest new audio file → result_path
                   status→done, pct=100
                   library/tracker.record_download(...) → writes library_items + Navidrome startScan
     • on SubprocessError/Exception: status→error with the output tail
     • on cancel: status→canceled and the subprocess *group* is SIGTERM/SIGKILLed (runner.py)
     • on pool shutdown mid-job: job left `queued` so the next boot resumes it
```

`runner.py` is the subprocess glue: `create_subprocess_exec` with `start_new_session=True` (own
process group → clean kill), reads combined stdout/stderr line by line, and turns each line into a
`ProgressEvent` via a provider-supplied `parse` callback. A non-zero exit raises `SubprocessError`
carrying the last ~40 lines for diagnostics. `tool_env()` puts the tools-venv `bin/` first on `PATH`
so the venv's `spotdl`/`yt-dlp` and the system `ffmpeg` are both found.

**Progress → UI:** `ProgressBroker` is in-process pub/sub. The worker publishes `{type: "job", job:
…}` payloads; `routes_events.py` holds one SSE stream per browser and fans them out. The BotManager
also subscribes, to ping the originating chat when a job reaches a terminal state.

## Metadata & library matching (`metadata/`, `navidrome/`)

`SearchAggregator` resolves a canonical identity via the active metadata source (Spotify when
configured, else MusicBrainz — keyless) and attaches each enabled provider's deliverable qualities.
In parallel, `navidrome/matcher.py` queries Subsonic (`search3` + `getSong`, reading `bitRate` +
`suffix`) to decide whether a track is already in the library and at what quality — that drives the
"in library @ MP3 320 / re-download to better" badge. Album/song cover art comes from the Cover Art
Archive (keyless); artist photos need Spotify credentials (MusicBrainz has none).

## Persistence (`db/models.py`)

Five tables: `library_items`, `jobs`, `tools`, `settings`, `credentials`. Notable:

- `jobs` is the durable queue. `kind` ∈ `download|tool_update|rescan|version_check`; `status` ∈
  `queued|running|done|error|canceled`; `origin` ∈ `web|telegram|matrix`; `batch_id` groups a
  multi-track request; `track_json` is the serialized `TrackRef`.
- `credentials.provider` is the PK; for bots it's `bot:telegram` / `bot:matrix`. `data_json` is a
  **Fernet-encrypted** blob (`security.py`, key derived from `APP_SECRET`).
- `library_items` has `UNIQUE(artist, title, album, quality_tier)` so the same track at a better tier
  is a distinct row (enables "upgrade to lossless").

Schema changes: new table → just add the model (create_all picks it up). New column on an existing
table → add to `_ADDED_COLUMNS` in `engine.py`. Anything involving data migration → use Alembic
(`alembic/` is wired to the models' metadata; run `alembic revision --autogenerate`).

## Bots (`bots/`)

`BotManager` owns the adapters and resolves each bot's config with precedence **env var > encrypted
DB row** (`bot:telegram`/`bot:matrix`). It hot-reloads on config change (`reload(name)`) without an
app restart, and subscribes to the broker to forward terminal job events to the chat that queued
them. Adapters are raw `httpx` (Telegram long-poll `getUpdates` + inline buttons; Matrix `/sync`,
non-E2E, auto-joins invites). Access is an **allowlist** (`_parse_int_csv` for Telegram numeric IDs,
`_parse_str_csv` for Matrix `@user:server`); empty allowlist denies all. Both queue downloads through
the same `enqueue_tracks()` as the web, tagging `origin` accordingly.
