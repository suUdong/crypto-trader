# 🔄 SESSION HANDOFF (자동 생성): 2026-04-03 13:37 UTC

## 1. 실행 상태

| 프로세스 | PID |
|---|---|
| `market_scan_loop.py` | 418754 |
| `strategy_research_loop.py` | 591091 |
| `loop_watchdog.sh` | 591085 |
| `crypto_trader` daemon | 554833 |
| market_scan 사이클 | 79 |

```bash
ct                          # 전체 상태 확인
tail -f logs/market_scan.log      # 마켓스캔 로그
tail -f logs/strategy_research.log  # 전략연구 로그
```

---

## 2. 마켓스캔 마지막 로그

```
--- [Cycle 79 START] ---
[21:48:40] Phase 1: Parallel API fetch...
[21:48:46] Fetched 48 symbols in 5.8s
[21:48:46] Phase 2: Batch GPU computation... [cal:invalid th=0.50]
[21:48:46] GPU done in 0.40s | Total: 6.2s
Watchlist saved: ['KRW-RAY', 'KRW-TAIKO']
[updater] daemon SIGTERM → PID 532804
[updater] daemon 재시작 PID=554829
[updater] 히스토리 기록: symbol_rotation / accumulation_dood_wallet / cycle=79 alpha=2.328
[updater] accumulation_dood_wallet: KRW-MON → KRW-RAY
[updater] daemon SIGTERM → PID 532804
[updater] daemon SIGTERM → PID 554829
[updater] daemon 재시작 PID=554833
[updater] 히스토리 기록: symbol_rotation / accumulation_tree_wallet / cycle=79 alpha=2.328
[updater] accumulation_tree_wallet: KRW-OPEN → KRW-TAIKO
[AutoUpdate] 심볼 교체 완료 → daemon 재시작
[Pre-Bull] score=+0.604 macro_bonus=+0.000 adj=+0.604 stealth=9/48
[BTC] btc_normal regime=BEAR ret=-0.0500 acc=0.991 cvd=-1.291
[Corr] avg=0.334 leaders=['KRW-LSK', 'KRW-ZIL', 'KRW-MOODENG']
--- [Cycle 79 DONE] ---
```

---

## 3. Git 변경사항

```
M .streamlit/config.toml
 M SESSION_HANDOFF.md
 M config/daemon.toml
 M docs/backtest_history.md
 M docs/wallet_changes.md
 M scripts/context_watch_hook.sh
 M scripts/crypto_ralph.sh
 M scripts/generate_handoff.py
 M scripts/strategy_research_loop.py
 M state/market_scan.state.json
 M state/strategy_research.state.json
?? MagicMock/
?? data/
?? docs/ralph_3080_plan.md
?? docs/superpowers/plans/2026-04-01-gpu-enhancement.md
?? docs/superpowers/plans/2026-04-01-pre-bull-detection.md
?? lab-stable.log
?? macro_intelligence.db-shm
?? macro_intelligence.db-wal
?? ralph-loop.state.json
```

### 최근 커밋
```
e0051ff fix: BTC fetch retry in gpu_tournament + tournament results (stealth_3gate Sharpe +6.315)
51329e8 feat: crypto_ralph.sh — autonomous Claude FIRE mode loop
9281330 fix: hypothesis infinite retry on credit error — add to done on API failure
af07047 feat: regime flip alert + tournament results + low_rs_high_acc validation
095d01a research: cvd threshold grid + bull_leadup + prebull signal findings
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

## 2026-04-03 13:35 UTC — Claude 신규 전략 가설 생성 [ralph:new_strategy_hypothesis] ✅[ok]

**결과**: Sharpe N/A | WR N/A | trades N/A
**메모**: Claude 가설 (미검증)

<details><summary>raw output</summary>

```
**전략명**: `momentum_vpin_combo`
**가설**: momentum_sol_grid(Sharpe +14.37)와 vpin_eth_grid(Sharpe +7.46)의 유효성을 확인했으니, 두 신호를 AND 조건으로 결합하면 진입 정밀도가 높아진다 — VPIN 급등(거래량 이상)이 감지된 봉에서만 모멘텀 진입
**탐색 파라미터**: `vpin_threshold` (0.6/0.7/0.8), `momentum_lookback` (3/6/12봉), `tp_sl_ratio` (1.5/2.0/3.0)
**예상 스크립트**: `scripts/backtest_momentum_vpin_combo.py`
**근거**: 두 전략이 각각 독립적으로 높은 Sharpe를 기록했고, 적용 심볼도 다름(SOL vs ETH). VPIN을 모멘텀의 필터로 쓰면 노이즈 진입을 줄이는 방향 — 완전히 새로운 조합이며, btc_dip_alt_entry에서 APT/LINK/SUI가 양의 수익을 보인 심볼들에 우선 적용하면 커버리지 확장도 가능.
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
