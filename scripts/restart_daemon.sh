#!/usr/bin/env bash
# Gracefully restart crypto-trader daemon with position recovery verification
set -euo pipefail

CONFIG="${1:-config/daemon.toml}"
ARTIFACTS_DIR="artifacts"
CHECKPOINT="$ARTIFACTS_DIR/runtime-checkpoint.json"
HEARTBEAT="$ARTIFACTS_DIR/daemon-heartbeat.json"
LOG="$ARTIFACTS_DIR/daemon.log"

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

echo "=== Crypto Trader Daemon Restart ==="
echo "Config: $CONFIG"
echo ""

# 1. Find and stop existing daemon
MATCHING_PIDS="$(find_matching_daemon_pids)"
if [ -n "$MATCHING_PIDS" ]; then
    echo "[1/5] Stopping existing daemon PIDs: $(echo "$MATCHING_PIDS" | tr '\n' ' ' | xargs)"
    for OLD_PID in $MATCHING_PIDS; do
        kill -TERM "$OLD_PID" 2>/dev/null || true
    done
    for i in $(seq 1 30); do
        STILL_RUNNING=""
        for OLD_PID in $MATCHING_PIDS; do
            if kill -0 "$OLD_PID" 2>/dev/null; then
                STILL_RUNNING="$STILL_RUNNING $OLD_PID"
            fi
        done
        if [ -z "$STILL_RUNNING" ]; then
            echo "  All matching daemons stopped after ${i}s"
            break
        fi
        sleep 1
    done
    for OLD_PID in $MATCHING_PIDS; do
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "  Force killing PID=$OLD_PID"
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
    done
else
    echo "[1/5] No running daemon found for config=$CONFIG"
fi

# 2. Verify checkpoint exists
echo ""
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
echo "[3/5] Starting daemon..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
    VENV_PYTHON=python3
fi
export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
nohup "$VENV_PYTHON" -m crypto_trader.cli run-multi --config "$CONFIG" >> "$LOG" 2>&1 &
NEW_PID=$!
echo "  New PID=$NEW_PID"

# 4. Wait for heartbeat
echo ""
echo "[4/5] Waiting for heartbeat..."
for i in $(seq 1 15); do
    sleep 2
    if [ -f "$HEARTBEAT" ]; then
        CURRENT_PID=$(python3 -c "import json; print(json.load(open('$HEARTBEAT'))['pid'])" 2>/dev/null || echo "")
        if [ "$CURRENT_PID" = "$NEW_PID" ]; then
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
echo "  PID: $NEW_PID"
echo "  Log: $LOG"
echo "  Monitor: tail -f $LOG"
