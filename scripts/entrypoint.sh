#!/usr/bin/env bash
set -euo pipefail

APP_DATA_DIR="${APP_DATA_DIR:-/data}"
mkdir -p "${APP_DATA_DIR}"

# Ensure the downloader tools exist in the mounted venv (idempotent).
/app/scripts/bootstrap_tools.sh

# Tables are created from the ORM metadata on startup (see lifespan/init_db). Alembic is available
# for versioned migrations later: `alembic upgrade head`.
exec uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
