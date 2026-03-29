#!/usr/bin/env bash
# Gracefully restart crypto-trader daemon with position recovery verification
set -euo pipefail

CONFIG="${1:-config/daemon.toml}"
ARTIFACTS_DIR="artifacts"
CHECKPOINT="$ARTIFACTS_DIR/runtime-checkpoint.json"
HEARTBEAT="$ARTIFACTS_DIR/daemon-heartbeat.json"
LOG="$ARTIFACTS_DIR/daemon.log"
SYSTEMD_UNIT="${CT_SYSTEMD_UNIT:-crypto-trader.service}"
SYSTEMD_MANAGED_CONFIG="${CT_SYSTEMD_CONFIG:-config/daemon.toml}"

find_matching_daemon_pids() {
    python3 - "$CONFIG" <<'PY'
import subprocess
import sys

config = sys.argv[1]
ps = subprocess.run(
    ["ps", "-eo", "pid=,args="],
    check=True,
    capture_output=True,
    text=True,
)
for raw in ps.stdout.splitlines():
    raw = raw.strip()
    if not raw:
        continue
    pid_text, _, args = raw.partition(" ")
    if not pid_text.isdigit():
        continue
    if "run-multi" not in args or f"--config {config}" not in args:
        continue
    print(pid_text)
PY
}

read_systemd_status() {
    systemctl --user show "$SYSTEMD_UNIT" -p LoadState -p ActiveState -p MainPID --value 2>/dev/null || true
}

heartbeat_field() {
    python3 - "$HEARTBEAT" "$1" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
field = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
value = payload.get(field, "")
print("" if value is None else value)
PY
}

stop_pids() {
    local pids="${1:-}"
    if [ -z "$pids" ]; then
        return 0
    fi
    for old_pid in $pids; do
        kill -TERM "$old_pid" 2>/dev/null || true
    done
    for i in $(seq 1 30); do
        local still_running=""
        for old_pid in $pids; do
            if kill -0 "$old_pid" 2>/dev/null; then
                still_running="$still_running $old_pid"
            fi
        done
        if [ -z "$still_running" ]; then
            echo "  All selected daemons stopped after ${i}s"
            return 0
        fi
        sleep 1
    done
    for old_pid in $pids; do
        if kill -0 "$old_pid" 2>/dev/null; then
            echo "  Force killing PID=$old_pid"
            kill -9 "$old_pid" 2>/dev/null || true
        fi
    done
}

systemd_manages_config() {
    if [ "$CONFIG" != "$SYSTEMD_MANAGED_CONFIG" ]; then
        return 1
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        return 1
    fi
    local status
    status="$(read_systemd_status)"
    local load_state main_pid
    load_state="$(printf '%s\n' "$status" | sed -n '1p')"
    main_pid="$(printf '%s\n' "$status" | sed -n '3p')"
    if [ -z "$load_state" ] || [ "$load_state" = "not-found" ]; then
        return 1
    fi
    SYSTEMD_MAIN_PID="$main_pid"
    return 0
}

echo "=== Crypto Trader Daemon Restart ==="
echo "Config: $CONFIG"
echo ""

USE_SYSTEMD_RESTART=0
SYSTEMD_MAIN_PID=""
if systemd_manages_config; then
    USE_SYSTEMD_RESTART=1
fi
PREVIOUS_HEARTBEAT_TIMESTAMP="$(heartbeat_field last_heartbeat)"

if [ "$USE_SYSTEMD_RESTART" = "1" ]; then
    MATCHING_PIDS="$(find_matching_daemon_pids)"
    STRAY_PIDS=""
    if [ -n "$MATCHING_PIDS" ]; then
        for old_pid in $MATCHING_PIDS; do
            if [ -n "$SYSTEMD_MAIN_PID" ] && [ "$SYSTEMD_MAIN_PID" != "0" ] && [ "$old_pid" = "$SYSTEMD_MAIN_PID" ]; then
                continue
            fi
            STRAY_PIDS="$STRAY_PIDS $old_pid"
        done
    fi
    if [ -n "$STRAY_PIDS" ]; then
        echo "[1/5] Stopping stray daemon PIDs before systemctl restart: $(echo "$STRAY_PIDS" | xargs)"
        stop_pids "$STRAY_PIDS"
    else
        echo "[1/5] No stray daemon found before systemctl restart"
    fi
    echo "[1/5] Restarting systemd unit via systemctl: $SYSTEMD_UNIT"
    systemctl --user restart "$SYSTEMD_UNIT"
else
    # 1. Find and stop existing daemon
    MATCHING_PIDS="$(find_matching_daemon_pids)"
    if [ -n "$MATCHING_PIDS" ]; then
        echo "[1/5] Stopping existing daemon PIDs: $(echo "$MATCHING_PIDS" | tr '\n' ' ' | xargs)"
        stop_pids "$MATCHING_PIDS"
    else
        echo "[1/5] No running daemon found for config=$CONFIG"
    fi
fi

# 2. Verify checkpoint exists
echo ""
POSITIONS="0"
if [ -f "$CHECKPOINT" ]; then
    WALLET_COUNT=$(python3 -c "import json; d=json.load(open('$CHECKPOINT')); print(len(d.get('wallet_states',{})))" 2>/dev/null || echo "0")
    POSITIONS=$(python3 -c "
import json
d = json.load(open('$CHECKPOINT'))
total = sum(len(w.get('positions', {})) for w in d.get('wallet_states', {}).values())
print(total)
" 2>/dev/null || echo "0")
    echo "[2/5] Checkpoint found: $WALLET_COUNT wallets, $POSITIONS open positions to restore"
else
    echo "[2/5] WARNING: No checkpoint found — daemon will start fresh"
fi

# 3. Start daemon
echo ""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NEW_PID=""
if [ "$USE_SYSTEMD_RESTART" = "1" ]; then
    echo "[3/5] systemctl handled daemon start"
else
    echo "[3/5] Starting daemon..."
    VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
    if [ ! -x "$VENV_PYTHON" ]; then
        VENV_PYTHON=python3
    fi
    export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
    nohup "$VENV_PYTHON" -m crypto_trader.cli run-multi --config "$CONFIG" >> "$LOG" 2>&1 &
    NEW_PID=$!
    echo "  New PID=$NEW_PID"
fi

# 4. Wait for heartbeat
echo ""
echo "[4/5] Waiting for heartbeat..."
for i in $(seq 1 15); do
    sleep 2
    if [ -f "$HEARTBEAT" ]; then
        CURRENT_PID="$(heartbeat_field pid)"
        CURRENT_CONFIG="$(heartbeat_field config_path)"
        CURRENT_TIMESTAMP="$(heartbeat_field last_heartbeat)"
        if [ "$CURRENT_CONFIG" != "$CONFIG" ]; then
            continue
        fi
        if [ "$USE_SYSTEMD_RESTART" = "1" ] && [ "$CURRENT_TIMESTAMP" = "$PREVIOUS_HEARTBEAT_TIMESTAMP" ]; then
            continue
        fi
        if [ "$USE_SYSTEMD_RESTART" = "1" ]; then
            CURRENT_SYSTEMD_STATUS="$(read_systemd_status)"
            CURRENT_SYSTEMD_MAIN_PID="$(printf '%s\n' "$CURRENT_SYSTEMD_STATUS" | sed -n '3p')"
            if [ -n "$CURRENT_SYSTEMD_MAIN_PID" ] && [ "$CURRENT_SYSTEMD_MAIN_PID" != "0" ] && [ "$CURRENT_PID" != "$CURRENT_SYSTEMD_MAIN_PID" ]; then
                continue
            fi
        fi
        if [ -z "$NEW_PID" ] || [ "$CURRENT_PID" = "$NEW_PID" ]; then
            NEW_PID="$CURRENT_PID"
            echo "  Heartbeat confirmed for PID=$NEW_PID"
            break
        fi
    fi
    if [ "$i" = "15" ]; then
        echo "  WARNING: No heartbeat after 30s — check $LOG"
    fi
done

# 5. Verify position restoration from logs
echo ""
echo "[5/5] Checking position restoration..."
sleep 3
if grep -q "Restored.*positions from checkpoint" "$LOG" 2>/dev/null; then
    RESTORE_LINE=$(grep "Restored.*positions from checkpoint" "$LOG" | tail -1)
    echo "  $RESTORE_LINE"
else
    if [ "$POSITIONS" = "0" ] || [ -z "$POSITIONS" ]; then
        echo "  No positions to restore (clean start)"
    else
        echo "  WARNING: Expected position restore but not found in logs"
        echo "  Check: tail -20 $LOG"
    fi
fi

echo ""
echo "=== Restart Complete ==="
echo "  PID: ${NEW_PID:-unknown}"
echo "  Log: $LOG"
echo "  Monitor: tail -f $LOG"
