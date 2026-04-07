#!/usr/bin/env bash
# Nightly backup for crypto-trader (SQLite snapshot + JSONL rotation).
# Run by crypto-trader-backup.service (oneshot timer @ 19:00 UTC = 04:00 KST).
set -euo pipefail

ARTIFACTS="${CT_ARTIFACTS_ROOT:-/var/lib/crypto-trader/artifacts}"
BACKUP_DIR="/var/lib/crypto-trader/backups"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
RETENTION_DAYS="${CT_BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

shopt -s nullglob
for db in "$ARTIFACTS"/*.db; do
    name="$(basename "$db" .db)"
    out="$BACKUP_DIR/${name}.${TS}.db"
    sqlite3 "$db" ".backup '$out'"
    gzip -f "$out"
done

for jsonl in "$ARTIFACTS"/*.jsonl; do
    name="$(basename "$jsonl" .jsonl)"
    out="$BACKUP_DIR/${name}.${TS}.jsonl.gz"
    gzip -c "$jsonl" > "$out"
done
shopt -u nullglob

find "$BACKUP_DIR" -type f -name '*.gz' -mtime +"$RETENTION_DAYS" -delete

echo "[backup] complete @ $TS — kept ${RETENTION_DAYS}d"
