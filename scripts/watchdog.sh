#!/usr/bin/env bash
# Cron/systemd watchdog: reconcile daemon liveness using heartbeat + systemd state
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${1:-config/daemon.toml}"
SYSTEMD_UNIT="${CT_SYSTEMD_UNIT:-crypto-trader.service}"
HEARTBEAT_MAX_AGE_SECONDS="${CT_HEARTBEAT_MAX_AGE_SECONDS:-240}"

cd "$PROJECT_DIR"

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
    VENV_PYTHON=python3
fi

export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV_PYTHON" -m crypto_trader.operator.watchdog \
    --project-dir "$PROJECT_DIR" \
    --config "$CONFIG" \
    --systemd-unit "$SYSTEMD_UNIT" \
    --heartbeat-max-age-seconds "$HEARTBEAT_MAX_AGE_SECONDS"
