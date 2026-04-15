#!/usr/bin/env bash
# scripts/backup.sh — nightly backup for crypto-trader
# Called by: /etc/systemd/system/crypto-trader-backup.service
# Runs as:   crypto user
# Output:    stdout → journalctl (SyslogIdentifier=crypto-trader-backup)
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
ARTIFACTS_ROOT="${CT_ARTIFACTS_ROOT:-/var/lib/crypto-trader/artifacts}"
BACKUP_DIR="/var/lib/crypto-trader/backups"
RETAIN_DAYS=7

DB_SRC="${ARTIFACTS_ROOT}/paper-trades.db"
JSONL_SRC="${ARTIFACTS_ROOT}/paper-trades.jsonl"

TIMESTAMP="$(date -u +%Y-%m-%dT%H%M%S)"
DB_DST="${BACKUP_DIR}/paper-trades-${TIMESTAMP}.db"
JSONL_DST="${BACKUP_DIR}/paper-trades-${TIMESTAMP}.jsonl"

# ── Helpers ───────────────────────────────────────────────────────────────────
log() { echo "[backup] $(date -u +%Y-%m-%dT%H:%M:%SZ)  $*"; }

# ── Setup ─────────────────────────────────────────────────────────────────────
mkdir -p "${BACKUP_DIR}"
log "backup dir: ${BACKUP_DIR}"
log "artifacts root: ${ARTIFACTS_ROOT}"

# ── SQLite backup ─────────────────────────────────────────────────────────────
if [[ ! -f "${DB_SRC}" ]]; then
    log "WARNING: DB not found (${DB_SRC}), skipping"
else
    sqlite3 "${DB_SRC}" ".backup '${DB_DST}'"
    log "DB backup OK: ${DB_DST}"
fi

# ── JSONL backup ──────────────────────────────────────────────────────────────
if [[ ! -f "${JSONL_SRC}" ]]; then
    log "WARNING: JSONL not found (${JSONL_SRC}), skipping"
else
    cp "${JSONL_SRC}" "${JSONL_DST}"
    log "JSONL backup OK: ${JSONL_DST}"
fi

# ── Prune old backups ─────────────────────────────────────────────────────────
PRUNED=0
while IFS= read -r -d '' old_file; do
    rm -f "${old_file}"
    log "pruned: ${old_file}"
    PRUNED=$(( PRUNED + 1 ))
done < <(find "${BACKUP_DIR}" -maxdepth 1 \
    \( -name 'paper-trades-*.db' -o -name 'paper-trades-*.jsonl' \) \
    -mtime "+${RETAIN_DAYS}" -print0)

log "pruned ${PRUNED} old backup file(s)"
log "done"
