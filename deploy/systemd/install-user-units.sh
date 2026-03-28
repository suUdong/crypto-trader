#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$UNIT_DIR"
install -m 0644 "$PROJECT_DIR/deploy/systemd/crypto-trader.service" \
    "$UNIT_DIR/crypto-trader.service"
install -m 0644 "$PROJECT_DIR/deploy/systemd/crypto-trader-watchdog.service" \
    "$UNIT_DIR/crypto-trader-watchdog.service"
install -m 0644 "$PROJECT_DIR/deploy/systemd/crypto-trader-watchdog.timer" \
    "$UNIT_DIR/crypto-trader-watchdog.timer"

systemctl --user daemon-reload
systemctl --user enable --now crypto-trader.service
systemctl --user enable --now crypto-trader-watchdog.timer
