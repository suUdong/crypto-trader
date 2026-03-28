#!/usr/bin/env bash
# Cron watchdog: restart crypto-trader daemon if not running
# Usage: */5 * * * * /home/wdsr88/workspace/crypto-trader/scripts/watchdog.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${1:-config/daemon.toml}"
LOG="$PROJECT_DIR/artifacts/daemon.log"
WATCHDOG_LOG="$PROJECT_DIR/artifacts/watchdog.log"

cd "$PROJECT_DIR"

is_daemon_running() {
    pgrep -f "crypto_trader.cli run-multi --config $CONFIG" >/dev/null 2>&1
}

log_msg() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$WATCHDOG_LOG"
}

if is_daemon_running; then
    exit 0
fi

log_msg "WARN: Daemon not running. Restarting via restart_daemon.sh..."
bash "$PROJECT_DIR/scripts/restart_daemon.sh" "$CONFIG" >> "$WATCHDOG_LOG" 2>&1
log_msg "INFO: Restart script completed (exit=$?)"
