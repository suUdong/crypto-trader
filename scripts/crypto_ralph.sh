#!/usr/bin/env bash
# crypto_ralph.sh — Claude 자율 FIRE 모드 루프
#
# 매 사이클:
#   1. 현재 시장/연구 상태 수집
#   2. 가장 ROI 높은 작업 결정
#   3. Claude가 자율 실행 (backtest/code/commit)
#   4. 결과 기록 후 대기
#
# Usage:
#   tmux new-window -n "crypto-ralph" -c ~/workspace/crypto-trader
#   ./scripts/crypto_ralph.sh [interval_minutes]

set -uo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERVAL_MINUTES="${1:-20}"
INTERVAL_SECS=$(( INTERVAL_MINUTES * 60 ))
STATE_FILE="$PROJ_ROOT/ralph-loop.state.json"
LOG_FILE="$PROJ_ROOT/logs/crypto_ralph.log"
CLAUDE_CMD="claude --dangerously-skip-permissions"

mkdir -p "$PROJ_ROOT/logs"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

get_cycle() {
    python3 -c "
import json
try:
    s = json.load(open('$STATE_FILE'))
    print(s.get('current_cycle', 66))
except:
    print(66)
" 2>/dev/null || echo "66"
}

save_cycle() {
    local cycle=$1
    python3 -c "
import json
try:
    s = json.load(open('$STATE_FILE'))
except:
    s = {}
s['current_cycle'] = $cycle
s.setdefault('history', []).append({'cycle': $cycle, 'note': 'Cycle $cycle archived.', 'timestamp': __import__('datetime').datetime.now().isoformat()})
s['history'] = s['history'][-50:]
json.dump(s, open('$STATE_FILE', 'w'), indent=2)
" 2>/dev/null
}

get_market_snapshot() {
    python3 -c "
import json, os
try:
    s = json.load(open('artifacts/pre-bull-signals.json'))
    l = s.get('latest', {})
    btc_ret   = l.get('btc_raw_ret', 0)
    btc_acc   = l.get('btc_acc', 1)
    btc_cvd   = l.get('btc_cvd_slope', 0)
    pre_bull  = l.get('pre_bull_score_adj', 0)
    stealth   = l.get('stealth_acc_count', 0)
    total     = l.get('total_coins_scanned', 0)
    regime    = 'BULL' if l.get('btc_bull_regime', False) else 'BEAR'
    print(f'BTC {regime} | ret={btc_ret:+.3f} | acc={btc_acc:.3f} | cvd={btc_cvd:+.3f} | pre_bull={pre_bull:+.3f} | stealth={stealth}/{total}')
except Exception as e:
    print(f'snapshot error: {e}')
" 2>/dev/null
}

get_history_tail() {
    tail -80 "$PROJ_ROOT/docs/backtest_history.md" 2>/dev/null || echo "(no history)"
}

get_research_status() {
    tail -10 "$PROJ_ROOT/logs/strategy_research.log" 2>/dev/null || echo "(no research log)"
}

# ── 메인 루프 ───────────────────────────────────────────────────────────────

log "=============================="
log "💎 crypto-ralph START (interval=${INTERVAL_MINUTES}m)"
log "=============================="

while true; do
    CYCLE=$(( $(get_cycle) + 1 ))
    log ""
    log "=== RALPH CYCLE ${CYCLE} START ==="

    MARKET=$(get_market_snapshot)
    HISTORY=$(get_history_tail)
    RESEARCH=$(get_research_status)

    PROMPT="파이어 모드 crypto-ralph 자율 사이클 ${CYCLE}.

## 현재 시장 상태
${MARKET}

## 최근 백테스트 히스토리 (마지막 80줄)
${HISTORY}

## strategy_research_loop 최근 상태
${RESEARCH}

## 임무
위 정보를 바탕으로 지금 당장 가장 ROI가 높은 작업 하나를 선택하고 완전히 실행해라.

### 우선순위 기준
1. Sharpe > 5.0 전략 발견 → daemon.toml 즉시 반영 (백테스트 근거 있을 때만)
2. 아직 백테스트 안 한 유망 가설 → 스크립트 작성 + 실행
3. 실패한 스크립트 수정 → 재실행
4. 현재 시장 조건에 맞는 즉시 활용 가능한 신호 분석
5. 코드 품질/버그 수정 → 커밋

### 규칙 (절대 준수)
- Python 실행: .venv/bin/python
- 백테스트 결과 → 반드시 docs/backtest_history.md 기록
- Safety 상수(HARD_MAX_DAILY_LOSS_PCT, SAFE_MAX_CONSECUTIVE_LOSSES 등) 변경 금지
- daemon.toml 수정 시 반드시 백테스트 Sharpe > 5.0 근거 필요
- 작업 완료 후 git commit 필수

완료 후 마지막 줄에 반드시 다음 형식으로 출력:
[RALPH CYCLE ${CYCLE} DONE] 작업: <한줄요약> | 결과: <Sharpe/WR/기타>
"

    log "프롬프트 생성 완료. Claude 실행 중..."

    # Claude 실행 (print mode = 비대화형 자율)
    OUTPUT=$(cd "$PROJ_ROOT" && echo "$PROMPT" | $CLAUDE_CMD -p --output-format text 2>&1) || true

    # 결과 로그
    log "--- Claude 출력 ---"
    echo "$OUTPUT" | tail -30 >> "$LOG_FILE"
    echo "$OUTPUT" | tail -5

    # DONE 신호 파싱
    DONE_LINE=$(echo "$OUTPUT" | grep "\[RALPH CYCLE ${CYCLE} DONE\]" | tail -1 || true)
    if [ -n "$DONE_LINE" ]; then
        log "✅ $DONE_LINE"
    else
        log "⚠️  DONE 신호 없음 (에러 또는 미완료)"
    fi

    save_cycle "$CYCLE"
    log "=== RALPH CYCLE ${CYCLE} END === (다음: ${INTERVAL_MINUTES}분 후)"
    log ""

    sleep "$INTERVAL_SECS"
done
