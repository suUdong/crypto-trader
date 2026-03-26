# Daemon Status - 2026-03-27

- Snapshot taken at `2026-03-26 22:22:45 KST` (`2026-03-26T13:22:45.993367+00:00`)
- Active daemon PID: `3964946`
- Active session id: `20260326T132243Z-3964946`
- Active config: `config/daemon.toml`
- Symbols: `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`
- Wallets: `9` (`momentum x2`, `kimchi_premium x1`, `vpin x3`, `volatility_breakout x2`, `consensus x1`)

## Executive Summary

현재 데몬은 실행 중이지만, 방금 재시작된 세션이라 누적 증거가 거의 없습니다. 최신 `runtime-checkpoint.json` 기준 포트폴리오 시작 자본 `9,000,000 KRW` 대비 평가손익은 `-350.09 KRW (-0.0039%)`이며, 손실은 `kimchi_premium`의 미실현 손익 1건에서만 발생했습니다.

현재 세션에는 아직 닫힌 거래가 없어 전략별 realized PnL, 거래 수, 승률은 전부 `0 / N/A`입니다. promotion gate는 백테스트 조건은 통과했지만, paper run 수와 realized PnL 증거가 부족해서 아직 초기 단계입니다.

## Strategy Performance

Source of truth for current performance: `artifacts/runtime-checkpoint.json` at `2026-03-26T13:22:45.993367+00:00`.

| Strategy | Wallets | Start Capital (KRW) | Equity (KRW) | MTM PnL (KRW) | MTM Return | Realized PnL (KRW) | Closed Trades | Win Rate | Open Positions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| momentum | 2 | 2,000,000.00 | 2,000,000.00 | 0.00 | 0.0000% | 0.00 | 0 | N/A | 0 |
| kimchi_premium | 1 | 1,000,000.00 | 999,649.91 | -350.09 | -0.0350% | 0.00 | 0 | N/A | 1 |
| vpin | 3 | 3,000,000.00 | 3,000,000.00 | 0.00 | 0.0000% | 0.00 | 0 | N/A | 0 |
| volatility_breakout | 2 | 2,000,000.00 | 2,000,000.00 | 0.00 | 0.0000% | 0.00 | 0 | N/A | 0 |
| consensus | 1 | 1,000,000.00 | 1,000,000.00 | 0.00 | 0.0000% | 0.00 | 0 | N/A | 0 |
| **Portfolio** | **9** | **9,000,000.00** | **8,999,649.91** | **-350.09** | **-0.0039%** | **0.00** | **0** | **N/A** | **1** |

## Promotion Gate Progress

Canonical gate logic lives in `src/crypto_trader/operator/promotion.py`. It currently requires:

1. positive backtest return
2. backtest max drawdown `<= 20%`
3. at least `5` paper runs
4. drift status not `out_of_sync` or `caution`
5. positive paper realized PnL
6. latest strategy verdict not `pause_strategy` or `reduce_risk`

### Current Progress vs Gate

| Criterion | Required | Current Evidence | Progress | Status |
|---|---|---|---|---|
| Backtest return | `> 0%` | `+3.57%` from `artifacts/backtest-baseline.json` (`2026-03-26T06:56:53.036620+00:00`) | 100% | PASS |
| Backtest max drawdown | `<= 20%` | `0.37%` from `artifacts/backtest-baseline.json` | 100% | PASS |
| Paper runs | `>= 5` | `1` current session iteration in `artifacts/daemon-heartbeat.json` | 20% | IN PROGRESS |
| Paper realized PnL | `> 0` | `0.00 KRW`, no closed trades yet | 0% | FAIL |
| Drift status | `on_track` | No fresh multi-wallet drift artifact for current session | unknown | BLOCKED BY STALE ARTIFACT |
| Latest verdict | not `pause_strategy`/`reduce_risk` | No fresh multi-wallet strategy verdict journal | unknown | BLOCKED BY STALE ARTIFACT |

### Net Readiness

- Hard passes: `2 / 6`
- In progress: `1 / 6`
- Failing now: `1 / 6`
- Blocked by stale artifacts: `2 / 6`

Practical reading: gate readiness is still well below promotion level. Even if the stale-artifact blockers were resolved favorably, the current session would still fail on realized PnL and would need `4` more paper runs to reach the minimum run count.

## Artifact Analysis

### Fresh and trustworthy for current status

- `artifacts/daemon-heartbeat.json`
  - updated at `2026-03-26 22:22:45 KST`
  - confirms daemon is currently running on PID `3964946`
- `artifacts/runtime-checkpoint.json`
  - updated at `2026-03-26 22:22:45 KST`
  - best source for current wallet equity, open positions, and trade counts
- `artifacts/backtest-baseline.json`
  - updated at `2026-03-26 15:56:53 KST`
  - shows the current BTC baseline is positive (`+3.57%`) with low drawdown (`0.37%`)

### Stale or inconsistent artifacts

- `artifacts/promotion-gate.json`
  - last updated `2026-03-25 06:49:07 KST`
  - still says `do_not_promote` because it references an older baseline with `0.0%` return
- `artifacts/drift-report.json`
  - same timestamp family as the stale promotion gate
  - still reflects a legacy single-symbol snapshot rather than the current multi-wallet daemon
- `artifacts/pnl-report.json`
  - last updated `2026-03-26 14:41:35 KST`
  - only includes `momentum_btc_wallet`, `momentum_eth_wallet`, and `kimchi_premium_wallet`, so it does not fully represent the active 9-wallet config
- `artifacts/paper-trades.jsonl`
  - contains `226` rows, all dated `2025-01-02`
  - all rows belong to `momentum_wallet`
  - naive journal aggregation yields `-53,134.02 KRW`, `226` trades, `0.0%` win rate
  - these look like legacy synthetic entries, not current daemon evidence
- `artifacts/positions.json`
  - last updated `2026-03-26 12:44:12 KST`
  - says `0` positions, which conflicts with the latest checkpoint showing `kimchi_premium` has `1` open position
- `artifacts/performance-dashboard.md`
  - says the daemon is running a reduced 2-strategy setup
  - latest checkpoint shows 5 strategy families and 9 wallets, so the dashboard is not current

## Takeaways

- Current live evidence is extremely early: one fresh session iteration, zero closed trades, one open `kimchi_premium` position.
- Current realized performance is flat, so no strategy has enough evidence yet to claim a positive edge in paper trading.
- The newest baseline is materially better than the persisted promotion-gate artifact suggests. The gate artifact should not be used as the current truth until it is regenerated.
- The main operational risk right now is not trading loss; it is artifact drift. Several reporting artifacts are stale enough to misstate both strategy count and promotion readiness.

## Sources

- `artifacts/daemon-heartbeat.json`
- `artifacts/runtime-checkpoint.json`
- `artifacts/backtest-baseline.json`
- `artifacts/promotion-gate.json`
- `artifacts/drift-report.json`
- `artifacts/pnl-report.json`
- `artifacts/paper-trades.jsonl`
- `artifacts/positions.json`
- `artifacts/performance-dashboard.md`
- `src/crypto_trader/operator/promotion.py`
