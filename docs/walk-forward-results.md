# Walk-Forward Validation Results

Date: 2026-03-26
Validation mode: fixed-parameter walk-forward over the 7 optimized 90-day candidates

- Dataset: `90` days of cached `minute60` candles
- Symbols: `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`
- Folds per symbol: `3`
- Total out-of-sample folds per strategy: `12`
- Gate: `avg_test_return_pct > 0`, `oos_win_rate >= 0.5`, `avg_efficiency_ratio > 0.3`, majority-pass across symbols

## Summary

| Strategy | Optimized Sharpe | WF Test Sharpe | WF Test Return | WF Test MDD | Test Trades | Efficiency | OOS Win Rate | Validated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| momentum | 1.34 | -7.87 | -1.48% | 1.70% | 73 | 0.464 | 0.000 | FAIL |
| kimchi_premium | 1.22 | -7.55 | -1.77% | 2.37% | 78 | -6.084 | 0.000 | FAIL |
| composite | 1.16 | 0.00 | +0.00% | 0.00% | 0 | 0.000 | 0.000 | FAIL |
| mean_reversion | -1.51 | -4.12 | -1.00% | 1.84% | 58 | -0.428 | 0.167 | FAIL |
| vpin | -1.86 | -6.42 | -1.30% | 1.81% | 69 | 0.247 | 0.167 | FAIL |
| volatility_breakout | -2.25 | -7.35 | -1.39% | 1.59% | 79 | -0.714 | 0.000 | FAIL |
| obi | -2.33 | -6.87 | -1.15% | 1.66% | 89 | 5.195 | 0.083 | FAIL |

## Decision

- Result: `NO PROMOTION`
- Validated strategies: `0 / 7`
- Best in-sample candidate remained `momentum`, but its out-of-sample average return was `-1.48%`
- `composite` stayed flat out of sample, but with `0` test trades it is not a deployable result
- `config/validated.toml` is intentionally marked as failed so stale momentum-only parameters are not reused by accident

## Interpretation

- The 90-day exhaustive tune found profitable in-sample parameter sets, especially for `momentum` and `kimchi_premium`.
- Those same fixed parameter sets did not survive walk-forward validation on rolling out-of-sample windows.
- The gap is large enough that the tuned configs should be treated as research artifacts, not validated deployment inputs.

## Artifacts

- Optimization source: `artifacts/backtest-grid-90d/combined.json`
- Walk-forward source: `artifacts/walk-forward-90d/fixed-params-summary.json`
- Optimized config: `config/optimized.toml`
- Validation status file: `config/validated.toml`
