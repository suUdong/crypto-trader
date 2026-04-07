# 🔄 SESSION HANDOFF (자동 생성): 2026-04-07 08:19 UTC

## 1. 실행 상태

| 프로세스 | PID |
|---|---|
| `market_scan_loop.py` | 3926 |
| `strategy_research_loop.py` | 765702 |
| `loop_watchdog.sh` | 1077435 |
| `crypto_trader` daemon | 1060707 |
| market_scan 사이클 | 167 |

```bash
ct                          # 전체 상태 확인
tail -f logs/market_scan.log      # 마켓스캔 로그
tail -f logs/strategy_research.log  # 전략연구 로그
```

---

## 2. 마켓스캔 마지막 로그

```
[21:52:30] Fetched 50 symbols in 8.3s
[21:52:30] Phase 2: Batch GPU computation... [cal:invalid th=0.50]
[21:52:30] GPU done in 0.44s | Total: 8.7s
Watchlist saved: ['KRW-MMT', 'KRW-KERNEL', 'KRW-TRUST', 'KRW-GAS']
[updater] daemon SIGTERM → PID 1915609
[updater] daemon 재시작 PID=1920075
[updater] 히스토리 기록: symbol_rotation / accumulation_dood_wallet / cycle=125 alpha=2.511
[updater] accumulation_dood_wallet: KRW-CELO → KRW-MMT
[updater] daemon SIGTERM → PID 1915609
[updater] daemon SIGTERM → PID 1920075
[updater] daemon 재시작 PID=1920104
[updater] 히스토리 기록: symbol_rotation / accumulation_tree_wallet / cycle=125 alpha=2.511
[updater] accumulation_tree_wallet: KRW-TAO → KRW-KERNEL
[AutoUpdate] 심볼 교체 완료 → daemon 재시작

⚠️  [REGIME FLIP] BULL → BEAR — BTC SMA20 이탈. 방어 모드.
[Pre-Bull] score=+1.000 macro_bonus=+0.000 adj=+1.000 stealth=12/50
[BTC] btc_normal regime=BEAR ret=+0.0101 acc=1.093 cvd=-0.534
[Corr] avg=0.285 leaders=['KRW-BONK', 'KRW-YGG', 'KRW-SONIC']
--- [Cycle 125 DONE] ---
```

---

## 3. Git 변경사항

```
M CLAUDE.md
 M SESSION_HANDOFF.md
 M config/daemon.toml
 M dashboard/app.py
 M dashboard/data.py
 M docs/backtest_history.md
 M docs/strategy_leaderboard.md
 M docs/wallet_changes.md
 M ralph-loop.state.json
 M scripts/crypto_ralph.sh
 M scripts/improvement_loop.py
 M scripts/market_scan_loop.py
 M scripts/strategy_evaluator_loop.py
 M scripts/strategy_research_loop.py
 M scripts/wallet_auto_updater.py
 M src/crypto_trader/config.py
 M src/crypto_trader/macro/adapter.py
 M src/crypto_trader/multi_runtime.py
 M src/crypto_trader/risk/manager.py
 M src/crypto_trader/strategy/__init__.py
```

### 최근 커밋
```
926e4c1 Add .worktrees/ to .gitignore for isolated workspace safety
f725c75 cycle213: 래칫 스탑 RiskManager 구현 + vpin_eth daemon 배포
007d2a4 cycle220: vpin_multi 래칫+분할익절 스태킹 검증 — 분할익절 무효, 래칫만 +3.436 유지
72801f2 cycle219: 2-tier 분할익절+ATR 레짐 적응형 81조합 3-fold WF — avg Sharpe +23.575 (c215 대비 +4.893 개선)
3fad08b cycle210: bb_squeeze_link paper 배포(Sharpe+7.151) + bb_squeeze_sol 비활성화(Sharpe+1.075 FAIL)
```

---

## 4. 최신 백테스트 결과

```
KRW-AVAX         44    +0.38%  52.3% |      0       n/a     n/a
KRW-STX          44    +0.18%  45.5% |      0       n/a     n/a
KRW-SAND         44    +0.16%  52.3% |     19    +0.23%   42.1%
KRW-ARB          17    +0.03%  47.1% |      0       n/a     n/a
KRW-ETH          44    -0.10%  50.0% |     17    -0.78%   29.4%
KRW-SOL          44    -0.18%  38.6% |      0       n/a     n/a
KRW-AXS          44    -0.24%  47.7% |     21    -0.22%   33.3%
KRW-DOT          44    -0.32%  36.4% |      0       n/a     n/a
KRW-ATOM         44    -0.44%  43.2% |     13    -0.34%   46.2%
KRW-NEAR         44    -1.41%  31.8% |      0       n/a     n/a

★ 최고 성과 알트: KRW-SUI  avg=+2.30%  WR=42.9%  n=14

Stealth 필터 개선 심볼: 3/16
  Best: KRW-SAND  stealth_avg=+0.23%  WR=42.1%  n=19

```

</details>

---

## 2026-04-07 07:41 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
전략명: vpin_eth_partial_tp_atr_regime
가설: c219의 2-tier 분할익절+ATR 레짐 적응형 로직(Sharpe+158.89)을 vpin_eth_grid(Sharpe+7.46) 베이스에 이식하면 vpin 엣지와 레짐 적응형 출구가 결합되어 추가 Sharpe 개선 가능.
탐색 파라미터: tp1_atr_mult(0.8/1.2/1.6), tp2_atr_mult(2.0/2.8/3.6), regime_vol_threshold(저변동/고변동 분기점 ATR%값 2개)
예상 스크립트: scripts/backtest_cycle221_vpin_eth_partial_tp_regime.py
근거: 유망 결과 2개(c219 분할익절 레짐 적응형 + vpin_eth_grid)의 직교 결합. c220에서 분할익절 단독 스태킹은 무효였지만 ATR 레짐 적응형 분기는 c219에서 검증됨 — vpin_eth는 아직 레짐 적응형 출구 미적용. poor 그룹(btc_dip 계열, truth_seeker)은 진입 신호 자체가 약해 회피.
```

</details>

---
```

---

## 5. 다음 세션 우선순위

1. `vpin_eth` 신규 파라미터 48h 페이퍼 모니터링 (TP=6%, SL=0.8%, hold=18)
2. `wallet_changes.md` 이력 기반 성과 추적 루틴 추가
3. `accumulation_breakout` 전략 코드에 `stealth_lookback` 파라미터 실제 반영
4. market 회복 시 진입 신호 확인 (pre_bull score 0.75+, BTC SMA20 돌파 감시)

---

## 6. 크립토 랄프 이전 작업 (최근 5개)

```
  사이클 209: 작업: c215 BB Squeeze 개별 심볼 3-fold WF 스크리닝 — c182 최적 파라미터 고정, SOL/DOGE/XRP/LINK/AVAX 5심볼 개별 OOS 성능 검증 | 결과: **DOGE Sharpe +15.515 PASS** (n=44, WR 62.3%, 슬리피지 0.0020에서도 +11.315 robust), **LINK Sharpe +7.151 PASS** (n=42, WR 58.0%, 신규 발견, slip=0.0020→+5.751), SOL +1.075 FAIL (F2/F3 마이너스), XRP -0.636 FAIL, AVAX -1.395 FAIL. 평가자 블로커 'bb_squeeze_sol/doge WF 미보고' 해소 | 다음제안: **(A) bb_squeeze_link daemon.toml 추가 배포** — Sharpe +7.151, 슬리피지 robust, n=42 충분. 초기 자본 ₩500K paper로 forward 검증 시작. **(B) bb_squeeze_sol daemon 모니터링 강화** — 개별 Sharpe 1.075 미달이나 pooled 기여 가능. 2주 paper WR/Sharpe 추적 후 비활성화 결정. **(C) Half-Kelly 포지션 사이징 적용 여부** — 평가자 최우선 [investigate] 항목, 사용자 승인 대기 중
  사이클 210: 작업: bb_squeeze_link paper 배포 + bb_squeeze_sol 비활성화 — c215 개별 심볼 3-fold WF 스크리닝 기반 포트폴리오 리밸런스 | 결과: LINK 추가 (Sharpe +7.151, n=42, WR 58.0%, slip=0.0020→+5.751 robust), SOL 비활성화 (Sharpe +1.075 FAIL, F2/F3 마이너스) | 다음제안: **(A) c216 래칫 스탑 공정 슬리피지 비교** — c212는 slip=0.001(이중)으로 c179 대비 -25.470 하락했으나 slip=0.0005 동일 조건 미검증. strategy_research_loop에 c216_ratchet_fair_slip_atr_adaptive 이미 큐잉됨 → 결과 대기. **(B) Half-Kelly 포지션 사이징 SAFE_MAX 결정** — 평가자 최우선 [investigate], 사용자 승인 대기 중. 15%(보수적 1단계) 시뮬레이션 비교 제안. **(C) bb_squeeze_link paper 30거래 모니터링** — forward 검증 데이터 축적 시작, 2주 후 live Sharpe/backtest Sharpe 비율 산출
  사이클 211: 작업: c219 2-tier 분할익절(tp1M=2.5, 70% 조기청산) + ATR 레짐 적응형 TP/SL — c215 최적 위 81조합 3-fold WF | 결과: **avg OOS Sharpe +23.575 PASS** (c215 +18.682 대비 +4.893 개선), F3 +29.650, WR 66.0%, trades 86, MDD -12.12%(개선). ATR 레짐 적응 효과 없음(hiTP=0 최적), SOL avg +7.658 FAIL(-2.824 악화) | 다음제안: **(A) c219 최적 파라미터를 donchian 전략 daemon 지갑에 적용** — Sharpe +23.575, n=86 충분, 분할익절 로직 src/ 구현 필요. 단 SOL 기여 약화로 SOL 지갑은 c215 파라미터 유지 권장. **(B) c220 SOL 전용 분할익절 최적화** — SOL은 짧은 추세 특성상 pRat=0.3(30% 조기) + 낮은 tp1M이 더 적합할 수 있음. SOL 단독 그리드 탐색으로 SOL avg Sharpe 10+ 복원 시도. **(C) Half-Kelly 포지션 사이징 SAFE_MAX 결정** — 평가자 최우선 [investigate], 사용자 승인 대기 중
  사이클 212: 작업: c220 vpin_multi 래칫 스탑 + 2-tier 분할익절 스태킹 검증 — c216 래칫(+3.436)과 c219 분할익절(+4.893 donchian) 조합 효과 측정 | 결과: **분할익절은 vpin에 무효** (최적 tp1M=0.0, 분할 OFF). 래칫 스탑만 유효 — avg OOS Sharpe +20.707 (baseline +17.271 대비 +3.436). 스태킹 시너지 0. 원인: vpin의 trailing stop이 이미 조기 청산 역할을 대체. slip=0.0020에서도 +18.273 PASS | 다음제안: **(A) 래칫 스탑 src/ 구현 후 vpin_eth daemon 배포** — c216/c220 2회 검증으로 +3.436 안정적 확인, RiskManager에 ratchet_be_trigger/lock_trigger/lock_pct 파라미터 추가. **(B) Multi-timeframe ensemble (240m + 60m)** — 평가자 [explore] 항목, 아직 미탐색. 240m VPIN 진입 + 60m RSI/VPIN 타이밍 보조 시그널로 진입 정밀도 향상 가능. **(C) Half-Kelly 포지션 사이징 SAFE_MAX 결정** — 평가자 최우선 [investigate], 사용자 승인 대기 중
  사이클 213: 작업: 래칫 스탑 RiskManager src/ 구현 + vpin_eth daemon.toml 배포 (c216/c220 검증 기반) | 결과: RiskConfig 3개 파라미터(ratchet_be_trigger=0.5, lock_trigger=1.5, lock_pct=0.90) 추가, exit_reason에 ATR 기반 래칫 로직 구현, 7 unit tests PASS, mypy strict PASS, 382 tests PASS | 다음제안: **(A) Half-Kelly 포지션 사이징 SAFE_MAX 시뮬레이션** — 평가자 3사이클 연속 최우선 [investigate], 15% 상한 1단계 적용 비교. **(B) vpin_eth ratchet paper 1주 모니터링** — paper WR/Sharpe 추적, live Sharpe/backtest 비율 0.7+ 확인. **(C) Multi-timeframe ensemble (240m + 60m)** — 평가자 [explore], 미탐색. **(D) research_loop c220 score_ablation_adaptive_hold 결과 검토** — Sharpe +51.596 / trades 4200 결과 상세 확인 필요 (n 과다 의심)
```

마지막 실행: 2026-04-05T21:19:55.782745
