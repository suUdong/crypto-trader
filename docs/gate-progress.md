# Gate Progress - 2026-03-27

- Runtime snapshot: `2026-03-27T01:25:53.733179+00:00` from `artifacts/runtime-checkpoint.json`
- Promotion artifacts: `2026-03-26T19:57:46.837562+00:00` to `2026-03-26T20:03:33.611542+00:00` from `artifacts/drift-report.json`, `artifacts/promotion-gate.json`, `artifacts/backtest-baseline.json`
- Active live universe at snapshot: `consensus x1`, `ema_crossover x1`, `kimchi_premium x1`, `mean_reversion x1`, `momentum x2`, `volatility_breakout x2`, `volume_spike x2`, `vpin x3`
- Scope note: the persisted promotion gate is still a single-symbol decision for `KRW-BTC`. The strategy rows below are the current operating read, not separate persisted gate verdicts.
- Artifact skew note: `promotion-gate.json` still references an older BTC baseline return of `+0.93%`, while the newest `backtest-baseline.json` shows `+2.06%`. This does not change the gate outcome, but it matters for reporting accuracy.

## Executive Summary

- Official gate status is still `stay_in_paper`.
- Current blocker is singular and explicit: `paper pnl is not yet positive`.
- Everything else needed by the current gate logic is already green on the latest artifacts: positive backtest return, acceptable drawdown, enough paper runs, drift `on_track`, and latest verdict `continue`.
- Live portfolio evidence is still too thin for promotion. At this snapshot, total mark-to-market PnL is `-517.74 KRW (-0.0040%)`, realized PnL is `0.00 KRW`, and open positions total `4`.

## Strategy Snapshot

| Strategy | Wallets | Start Capital | Equity | MTM PnL | MTM Return | Realized PnL | Closed Trades | Open Positions | OOS Return | OOS Sharpe | Current Read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `consensus` | 1 | 1,000,000.00 | 1,000,000.00 | 0.00 | +0.0000% | 0.00 | 0 | 0 | N/A | N/A | Live-only filter wallet in the current setup; no dedicated research-line promotion artifact exists yet. |
| `ema_crossover` | 1 | 1,000,000.00 | 1,000,000.00 | 0.00 | +0.0000% | 0.00 | 0 | 0 | N/A | N/A | No live realized evidence yet, so promotion readiness is still unproven. |
| `kimchi_premium` | 1 | 1,000,000.00 | 999,482.26 | -517.74 | -0.0518% | 0.00 | 0 | 4 | N/A | N/A | Only strategy currently carrying live exposure, so it is also the only visible drag on the portfolio. |
| `mean_reversion` | 1 | 1,000,000.00 | 1,000,000.00 | 0.00 | +0.0000% | 0.00 | 0 | 0 | N/A | N/A | No live realized evidence yet, so promotion readiness is still unproven. |
| `momentum` | 2 | 2,000,000.00 | 2,000,000.00 | 0.00 | +0.0000% | 0.00 | 0 | 0 | N/A | N/A | Active set's best research candidate, but live proof has not started because there are still no closed trades. |
| `volatility_breakout` | 2 | 2,000,000.00 | 2,000,000.00 | 0.00 | +0.0000% | 0.00 | 0 | 0 | N/A | N/A | No live realized evidence yet, so promotion readiness is still unproven. |
| `volume_spike` | 2 | 2,000,000.00 | 2,000,000.00 | 0.00 | +0.0000% | 0.00 | 0 | 0 | N/A | N/A | No live realized evidence yet, so promotion readiness is still unproven. |
| `vpin` | 3 | 3,000,000.00 | 3,000,000.00 | 0.00 | +0.0000% | 0.00 | 0 | 0 | N/A | N/A | No live realized evidence yet, so promotion readiness is still unproven. |
| **Portfolio** | **13** | **13,000,000.00** | **12,999,482.26** | **-517.74** | **-0.0040%** | **0.00** | **0** | **4** | — | — | Gate remains blocked by zero realized paper PnL. |

## Promotion Gate Progress

Canonical logic lives in `src/crypto_trader/operator/promotion.py`.

| Criterion | Required | Current Evidence | Progress | Status |
| --- | --- | --- | ---: | --- |
| Backtest return | `> 0%` | `+2.06%` from `artifacts/backtest-baseline.json` | 100% | PASS |
| Backtest max drawdown | `<= 20%` | `0.00%` from `artifacts/backtest-baseline.json` | 100% | PASS |
| Paper runs | `>= 5` | `20` runs from `artifacts/drift-report.json` | 400% | PASS |
| Drift status | not `out_of_sync` or `caution` | `on_track` from `artifacts/drift-report.json` | 100% | PASS |
| Latest verdict | not `pause_strategy` or `reduce_risk` | latest `strategy-runs.jsonl` record is `continue` at `2026-03-27T01:25:53.732586+00:00` | 100% | PASS |
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
- `src/crypto_trader/operator/promotion.py`