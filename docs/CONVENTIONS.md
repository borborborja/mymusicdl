# User-designated conventions

Decisions the project owner (Borja) confirmed. These are **product/architecture choices, not
suggestions** — honor them, and if a task seems to require changing one, ask first. Each entry says
*what* and *why* so you can apply the spirit, not just the letter.

## Product

- **Free sources only, for now.** `spotdl` + `yt-dlp` are wired and enabled. Paid lossless
  (Tidal/Qobuz/Deezer via `streamrip`, plus optional `tiddl` for Tidal) ships as **adapters that stay
  disabled until credentials are added** (Settings page or env var). *Why:* the owner doesn't pay for
  these yet but wants zero-code activation later. **Turning one on must remain "add a credential".**

- **Single, well-tagged tracks — never album blobs.** The album view expands into selectable tracks;
  downloads are always per-track. *Why:* the whole reason the tool exists is clean, individually
  tagged files in Navidrome, with per-track "already owned / upgrade quality" awareness.

- **Re-download to better quality is a feature.** The library badge shows current stored quality and
  offers an upgrade when only a lossy tier exists. `library_items`'s
  `UNIQUE(artist, title, album, quality_tier)` exists for this. Don't collapse it.

## Storage & integration

- **Write directly into the volume Navidrome reads, then rescan.** The downloaded file lands in
  `MUSIC_LIBRARY_PATH` (`/music`), which **must be the same named volume the Navidrome container
  mounts** (in the owner's setup that's an `rclone`-backed named volume shared between the two
  stacks). After each download the app calls Subsonic `startScan`. *Why:* a freshly downloaded track
  must appear in Navidrome immediately, with no copy step.

- **Tools live in a mounted venv so updates persist.** `$TOOLS_VENV` (`/data/toolsvenv`) is on a host
  volume; the in-app updater runs `pip install -U` there. *Why:* upgrades must survive Watchtower
  recreating the container — they would be lost if tools were baked into the image.

## Architecture

- **No Redis / no Celery.** Jobs are SQLite rows consumed by an in-process asyncio worker pool;
  progress streams over **SSE** (not WebSocket). *Why:* family-scale load doesn't justify the
  operational weight; SSE reconnects on its own and passes cleanly through Cloudflare.

- **CLIs as subprocesses, not libraries.** The downloaders are driven via their command-line
  interface, not their Python internals. *Why:* far more stable across tool versions.

- **Minimal dependencies.** Raw `httpx` instead of vendor SDKs (Spotify, Telegram, Matrix). *Why:*
  fewer moving parts, smaller attack surface, easier upgrades. Keep new deps to a real need.

- **Auth is delegated to the edge** (Cloudflare Access via the Dockflare group). The app has no login
  of its own; `APP_SHARED_PASSWORD` is only an optional extra gate, off by default.

## Security

- **`APP_SECRET` encrypts provider + bot credentials** in the DB (Fernet). It is required and
  load-bearing; rotating it invalidates stored credentials.
- **`.env` and `data/` are never committed.** Only `.env.example` (placeholders) is tracked.
- **The public repo carries no infra specifics.** Hostnames, IPs, network names, the rclone remote,
  and family-derived naming were scrubbed from files **and git history**; `compose.yaml` reads every
  site value from `.env`. Keep it that way.

## Bots

- **Both Telegram and Matrix**, mirroring the web app over chat. Optional; configured via env **or**
  the Settings page (stored encrypted; env takes precedence; hot-reload on change).
- **Access = allowlist of IDs.** Empty allowlist = deny everyone. An unauthorised user is told their
  own ID so the admin can add it. *Why:* simplest safe model for a private family tool.
- **Matrix is non-E2E** — a dedicated unencrypted room; the bot auto-joins invites.
- **Bot-queued downloads are badged with 📱** in the web Queue (the `origin` column).

## Delivery

- **Image is published to GHCR via GitHub Actions** on push to `main`
  (`ghcr.io/borborborja/mymusicdl`), using the built-in `GITHUB_TOKEN` — no Docker Hub, no external
  secrets. *Why:* full autonomy, zero secret setup. **Watchtower** auto-updates the container on a new
  `:latest`. Note GHCR package visibility is **independent** of repo visibility (see DEPLOY).

## Conventions for *how the assistant works* with this owner

- Replies in **Spanish** (the owner writes in Spanish).
- The homelab follows its own stack conventions (compose under `/opt/stacks`, data under
  `/opt/dades`, external Docker networks, Dockflare/Watchtower labels). Those, and the real
  hostnames/IPs/network/volume names, live **only** in the owner's private on-server `.env` — never
  in this public repo.
- Don't push, deploy, or change repo/package visibility unless asked.
