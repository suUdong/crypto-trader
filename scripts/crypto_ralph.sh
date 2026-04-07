#!/usr/bin/env bash
# crypto_ralph.sh — Claude 자율 FIRE 모드 루프
#
# 매 사이클:
#   1. 현재 시장/연구 상태 + 이전 사이클 상세 결과 수집
#   2. Claude가 자율 실행 (backtest/code/commit)
#   3. 상세 결과 저장 → 다음 사이클에 완벽히 연결
#
# Usage:
#   tmux new-window -n "crypto-ralph" -c ~/workspace/crypto-trader
#   ./scripts/crypto_ralph.sh [cooldown_minutes]   # 기본 3분 쿨다운

set -uo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THROTTLE_FILE="$PROJ_ROOT/config/loop_throttle.toml"
COOLDOWN_MINUTES="${1:-3}"
COOLDOWN_SECS=$(( COOLDOWN_MINUTES * 60 ))

# loop_throttle.toml에서 ralph.cooldown_minutes 읽기 (매 사이클 호출)
read_throttle_cooldown() {
    if [[ -f "$THROTTLE_FILE" ]]; then
        local val
        val=$(python3 -c "
import tomllib, pathlib
d = tomllib.loads(pathlib.Path('$THROTTLE_FILE').read_text())
print(d.get('ralph', {}).get('cooldown_minutes', $COOLDOWN_MINUTES))
" 2>/dev/null)
        if [[ -n "$val" ]]; then
            echo "$val"
            return
        fi
    fi
    echo "$COOLDOWN_MINUTES"
}
STATE_FILE="$PROJ_ROOT/ralph-loop.state.json"
LOG_FILE="$PROJ_ROOT/logs/crypto_ralph.log"
CLAUDE_CMD="claude --dangerously-skip-permissions"
CLAUDE_TIMEOUT=1800  # 30분 (작업 완료 기다림)

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
    python3 - "$STATE_FILE" "$cycle" <<'PY'
import json, sys, os, datetime
state_file, cycle = sys.argv[1], int(sys.argv[2])
try:
    s = json.load(open(state_file))
except Exception:
    s = {}
s['current_cycle'] = cycle
s.setdefault('history', []).append({'cycle': cycle, 'timestamp': datetime.datetime.now().isoformat()})
s['history'] = s['history'][-50:]
tmp = state_file + ".tmp"
with open(tmp, 'w') as f:
    json.dump(s, f, indent=2)
os.replace(tmp, state_file)
PY
}

get_market_snapshot() {
    python3 -c "
import json
try:
    s = json.load(open('artifacts/pre-bull-signals.json'))
    l = s.get('latest', {})
    btc_ret  = l.get('btc_raw_ret', 0)
    btc_acc  = l.get('btc_acc', 1)
    btc_cvd  = l.get('btc_cvd_slope', 0)
    pre_bull = l.get('pre_bull_score_adj', 0)
    stealth  = l.get('stealth_acc_count', 0)
    total    = l.get('total_coins_scanned', 0)
    regime   = 'BULL' if l.get('btc_bull_regime', False) else 'BEAR'
    print(f'BTC {regime} | ret={btc_ret:+.3f} | acc={btc_acc:.3f} | cvd={btc_cvd:+.3f} | pre_bull={pre_bull:+.3f} | stealth={stealth}/{total}')
except Exception as e:
    print(f'snapshot error: {e}')
" 2>/dev/null
}

get_evaluator_report() {
    python3 -c "
import json
from pathlib import Path
report_path = Path('$PROJ_ROOT/state/evaluator_report.json')
if not report_path.exists():
    print('(평가자 리포트 없음 — 아직 첫 평가 전)')
else:
    try:
        r = json.loads(report_path.read_text())
        print(f'[평가자 리포트 {r.get(\"eval_id\", \"?\")}] {r.get(\"generated_at\", \"\")[:16]}')
        print(f'방향: {r.get(\"direction\", \"\")}')
        for d in r.get('directives', []):
            print(f'  • [{d[\"type\"]}] {d[\"target\"]}: {d[\"suggested_action\"]}')
        if r.get('blockers'):
            print(f'⚠️  블로커: {r[\"blockers\"]}')
    except Exception as e:
        print(f'리포트 파싱 에러: {e}')
" 2>/dev/null
}

get_history_tail() {
    tail -80 "$PROJ_ROOT/docs/backtest_history.md" 2>/dev/null || echo "(no history)"
}

get_research_status() {
    tail -10 "$PROJ_ROOT/logs/strategy_research.log" 2>/dev/null || echo "(no research log)"
}

# 이전 사이클 상세 결과 (단순 요약이 아닌 실제 출력 포함)
get_prev_context() {
    python3 -c "
import json
try:
    s = json.load(open('$STATE_FILE'))
    done = s.get('ralph_done', [])
    if not done:
        print('(없음 — 첫 사이클)')
    else:
        # 마지막 3개는 상세 출력 포함
        for d in done[-3:]:
            print(f\"=== 사이클 {d['cycle']} ===\")
            print(f\"요약: {d['summary']}\")
            if d.get('detail'):
                print('결과 상세:')
                print(d['detail'])
            print()
except:
    print('(없음)')
" 2>/dev/null
}

save_done() {
    local cycle=$1
    local summary=$2
    local detail=$3  # Claude 출력 마지막 40줄
    RALPH_SUMMARY="$summary" RALPH_DETAIL="$detail" python3 - "$STATE_FILE" "$cycle" <<'PY'
import json, sys, os, datetime
state_file, cycle = sys.argv[1], int(sys.argv[2])
summary = os.environ.get('RALPH_SUMMARY', '')
detail  = os.environ.get('RALPH_DETAIL', '')
try:
    s = json.load(open(state_file))
except Exception:
    s = {}
s.setdefault('ralph_done', []).append({
    'cycle': cycle,
    'summary': summary,
    'detail': detail,
    'timestamp': datetime.datetime.now().isoformat()
})
s['ralph_done'] = s['ralph_done'][-30:]
s['ralph_last_run'] = datetime.datetime.now().isoformat()
tmp = state_file + ".tmp"
with open(tmp, 'w') as f:
    json.dump(s, f, indent=2)
os.replace(tmp, state_file)
PY
}

# ── 메인 루프 ───────────────────────────────────────────────────────────────

log "=============================="
log "💎 crypto-ralph START (cooldown=${COOLDOWN_MINUTES}m, timeout=${CLAUDE_TIMEOUT}s)"
log "=============================="

while true; do
    CYCLE=$(( $(get_cycle) + 1 ))
    log ""
    log "=== RALPH CYCLE ${CYCLE} START ==="

    MARKET=$(get_market_snapshot)
    HISTORY=$(get_history_tail)
    RESEARCH=$(get_research_status)
    PREV_CTX=$(get_prev_context)
    EVAL_REPORT=$(get_evaluator_report)

    PROMPT="파이어 모드 crypto-ralph 자율 사이클 ${CYCLE}.

## 현재 시장 상태
${MARKET}

## 평가자 리포트 (전문 심사관 방향 제시)
${EVAL_REPORT}

## 이전 사이클 상세 결과 (여기서 이어받아 다음 단계 실행)
${PREV_CTX}

## 최근 백테스트 히스토리 (마지막 80줄)
${HISTORY}

## strategy_research_loop 최근 상태
${RESEARCH}

## 임무
이전 사이클 결과를 정확히 이어받아 다음 단계로 발전시켜라.
- 이전이 Sharpe 4.x → 파라미터 범위 확장 또는 필터 추가
- 이전이 실패 → 원인 분석 후 수정 재실행
- 이전이 없음 → 백테스트 히스토리 기반 가장 유망한 가설 선택

지금 당장 작업 하나를 완전히 실행해라.

### ⚠️ 최우선 지시 (사용자 직접 하달 — 현재 시장: BEAR/Sideways, 실매매 수익 0원)
현재 daemon의 모든 전략이 BULL 전용이라 신호 자체가 없다.
**BEAR/Sideways 레짐에서 실제로 작동하는 전략을 찾는 것이 최우선이다.**

BEAR/Sideways 전략 탐색 방향 (아직 성공한 것 없음):
- **단기 변동성 매매**: 급락 후 단기 반등 (RSI 과매도 + 볼륨 급증, 1h 기준)
- **스테이블코인 전환 타이밍**: BTC < SMA200 + CVD 음수 → 알트 비중 축소 시그널
- **레짐별 포지션 사이징**: BEAR 구간 최소 포지션(10~20%) + 반등 신호 시 증대
- **crypto-neutral 전략**: BTC 방향성 무관, 알트 간 상대강도 롱 (pairs/basket)
- **횡보장 mean-reversion**: BB 밴드 내 bounce (stealth_3gate를 Sideways 조건으로 재조정)

백테스트 기간에 BEAR/Sideways 구간 반드시 포함 (2022 BEAR, 2025 Q4 BEAR, 2026 현재).
WF fold 중 최소 1개는 BEAR 구간이어야 배포 검토 가능.

### 우선순위
1. **BEAR/Sideways 전략 탐색** (최우선 — 지금 시장에서 작동하는 것)
2. Sharpe > 5.0 전략 → daemon.toml 반영 (백테스트 근거 있을 때만)
3. 이전 promising 결과 → 개선 (파라미터 확장 / 필터 강화)
4. 미탐색 유망 가설 → 스크립트 작성 + 실행
5. 실패 작업 → 수정 재실행

### 규칙 (절대 준수)
- Python: .venv/bin/python
- 백테스트 결과 → docs/backtest_history.md 기록
- Safety 상수 변경 금지
- daemon.toml 수정 시 Sharpe > 5.0 근거 필요
- 완료 후 git commit 필수
- n < 30 결과로 daemon 배포 결정 금지 (통계적으로 불충분 — Opus/Codex 리뷰)
- OOS 윈도우 재사용 금지 — artifacts/oos_window_registry.json 확인 후 새 윈도우 사용, 완료 후 기록
- daemon 반영 전 단순 보유(buy-and-hold) 대비 수익률 비교 필수
- 슬리피지 미포함 백테스트 결과에는 반드시 ★슬리피지미포함 표시
- 백테스트 진입가: 신호 발생 봉의 종가(close) 사용 금지 → 반드시 다음 봉 시가(next_bar['open']) 사용

완료 후 반드시 마지막에 출력:
[RALPH CYCLE ${CYCLE} DONE] 작업: <한줄요약> | 결과: <Sharpe/WR/기타> | 다음제안: <다음사이클에서 할 것>
"

    log "Claude 실행 중... (최대 ${CLAUDE_TIMEOUT}초, 완료 대기)"
    START_TS=$(date +%s)

    # Claude 실행 — 완료될 때까지 대기 (timeout은 안전망)
    OUTPUT=$(cd "$PROJ_ROOT" && echo "$PROMPT" | timeout "$CLAUDE_TIMEOUT" $CLAUDE_CMD -p --output-format text 2>&1) || true

    END_TS=$(date +%s)
    ELAPSED=$(( END_TS - START_TS ))
    log "Claude 완료 (${ELAPSED}초 소요)"

    # 전체 출력 로그 저장
    echo "$OUTPUT" >> "$LOG_FILE"

    # DONE 신호 파싱
    DONE_LINE=$(echo "$OUTPUT" | grep "\[RALPH CYCLE ${CYCLE} DONE\]" | tail -1 || true)
    DETAIL=$(echo "$OUTPUT" | tail -40)  # 마지막 40줄 = 실제 결과 상세

    if [ -n "$DONE_LINE" ]; then
        log "✅ $DONE_LINE"
        SUMMARY=$(echo "$DONE_LINE" | sed 's/.*DONE\] //')
    else
        log "⚠️  DONE 신호 없음 (타임아웃 ${ELAPSED}s 또는 에러)"
        SUMMARY="DONE 신호 없음 — ${ELAPSED}s 후 종료"
    fi

    save_done "$CYCLE" "$SUMMARY" "$DETAIL"
    save_cycle "$CYCLE"

    THROTTLE_CD=$(read_throttle_cooldown)
    THROTTLE_CD_SECS=$(( THROTTLE_CD * 60 ))
    log "=== RALPH CYCLE ${CYCLE} END === (${THROTTLE_CD}분 쿨다운 후 다음 사이클)"
    log ""

    sleep "$THROTTLE_CD_SECS"
done
