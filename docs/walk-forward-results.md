# Walk-Forward Validation Results

Date: 2026-03-26
Validation mode: grid search + walk-forward over the 7 supported strategies

- Dataset: `90` days of cached `minute60` candles
- Symbols: `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`
- Candidate search: per-strategy `top-5` grid candidates
- Folds per symbol: `3`
- Total out-of-sample folds per strategy: `12`
- Gate: `avg_test_return_pct > 0`, `oos_win_rate >= 0.5`, `avg_efficiency_ratio > 0.3`, majority-pass across symbols

## Summary

| Strategy | Candidates | Best Sharpe | Best Return | Trades | Profit Factor | Efficiency | OOS Win Rate | Validated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| momentum | 5 | 0.289 | +0.71% | 515 | 1.061 | -0.522 | 0.333 | FAIL |
| composite | 5 | 0.239 | +0.63% | 60 | 1.304 | -4.953 | 0.250 | FAIL |
| kimchi_premium | 4 | 0.217 | +0.47% | 240 | 1.071 | -1.949 | 0.000 | FAIL |
| volatility_breakout | 5 | -0.277 | +0.25% | 338 | 1.012 | -1.019 | 0.000 | FAIL |
| obi | 5 | -0.944 | -1.27% | 305 | 0.882 | 2.709 | 0.083 | FAIL |
| vpin | 5 | -1.234 | -1.37% | 238 | 0.880 | 1.918 | 0.167 | FAIL |
| mean_reversion | 5 | -3.605 | -4.46% | 75 | 0.385 | 0.140 | 0.167 | FAIL |

## Decision

- Result: `NO PROMOTION`
- Validated strategies: `0 / 7`
- Best research candidate: `momentum`
- Best research params: `momentum_lookback=20`, `momentum_entry_threshold=0.005`, `rsi_period=18`, `max_holding_bars=36`
- Why it still failed: efficiency stayed negative (`-0.522`) and only `33.3%` of OOS folds were profitable
- `config/validated.toml` remains intentionally failed so stale research params are not promoted to deployment

## Interpretation

- Re-tuning inside the walk-forward loop improved the research leaderboard relative to the earlier fixed-parameter check, but it still did not produce a deployable candidate.
- `momentum` remained the strongest research setup by combined Sharpe and return, with `515` trades and profit factor `1.061`, so it is the current best parameter set for further offline study.
- `composite` was the cleanest alternate research candidate on profit factor (`1.304`), but its OOS gate was weaker than `momentum`.
- The shared failure mode is robustness, not search quality: positive or near-positive in-sample candidates still degraded materially out of sample.

## Recommended Research Params

### momentum

```toml
[strategy]
momentum_lookback = 20
momentum_entry_threshold = 0.005
rsi_period = 18
max_holding_bars = 36
```

Use these as a research baseline only. They are the strongest candidate from this run, not a validated deployment config.

## Artifacts

- Strategy summaries: `artifacts/grid-wf-90d/*.json`
- Combined summary: `artifacts/walk-forward-90d/grid-wf-summary.json`
- Prior fixed-parameter reference: `artifacts/walk-forward-90d/fixed-params-summary.json`
- Optimized config baseline: `config/optimized.toml`
- Validation status file: `config/validated.toml`
