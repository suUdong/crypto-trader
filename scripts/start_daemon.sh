#!/usr/bin/env bash
# start_daemon.sh — PC 재시작 후 daemon + market_scan 띄우는 스크립트
#
# Usage:
#   ./scripts/start_daemon.sh          # 전체 시작 (daemon + market_scan)
#   ./scripts/start_daemon.sh stop     # 전체 중지
#   ./scripts/start_daemon.sh status   # 상태 확인
#   ./scripts/start_daemon.sh restart  # 재시작

set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJ_ROOT/.venv/bin/python"
CONFIG="$PROJ_ROOT/config/daemon.toml"

DAEMON_LOG="/tmp/crypto_daemon.log"
DAEMON_PID="/tmp/crypto_daemon.pid"
SCAN_LOG="/tmp/market_scan.log"
SCAN_PID="/tmp/market_scan.pid"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# -- PID helpers --

_get_pid() {
    local pid_file="$1" grep_pattern="$2"
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "$pid"
            return
        fi
    fi
    pgrep -f "$grep_pattern" 2>/dev/null | head -1 || true
}

_start_proc() {
    local name="$1" cmd="$2" log_file="$3" pid_file="$4" grep_pattern="$5"
    local existing
    existing=$(_get_pid "$pid_file" "$grep_pattern")
    if [[ -n "$existing" ]]; then
        log "$name 이미 실행 중 (PID $existing)"
        return
    fi
    log "$name 시작..."
    cd "$PROJ_ROOT"
    nohup $cmd > "$log_file" 2>&1 &
    local pid=$!
    echo "$pid" > "$pid_file"
    sleep 3
    if ps -p "$pid" > /dev/null 2>&1; then
        log "$name 시작 완료 (PID $pid)"
        tail -5 "$log_file" 2>/dev/null || true
    else
        log "ERROR: $name 시작 실패"
        tail -20 "$log_file" 2>/dev/null || true
    fi
}

_stop_proc() {
    local name="$1" pid_file="$2" grep_pattern="$3"
    local pid
    pid=$(_get_pid "$pid_file" "$grep_pattern")
    if [[ -z "$pid" ]]; then
        log "$name 실행 중 아님"
        return
    fi
    log "$name 중지 (PID $pid)..."
    kill "$pid" 2>/dev/null || true
    sleep 2
    if ps -p "$pid" > /dev/null 2>&1; then
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
    log "$name 중지 완료"
}

_status_proc() {
    local name="$1" pid_file="$2" grep_pattern="$3" log_file="$4"
    local pid
    pid=$(_get_pid "$pid_file" "$grep_pattern")
    if [[ -n "$pid" ]]; then
        log "$name 실행 중 (PID $pid)"
        ps -p "$pid" -o pid,etime,rss,cmd --no-headers
    else
        log "$name 실행 중 아님"
    fi
    echo "--- $name 최근 로그 ---"
    tail -5 "$log_file" 2>/dev/null || echo "(로그 없음)"
    echo ""
}

# -- Commands --

do_start() {
    _start_proc "daemon" \
        "$VENV_PYTHON -m crypto_trader.cli run-multi --config $CONFIG" \
        "$DAEMON_LOG" "$DAEMON_PID" "crypto_trader.cli run-multi"
    _start_proc "market_scan" \
        "$VENV_PYTHON $PROJ_ROOT/scripts/market_scan_loop.py" \
        "$SCAN_LOG" "$SCAN_PID" "market_scan_loop.py"
}

do_stop() {
    _stop_proc "market_scan" "$SCAN_PID" "market_scan_loop.py"
    _stop_proc "daemon" "$DAEMON_PID" "crypto_trader.cli run-multi"
}

do_status() {
    _status_proc "daemon" "$DAEMON_PID" "crypto_trader.cli run-multi" "$DAEMON_LOG"
    _status_proc "market_scan" "$SCAN_PID" "market_scan_loop.py" "$SCAN_LOG"
}

case "${1:-start}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; do_start ;;
    status)  do_status ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
