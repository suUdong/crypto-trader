# Loop Separation Design
**Date:** 2026-04-03  
**Status:** Approved

## Problem

두 루프(`autonomous_lab_loop.py`, `crypto_ralph.py`)가 역할이 겹치고, 이름이 역할을 반영하지 않으며, state 파일을 공유해 race condition 위험이 있음.

## Goals

1. 역할 명확히 분리 — 시장 감시 / 전략 연구
2. 파일명을 역할 기반으로 통일 (`_loop` suffix)
3. state 파일 완전 분리
4. watchdog이 두 루프 모두 감시

---

## File Renames

| 현재 | 변경 후 |
|---|---|
| `scripts/autonomous_lab_loop.py` | `scripts/market_scan_loop.py` |
| `scripts/crypto_ralph.py` | `scripts/strategy_research_loop.py` |
| `scripts/ralph_watchdog.sh` | `scripts/loop_watchdog.sh` |

---

## market_scan_loop.py

**역할:** 실시간 시장 감시 전담. 백테스트 일절 없음.

**주기:** 1시간

**담당 기능:**
- 업비트 50개 심볼 병렬 fetch
- GPU 배치 연산 (stealth score, alpha calibration)
- pre_bull_score 계산 (+ macro bonus)
- BTC regime 판단 (btc_normal / btc_stealth / bear 등)
- 상관관계 리더 추출
- watchlist 저장

**제거 항목:**
- `_backtest_worker` 스레드 (6h GPU alpha backtest) → strategy_research_loop으로 이전
- `_tournament_worker` 스레드 (24h strategy tournament) → strategy_research_loop으로 이전

**State 파일:** `state/market_scan.state.json`
```json
{ "current_cycle": 0 }
```

---

## strategy_research_loop.py

**역할:** 전략 연구 전담. 시장 데이터 실시간 조회 없음.

**주기:** 태스크 완료 후 600초(10분) 대기

**PIPELINE (순차 실행, done 목록으로 중복 방지):**

| ID | 설명 | 주기 힌트 |
|---|---|---|
| `stealth_sol_sweep` | stealth_3gate 전체 마켓 스캔 (GPU) | - |
| `truth_seeker_sweep` | TruthSeeker 파라미터 스윕 | - |
| `vpin_eth_grid` | vpin_eth 파라미터 그리드 | - |
| `momentum_sol_grid` | momentum_sol 파라미터 그리드 | - |
| `regime_stealth` | BTC 레짐 + 스텔스 2-Factor | - |
| `alpha_backtest` | GPU alpha filter 백테스트 (market_scan_loop에서 이전) | 6h 이상 경과 시 |
| `strategy_tournament` | strategy tournament (market_scan_loop에서 이전) | 24h 이상 경과 시 |
| `new_strategy_hypothesis` | Claude CLI 신규 전략 가설 생성 | 파이프라인 소진 시 |

**알림 임계값:** Sharpe >= 3.0 시 텔레그램

**State 파일:** `state/strategy_research.state.json`
```json
{ "cycle": 0, "done": [], "last_run": null }
```

---

## loop_watchdog.sh

**역할:** 두 루프 모두 감시, 죽으면 재시작

**변경 사항:**
- `market_scan_loop.py` + `strategy_research_loop.py` 둘 다 pgrep
- 로그 경로 버그 수정: `logs/lab-stable.log` → `logs/market_scan.log`
- strategy_research_loop 로그: `logs/strategy_research.log`

**로그 파일 정리:**

| 루프 | 로그 |
|---|---|
| market_scan_loop | `logs/market_scan.log` |
| strategy_research_loop | `logs/strategy_research.log` |
| watchdog | `logs/watchdog.log` |

---

## State 파일 마이그레이션

- `ralph-loop.state.json`의 `current_cycle` → `state/market_scan.state.json`
- `ralph-loop.state.json`의 `ralph_cycle`, `ralph_done` → `state/strategy_research.state.json`
- 마이그레이션 후 `ralph-loop.state.json` 삭제

---

## Out of Scope

- 두 루프 간 통신 (IPC, pub/sub) — 현재 불필요
- 전략 파이프라인 내용 변경 — 파일명/state 분리만
- daemon.toml 변경
