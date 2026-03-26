# Strategy Performance Comparison Report

**Generated**: 2026-03-26 08:14 UTC
**Scope**: 7-strategy offline comparison across `90`-day baseline, tuned in-sample search, and `90`-day walk-forward validation
**Authoritative sources**: `/home/wdsr88/workspace/crypto-trader/artifacts/backtest-grid-90d/baseline.json`, `/home/wdsr88/workspace/crypto-trader/artifacts/backtest-grid-90d/combined.json`, `/home/wdsr88/workspace/crypto-trader/artifacts/walk-forward-90d/grid-wf-summary.json`

## Executive Summary

- Baseline leader: `momentum` at `+1.40%` average return with `1.14` PF.
- Best in-sample Sharpe after tuning: `momentum` at `1.34`.
- Best in-sample return after tuning: `kimchi_premium` at `+5.29%`.
- Largest tuning lift: `kimchi_premium` improved average return by `+9.49%` versus the untuned baseline.
- Best out-of-sample research candidate: `momentum` with `+0.71%` return and `0.29` Sharpe.
- Positive out-of-sample return appeared in `4` strategies: `composite, kimchi_premium, momentum, volatility_breakout`.
- Validation result: `0 / 7` strategies passed. Promotion remains `NO`.

## Comparison Matrix

| Strategy | Baseline Ret | Baseline PF | Tuned Ret | Tuned Sharpe | Lift | OOS Ret | OOS Sharpe | OOS Win Rate | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| momentum | +1.40% | 1.14 | +4.80% | 1.34 | +3.39% | +0.71% | 0.29 | 33.3% | OOS positive, gate fail |
| composite | +0.38% | 1.57 | +0.04% | 1.16 | -0.34% | +0.63% | 0.24 | 25.0% | OOS positive, gate fail |
| kimchi_premium | -4.20% | 0.67 | +5.29% | 1.22 | +9.49% | +0.47% | 0.22 | 0.0% | OOS positive, gate fail |
| volatility_breakout | -2.18% | 0.80 | -5.95% | -2.25 | -3.76% | +0.25% | -0.28 | 0.0% | Negative edge |
| obi | -2.32% | 0.74 | -5.23% | -2.33 | -2.91% | -1.27% | -0.94 | 8.3% | Negative edge |
| vpin | -0.62% | 0.93 | -5.13% | -1.86 | -4.52% | -1.37% | -1.23 | 16.7% | Negative edge |
| mean_reversion | -5.42% | 0.20 | -1.91% | -1.51 | +3.51% | -4.46% | -3.61 | 16.7% | Negative edge |

## Stability And Risk

| Strategy | Baseline MDD | Tuned MDD | OOS PF | OOS Trades | Efficiency | Tier |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| composite | 0.87% | 0.01% | 1.30 | 60 | -4.95 | research hold |
| kimchi_premium | 6.93% | 6.13% | 1.07 | 240 | -1.95 | research hold |
| momentum | 3.84% | 7.53% | 1.06 | 515 | -0.52 | research hold |
| volatility_breakout | 4.90% | 8.97% | 1.01 | 338 | -1.02 | drop |
| obi | 4.61% | 7.07% | 0.88 | 305 | 2.71 | drop |
| vpin | 4.62% | 7.03% | 0.88 | 238 | 1.92 | drop |
| mean_reversion | 5.96% | 8.00% | 0.38 | 75 | 0.14 | drop |

## Interpretation

1. `momentum` is the current best research candidate. It finished top out of sample at `+0.71%` with `0.29` Sharpe, but still did not clear the promotion gate.
2. `kimchi_premium` produced the biggest in-sample upside (`+5.29%`), but it failed to convert that edge into a validated deployment candidate.
3. `kimchi_premium` showed the biggest tuning lift (`+9.49%`), which is useful for research, but lift alone was not enough to prove robustness.
4. Strategies that only looked good in sample remain a watchlist, not a deployment queue: `none`.
5. The weakest validation cohort was `mean_reversion, vpin, obi`. No strategy cleared the promotion gate, so `config/optimized.toml` should remain a paper/research artifact rather than a validated deployment config.

## Live Snapshot Scope Note

The current `runtime-checkpoint.json` was excluded from the ranking table.

- Offline research universe: `composite, kimchi_premium, mean_reversion, momentum, obi, volatility_breakout, vpin`
- Live snapshot universe: `consensus, kimchi_premium, momentum, volatility_breakout, vpin`
- Missing from live snapshot: `composite, mean_reversion, obi`
- Extra live-only strategies: `consensus`
- Reason: the live wallet mix is not the same 7-strategy matrix, so including it would distort cross-strategy comparison.
