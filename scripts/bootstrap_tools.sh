#!/usr/bin/env bash
# Create / refresh the mounted tools virtualenv. Living on a host volume means in-app
# `pip install -U` upgrades persist across container recreation (Watchtower).
set -euo pipefail

TOOLS_VENV="${TOOLS_VENV:-/data/toolsvenv}"
PY_TAG="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
MARKER="${TOOLS_VENV}/.python-version"

# Rebuild if missing, or if the image's python minor changed (compiled wheels would otherwise break).
if [ ! -x "${TOOLS_VENV}/bin/python" ] || [ "$(cat "${MARKER}" 2>/dev/null || echo none)" != "${PY_TAG}" ]; then
  echo "[bootstrap] (re)creating tools venv at ${TOOLS_VENV} for python ${PY_TAG}"
  rm -rf "${TOOLS_VENV}"
  python -m venv "${TOOLS_VENV}"
  "${TOOLS_VENV}/bin/pip" install --no-cache-dir --upgrade pip
  # Free path (always) + streamrip so the Tidal/Qobuz/Deezer adapters are ready once credentials
  # are added. tiddl (optional Tidal alternative) is intentionally not installed by default.
  "${TOOLS_VENV}/bin/pip" install --no-cache-dir spotdl yt-dlp streamrip
  echo "${PY_TAG}" > "${MARKER}"
  echo "[bootstrap] done"
else
  echo "[bootstrap] tools venv present (python ${PY_TAG}) — leaving as-is"
fi
