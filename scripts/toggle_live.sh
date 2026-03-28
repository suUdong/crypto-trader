#!/usr/bin/env bash
# Toggle paper_trading mode and restart daemon
# Usage:
#   ./scripts/toggle_live.sh live    # switch to live trading
#   ./scripts/toggle_live.sh paper   # switch back to paper trading
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${2:-config/daemon.toml}"
CONFIG_PATH="$PROJECT_DIR/$CONFIG"
MODE="${1:-}"

if [[ "$MODE" != "live" && "$MODE" != "paper" ]]; then
    echo "Usage: $0 <live|paper> [config-file]"
    echo ""
    echo "  live   — set paper_trading = false (REAL MONEY)"
    echo "  paper  — set paper_trading = true  (safe mode)"
    exit 1
fi

if [[ "$MODE" == "live" ]]; then
    TARGET="false"
    echo "⚠️  SWITCHING TO LIVE TRADING (real money) ⚠️"
    echo ""
    # Safety: verify credentials are set
    if [[ -z "${CT_UPBIT_ACCESS_KEY:-}" || -z "${CT_UPBIT_SECRET_KEY:-}" ]]; then
        echo "ERROR: Upbit API credentials not set."
        echo "  export CT_UPBIT_ACCESS_KEY='your-key'"
        echo "  export CT_UPBIT_SECRET_KEY='your-secret'"
        exit 1
    fi
    echo "Credentials: OK"
    echo ""
    read -r -p "Type YES to confirm live trading: " CONFIRM
    if [[ "$CONFIRM" != "YES" ]]; then
        echo "Aborted."
        exit 1
    fi
else
    TARGET="true"
    echo "Switching to paper trading (safe mode)"
fi

# Toggle the flag in config
sed -i "s/^paper_trading = .*/paper_trading = $TARGET/" "$CONFIG_PATH"
echo "Config updated: paper_trading = $TARGET"

# Restart daemon
echo ""
bash "$PROJECT_DIR/scripts/restart_daemon.sh" "$CONFIG"
echo ""
echo "Done. Mode: $MODE"
