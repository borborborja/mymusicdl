#!/usr/bin/env bash
# Consistent snapshot of the mymusicdl SQLite DB (library, jobs, encrypted credentials, bot state).
#
# Uses `sqlite3 .backup`, which is safe to run against a live DB (unlike `cp`, which can capture a
# half-written file). Keeps the last N snapshots. Run it from cron or a backup job; the DB is small.
#
# Usage:
#   scripts/backup_db.sh [DATA_DIR] [BACKUP_DIR] [KEEP]
# Defaults: DATA_DIR=./data  BACKUP_DIR=$DATA_DIR/backups  KEEP=14
#
# In the container the DB lives at /data/mymusicdl.db, so on the host point DATA_DIR at the mounted
# data volume, e.g.:  scripts/backup_db.sh /opt/dades/mymusicdl
set -euo pipefail

DATA_DIR="${1:-./data}"
BACKUP_DIR="${2:-${DATA_DIR}/backups}"
KEEP="${3:-14}"

DB="${DATA_DIR%/}/mymusicdl.db"
if [[ ! -f "$DB" ]]; then
  echo "backup_db: no DB at $DB" >&2
  exit 1
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "backup_db: sqlite3 not found (install it, or run inside the container)" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR%/}/mymusicdl-${STAMP}.db"

sqlite3 "$DB" ".backup '${OUT}'"
gzip -f "$OUT"
echo "backup_db: wrote ${OUT}.gz"

# Prune old snapshots, keeping the newest KEEP.
ls -1t "${BACKUP_DIR%/}"/mymusicdl-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "$old"
  echo "backup_db: pruned $old"
done

# Restore (manual):
#   gunzip -c mymusicdl-YYYYMMDD-HHMMSS.db.gz > mymusicdl.db   # with the app stopped
