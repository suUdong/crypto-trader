# 90-Day Parameter Optimization Summary

Date: 2026-03-26
Scope: 7 strategies x 4 symbols (`KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`) on cached `minute60` candles

## Runbook

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 \
  --cache-dir artifacts/candle-cache \
  --json-out artifacts/backtest-grid-90d/baseline.json

PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized.toml \
  --cache-dir artifacts/candle-cache \
  --json-out artifacts/backtest-grid-90d/combined.json
```

The tuned candidates were then validated out of sample with the fixed-parameter
walk-forward pass summarized in [walk-forward-results.md](/home/wdsr88/workspace/crypto-trader/docs/walk-forward-results.md).

## Headline Outcome

- Baseline coverage: `28` runs, `1687` total trades, all `7` strategies generated trades
- Best tuned strategy by average Sharpe: `momentum` at `1.34`
- Best tuned strategy by average return: `kimchi_premium` at `+5.29%`
- `config/optimized.toml` now contains runnable wallet blocks for all 7 tuned strategies

## Tuned Ranking

| Strategy | Avg Sharpe | Avg Return | Avg MDD | Avg WR | Avg PF | Trades | Candidate Rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| momentum | 1.34 | +4.80% | 7.53% | 37.9% | 1.23 | 306 | #1 |
| kimchi_premium | 1.22 | +5.29% | 6.13% | 51.0% | 1.49 | 160 | #1 |
| composite | 1.16 | +0.04% | 0.01% | 50.0% | inf | 2 | #1 |
| mean_reversion | -1.51 | -1.91% | 8.00% | 46.3% | 0.61 | 87 | #1 |
| vpin | -1.86 | -5.13% | 7.03% | 43.1% | 0.66 | 257 | #3 |
| volatility_breakout | -2.25 | -5.95% | 8.97% | 29.2% | 0.60 | 231 | #1 |
| obi | -2.33 | -5.23% | 7.07% | 36.3% | 0.52 | 160 | #1 |

## Baseline Averages

| Strategy | Avg Return | Avg MDD | Avg WR | Avg PF | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| momentum | +1.58% | 3.83% | 45.7% | 1.15 | 488 |
| vpin | -0.53% | 4.58% | 51.3% | 0.94 | 235 |
| composite | +0.10% | 0.17% | 25.0% | 0.77 | 6 |
| obi | -2.30% | 4.60% | 42.6% | 0.75 | 290 |
| kimchi_premium | -3.43% | 6.55% | 50.7% | 0.68 | 166 |
| volatility_breakout | -4.73% | 6.07% | 25.9% | 0.58 | 420 |
| mean_reversion | -5.21% | 6.05% | 44.4% | 0.33 | 82 |

## Deployment Note

- In-sample tuning improved `momentum` and `kimchi_premium`, but fixed-parameter walk-forward validation rejected all 7 optimized candidates.
- `config/optimized.toml` is useful for controlled paper experiments, not for automatic promotion to validated deployment.
- `config/validated.toml` now explicitly records a failed validation state instead of carrying forward stale parameters.

## Artifacts

- Baseline JSON: `artifacts/backtest-grid-90d/baseline.json`
- Combined tune JSON: `artifacts/backtest-grid-90d/combined.json`
- Optimized config: `config/optimized.toml`
- Walk-forward JSON: `artifacts/walk-forward-90d/fixed-params-summary.json`
- Walk-forward report: [walk-forward-results.md](/home/wdsr88/workspace/crypto-trader/docs/walk-forward-results.md)
