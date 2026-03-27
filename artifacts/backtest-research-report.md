# Backtest Research Report

- Generated: `2026-03-27 08:45 UTC`
- Baseline artifact: `artifacts/backtest-results-90d.json`
- Walk-forward artifact: `artifacts/walk-forward-90d/grid-wf-summary.json`
- Portfolio artifact: `artifacts/portfolio-optimization.json`

## Executive Summary

- Strategy universe: `8`
- Walk-forward validated strategies: `0`
- Best research candidate: `momentum_pullback` at `0.14` Sharpe
- Largest wallet weight: `momentum_pullback` at `100.0%`

## Comparison Matrix

| Strategy | Baseline Ret | Baseline PF | WF Sharpe | WF Return | OOS Win Rate | Validated | Wallet Weight |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| momentum_pullback | -0.80% | 0.48 | 0.14 | +0.01% | 25.0% | NO | 100.0% |
| composite | +0.05% | inf | 0.00 | +0.00% | 0.0% | NO | 0.0% |
| momentum | +0.24% | 1.17 | -4.05 | -0.50% | 25.0% | NO | 0.0% |
| mean_reversion | -1.26% | 0.37 | -6.16 | -0.55% | 16.7% | NO | 0.0% |
| obi | -0.20% | 0.85 | -6.53 | -0.62% | 25.0% | NO | 0.0% |
| kimchi_premium | -0.25% | 0.90 | -6.59 | -0.91% | 16.7% | NO | 0.0% |
| volatility_breakout | -0.27% | 0.60 | -8.64 | -0.55% | 8.3% | NO | 0.0% |
| vpin | +0.01% | 1.02 | -9.14 | -1.05% | 0.0% | NO | 0.0% |

## Wallet Recommendation

| Strategy | Weight | Allocation | WF Sharpe |
| --- | ---: | ---: | ---: |
| momentum_pullback | 100.0% | 8,000,000 KRW | 0.14 |
| composite | 0.0% | 0 KRW | 0.00 |
| momentum | 0.0% | 0 KRW | -4.05 |
| mean_reversion | 0.0% | 0 KRW | -6.16 |
| obi | 0.0% | 0 KRW | -6.53 |
| kimchi_premium | 0.0% | 0 KRW | -6.59 |
| volatility_breakout | 0.0% | 0 KRW | -8.64 |
| vpin | 0.0% | 0 KRW | -9.14 |
