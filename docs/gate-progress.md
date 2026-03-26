# Gate Progress - 2026-03-27

- Runtime snapshot: `2026-03-26T19:14:42.300893+00:00` from `artifacts/runtime-checkpoint.json`
- Promotion artifacts: `2026-03-26T19:06:53.751188+00:00` to `2026-03-26T19:10:47.745449+00:00` from `artifacts/drift-report.json`, `artifacts/promotion-gate.json`, `artifacts/backtest-baseline.json`
- Active live universe at snapshot: `consensus x1`, `kimchi_premium x1`, `momentum x2`, `volatility_breakout x2`, `vpin x3`
- Scope note: the persisted promotion gate is still a single-symbol decision for `KRW-BTC`. The strategy rows below are the current operating read, not separate persisted gate verdicts.
- Artifact skew note: `promotion-gate.json` still references an older BTC baseline return of `+0.93%`, while the newest `backtest-baseline.json` shows `+2.06%`. This does not change the gate outcome, but it matters for reporting accuracy.

## Executive Summary

- Official gate status is still `stay_in_paper`.
- Current blocker is singular and explicit: `paper pnl is not yet positive`.
- Everything else needed by the current gate logic is already green on the latest artifacts: positive backtest return, acceptable drawdown, enough paper runs, drift `on_track`, and latest verdict `continue`.
- Live portfolio evidence is still too thin for promotion. At this snapshot, total mark-to-market PnL is `-390.62 KRW (-0.0043%)`, realized PnL is `0.00 KRW`, and only `kimchi_premium` has an open position.

## Strategy Snapshot

| Strategy | Wallets | Start Capital | Equity | MTM PnL | MTM Return | Realized PnL | Closed Trades | Open Positions | OOS Return | OOS Sharpe | Current Read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `momentum` | 2 | 2,000,000.00 | 2,000,000.00 | 0.00 | 0.0000% | 0.00 | 0 | 0 | +0.71% | 0.29 | Active set's best research candidate, but live proof has not started because there are still no closed trades. |
| `kimchi_premium` | 1 | 1,000,000.00 | 999,609.38 | -390.62 | -0.0391% | 0.00 | 0 | 1 | +0.47% | 0.22 | Only strategy currently carrying live exposure, so it is also the only visible drag on the portfolio. |
| `vpin` | 3 | 3,000,000.00 | 3,000,000.00 | 0.00 | 0.0000% | 0.00 | 0 | 0 | -1.37% | -1.23 | Flat live and already weak in walk-forward research, so it has no promotion case yet. |
| `volatility_breakout` | 2 | 2,000,000.00 | 2,000,000.00 | 0.00 | 0.0000% | 0.00 | 0 | 0 | +0.25% | -0.28 | Slightly positive OOS return but still negative Sharpe and no live realized evidence. |
| `consensus` | 1 | 1,000,000.00 | 1,000,000.00 | 0.00 | 0.0000% | 0.00 | 0 | 0 | N/A | N/A | Live-only filter wallet in the current setup; no dedicated research-line promotion artifact exists yet. |
| **Portfolio** | **9** | **9,000,000.00** | **8,999,609.38** | **-390.62** | **-0.0043%** | **0.00** | **0** | **1** | — | — | Gate remains blocked by zero realized paper PnL. |

## Promotion Gate Progress

Canonical logic lives in `src/crypto_trader/operator/promotion.py`.

| Criterion | Required | Current Evidence | Progress | Status |
| --- | --- | --- | ---: | --- |
| Backtest return | `> 0%` | `+2.06%` from `artifacts/backtest-baseline.json` | 100% | PASS |
| Backtest max drawdown | `<= 20%` | `0.00%` from `artifacts/backtest-baseline.json` | 100% | PASS |
| Paper runs | `>= 5` | `20` runs from `artifacts/drift-report.json` | 400% | PASS |
| Drift status | not `out_of_sync` or `caution` | `on_track` from `artifacts/drift-report.json` | 100% | PASS |
| Latest verdict | not `pause_strategy` or `reduce_risk` | latest `strategy-runs.jsonl` record is `continue` at `2026-03-26T19:14:42.300323+00:00` | 100% | PASS |
| Paper realized PnL | `> 0%` | `0.00%` from `artifacts/drift-report.json`; runtime checkpoint also shows `0.00 KRW` realized PnL | 0% | FAIL |

Net read: `5 / 6` gate checks are currently green. Promotion is still blocked because paper performance has not produced positive realized PnL yet.

## Remaining Gap

- Minimum gap to promotion: cumulative realized paper PnL must move from `0.00 KRW` to any value `> 0 KRW`.
- In practical terms, the next meaningful milestone is the first closed profitable trade that leaves cumulative realized PnL positive after fees.
- Until that happens, extra paper runs only add confidence to already-passed checks; they do not change the gate decision.

## Interpretation

- `momentum` remains the best active strategy on research quality, but current live evidence is still zero-length from a promotion perspective.
- `kimchi_premium` is the only strategy with open risk right now, so it is the only strategy that can improve or worsen promotion readiness in the very short term.
- `vpin` and `volatility_breakout` are idle in the current snapshot and therefore not contributing any live proof despite being allocated capital.
- `consensus` should be treated as a live execution filter, not a promotable standalone strategy, until it has its own backtest and drift lineage.

## Data Quality Notes

- `promotion-gate.json` and `drift-report.json` are authoritative for the current official gate state, but they are still scoped to `KRW-BTC`.
- `promotion-gate.json` lags the newest `backtest-baseline.json` on baseline return, so official status is usable but the latest return number should be read from `backtest-baseline.json`.
- `runtime-checkpoint.json` is the best source for current strategy-level capital, equity, and open-position counts.
- `strategy-runs.jsonl` records verdicts, but it does not persist `wallet` or `strategy_type`, so per-strategy verdict slicing is inferred rather than directly stored.

## Sources

- `artifacts/runtime-checkpoint.json`
- `artifacts/backtest-baseline.json`
- `artifacts/drift-report.json`
- `artifacts/promotion-gate.json`
- `artifacts/strategy-runs.jsonl`
- `artifacts/walk-forward-90d/grid-wf-summary.json`
- `src/crypto_trader/operator/promotion.py`
