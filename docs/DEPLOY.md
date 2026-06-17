# Deploy

Three ways to run it: **from the GHCR image** (normal), **build locally** (no registry needed), or
**bare metal / dev** (no Docker). Plus the GHCR package-visibility gotcha that currently blocks a
no-login pull.

## TL;DR (homelab, from the registry)

```bash
# 1. one folder for the stack
mkdir -p /opt/stacks/mymusicdl && cd /opt/stacks/mymusicdl
# 2. drop compose.yaml + create .env (see "Configuration" below)
# 3. (if the GHCR package is still PRIVATE) authenticate the host once:
echo "$GHCR_PAT" | docker login ghcr.io -u borborborja --password-stdin   # PAT needs read:packages
# 4. up
docker compose up -d && docker compose logs -f mymusicdl
```

Image: `ghcr.io/borborborja/mymusicdl:latest`, built and pushed by GitHub Actions
(`.github/workflows/docker-image.yml`) on every push to `main`. **Watchtower** (label in
`compose.yaml`) auto-updates the container when a new `:latest` is published.

## Configuration (`.env`)

`compose.yaml` is generic; **every site-specific value comes from `.env`** (golden rule #6). Copy
`.env.example` and fill it. The variables that matter for deploy:

| Var | What | Example |
|---|---|---|
| `APP_SECRET` | **Required.** Encrypts stored credentials. Long random string. | `openssl rand -hex 32` |
| `NAVIDROME_URL/USER/PASSWORD` | Subsonic API the app calls for rescans + library matching | `http://navidrome:4533` |
| `PUBLIC_HOSTNAME` | Hostname your tunnel/proxy exposes | `music.example.com` |
| `EDGE_NETWORK` | Existing external Docker net for the tunnel/proxy | `cloudflare-net` |
| `INTERNAL_NETWORK` | Existing external Docker net Navidrome sits on | `internal` |
| `MUSIC_VOLUME` | **The same named volume Navidrome mounts** for its library | `music` |
| `DATA_DIR` | Host path for SQLite + the tools venv | `./data` |
| `LAN_BIND_IP` | Host IP to bind the UI on (loopback by default) | `127.0.0.1` |
| `SPOTIFY_CLIENT_ID/SECRET` | Optional — better catalog + artist photos | — |
| `DOWNLOAD_CONCURRENCY` | Parallel downloads | `2` |
| `TELEGRAM_*` / `MATRIX_*` | Optional bot config (or set in the Settings page) | — |

> The `MUSIC_VOLUME` **must** resolve to the same storage Navidrome reads (in the owner's homelab an
> `rclone`-backed named volume defined in the Navidrome stack), or downloads won't appear in
> Navidrome. The volume must already exist (`external: true` in compose) — start Navidrome first.

## Option B — build locally (no registry, no login)

If you don't want to use GHCR at all, build the image on the host:

```bash
# edit compose.yaml: comment out `image:`, uncomment `build: .`
docker compose up -d --build
```

This needs the source on the host. The multi-stage `Dockerfile` builds the SPA (node:22-alpine) and
the Python runtime (python:3.12-slim + ffmpeg/tini/curl) — no extra setup.

## Option C — bare metal / development

See [the run instructions in CLAUDE.md](../CLAUDE.md#how-to-run-it-locally). Backend with uvicorn +
a local tools venv, frontend with `npm run dev`. Use `APP_DATA_DIR=./data MUSIC_LIBRARY_PATH=./music`
so it writes under the repo.

## ⚠️ GHCR package visibility (the "unauthorized" pull)

**Making the GitHub repo public does NOT make the container package public** — package visibility is
independent. While the package is private, `docker pull` fails with `unauthorized` unless the host is
logged in. Two fixes:

- **Make the package public** (no login needed afterwards): GitHub → your profile → **Packages** →
  `mymusicdl` → **Package settings** → **Danger Zone → Change visibility → Public**.
  Direct URL: `https://github.com/users/borborborja/packages/container/mymusicdl/settings`.
  (The *Connect repository* button does **not** do this.)
- **Keep it private + log in:** `docker login ghcr.io -u borborborja` with a PAT that has
  `read:packages`. Watchtower then also needs that auth (it reads the host's `~/.docker/config.json`)
  to pull updates.

Verify a package is public (returns HTTP 200 anonymously):

```bash
T=$(curl -s "https://ghcr.io/token?scope=repository:borborborja/mymusicdl:pull" | python3 -c "import sys,json;print(json.load(sys.stdin).get('token',''))")
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $T" https://ghcr.io/v2/borborborja/mymusicdl/manifests/latest
# 200 = public · 401/403 = still private
```

## First-boot expectations

On first start the container will: create `DATA_DIR/mymusicdl.db` and its tables, build the tools
venv at `$TOOLS_VENV` and `pip install spotdl yt-dlp streamrip` into it (this takes a bit — watch the
`[bootstrap]` logs), then serve on `:8080`. Health: `GET /api/health` reports app status, whether
Navidrome is reachable, and whether `/music` is writable. The container `HEALTHCHECK` curls that
endpoint.

## Homelab notes

The owner's stack follows its homelab conventions — compose under `/opt/stacks/mymusicdl/`, data
under `/opt/dades/mymusicdl/`, two external Docker networks (edge + internal), Dockflare + Watchtower
labels, a fixed LAN bind IP, and the shared `rclone` music volume that the Navidrome stack defines.
**All of those real values (hostname, IP, network names, volume name) live only in the on-server
`.env`, never in this repo** — `compose.yaml` reads them from there. Start the Navidrome stack first
so the shared music volume exists before this one mounts it.
