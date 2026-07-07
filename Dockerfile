# syntax=docker/dockerfile:1

# ───────────────────────── Stage 1: build the SPA ─────────────────────────
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build                         # → /app/frontend/dist

# ───────────────────────── Stage 2: python deps ──────────────────────────
FROM python:3.12-slim AS backend-deps
WORKDIR /app
COPY pyproject.toml ./
COPY backend/ ./backend/
RUN pip install --no-cache-dir --prefix=/install .

# ───────────────────────── Stage 3: runtime ──────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    APP_DATA_DIR=/data \
    MUSIC_LIBRARY_PATH=/music \
    TOOLS_VENV=/data/toolsvenv \
    PORT=8080

# ffmpeg: required by spotdl/yt-dlp for audio extraction/transcoding.
# tini: reaps the download subprocesses cleanly. curl: container healthcheck.
# sqlite3: consistent DB backups via scripts/backup_db.sh (`sqlite3 .backup`).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg tini ca-certificates curl sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# deno: a JS runtime yt-dlp/spotdl need to solve YouTube's JS challenges (signature / n-param).
# Without it, some YouTube(-Music) downloads fail. Pulled from the official multi-arch binary image.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

COPY --from=backend-deps /install /usr/local

WORKDIR /app
COPY backend/ ./backend/
COPY alembic/ ./alembic/
COPY alembic.ini pyproject.toml ./
COPY scripts/ ./scripts/
COPY --from=frontend /app/frontend/dist ./static
RUN chmod +x scripts/*.sh

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/api/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/scripts/entrypoint.sh"]
