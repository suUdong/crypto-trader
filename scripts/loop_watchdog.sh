#!/usr/bin/env bash
# loop_watchdog.sh: market_scan_loop + strategy_research_loop 감시 및 자동 재시작
set -uo pipefail

ROOT="/home/wdsr88/workspace/crypto-trader"
PYTHON="$ROOT/.venv/bin/python3"
LOG_DIR="$ROOT/logs"

mkdir -p "$LOG_DIR"

cd "$ROOT"

echo "[$(date)] loop_watchdog started" >> "$LOG_DIR/watchdog.log"

while true; do
    # market_scan_loop 감시
    if ! pgrep -f "market_scan_loop.py" > /dev/null; then
        echo "[$(date)] market_scan_loop 중단됨. 재시작..." >> "$LOG_DIR/watchdog.log"
        nohup "$PYTHON" -u scripts/market_scan_loop.py >> "$LOG_DIR/market_scan.log" 2>&1 &
        echo "[$(date)] market_scan_loop 재시작 PID=$!" >> "$LOG_DIR/watchdog.log"
    fi

    # strategy_research_loop 감시
    if ! pgrep -f "strategy_research_loop.py" > /dev/null; then
        echo "[$(date)] strategy_research_loop 중단됨. 재시작..." >> "$LOG_DIR/watchdog.log"
        nohup "$PYTHON" -u scripts/strategy_research_loop.py >> "$LOG_DIR/strategy_research.log" 2>&1 &
        echo "[$(date)] strategy_research_loop 재시작 PID=$!" >> "$LOG_DIR/watchdog.log"
    fi

    sleep 30
done
