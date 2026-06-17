# Roadmap & planned work

Future goals to **keep in mind while writing code now**, so today's changes don't paint tomorrow into
a corner. Status reflects the current scaffold. Update this file as items land.

## Current status

- ✅ End-to-end **free** download path (`spotdl` + `yt-dlp`): search → pick → queue → live progress →
  tagged file in `/music` → Navidrome rescan → "already in library" badge.
- ✅ Asyncio worker pool + SQLite job queue + SSE progress; jobs rehydrate on boot.
- ✅ Cover-forward UI (Cover Art Archive images, gradient fallback).
- ✅ Telegram + Matrix bots mirroring the web app; `origin` badging.
- ✅ Updater: PyPI version check + GitHub changelog + in-venv `pip install -U`.
- ✅ CI → GHCR image; `compose.yaml` parameterized for a public repo.
- ⏳ Paid lossless sources are **scaffolded but disabled** (no credentials).

## Planned / known future work

Keep these in view so present code stays compatible:

1. **Make paid providers actually resolve & download** (`streamrip_provider.py` is a stub).
   When Tidal/Qobuz/Deezer credentials are added, the adapters need:
   - **Native catalog search** so results carry *real* qualities (the `Provider.search()` override),
     instead of leaning on the Spotify/MusicBrainz metadata identity.
   - A **templated `streamrip` `config.toml`** generated from the stored credential (token/ARL) with
     `downloads.folder` pointed at the job's `dest_dir`, so `rip url <track>` resolves a real source
     URL rather than the Spotify metadata URL.
   - *Design implication now:* keep `TrackRef.ext_ids` and `source_url` flexible enough to carry a
     provider-native id; don't assume every track's `source_url` is a Spotify URL.

2. **Artist photos.** MusicBrainz has none, so artist images currently need Spotify credentials. If a
   keyless artist-image source is added, slot it into the metadata layer behind the same `Artwork`
   fallback. Don't hardcode Spotify as the only image source.

3. **Versioned migrations.** Today schema lives via `create_all` + `_ensure_columns`. The moment a
   change needs data migration / column rename / constraint change, switch that change to **Alembic**
   (already wired to the models' metadata). Keep new columns additive until then.

4. **Tool-venv / Python-minor coupling.** The mounted venv is tied to the image's Python minor;
   `bootstrap_tools.sh` rebuilds it when the minor changes (via a `.python-version` marker). If you
   bump the base image's Python, confirm that path still triggers a clean rebuild.

5. **`tiddl` as an alternate Tidal backend** is intentionally not installed by default. If enabled,
   register `TiddlProvider` in the registry (the commented line is there) and add it to
   `bootstrap_tools.sh`.

6. **GHCR package visibility.** The repo is public but the container package must be flipped to public
   via the GitHub UI (or pulled with a `read:packages` token). See [DEPLOY](DEPLOY.md). Not a code
   task, but it's the current blocker for a no-login `docker pull`.

## Non-goals (don't build these without asking)

- A login/identity system in the app (auth is delegated to Cloudflare Access).
- Redis/Celery or any external queue (family scale doesn't warrant it).
- Whole-album downloads as a single blob (violates the core product rule).
- Baking downloader CLIs into the image / `pyproject.toml` (breaks persistent self-update).
