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

- Baseline coverage: `28` runs, `1699` total trades, all `7` strategies generated trades
- Best tuned strategy by average Sharpe: `momentum` at `1.34`
- Best tuned strategy by average return: `kimchi_premium` at `+5.29%`
- Revalidated baseline leader: `momentum` at `+1.40%` average return with `496` trades
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
| momentum | +1.40% | 3.84% | 45.8% | 1.14 | 496 |
| composite | +0.38% | 0.87% | 39.6% | 1.57 | 22 |
| vpin | -0.62% | 4.62% | 50.8% | 0.93 | 239 |
| volatility_breakout | -2.18% | 4.90% | 30.2% | 0.80 | 395 |
| obi | -2.32% | 4.61% | 43.1% | 0.74 | 293 |
| kimchi_premium | -4.20% | 6.93% | 51.3% | 0.67 | 197 |
| mean_reversion | -5.42% | 5.96% | 26.8% | 0.20 | 57 |

## Deployment Note

- In-sample tuning improved `momentum` and `kimchi_premium`, but fixed-parameter walk-forward validation rejected all 7 optimized candidates.
- The baseline section above was revalidated on the current worktree; tuned and walk-forward sections still reflect the latest stored optimization artifacts.
- `config/optimized.toml` is useful for controlled paper experiments, not for automatic promotion to validated deployment.
- `config/validated.toml` now explicitly records a failed validation state instead of carrying forward stale parameters.

## Artifacts

- Baseline JSON: `artifacts/backtest-grid-90d/baseline.json`
- Combined tune JSON: `artifacts/backtest-grid-90d/combined.json`
- Optimized config: `config/optimized.toml`
- Walk-forward JSON: `artifacts/walk-forward-90d/fixed-params-summary.json`
- Walk-forward report: [walk-forward-results.md](/home/wdsr88/workspace/crypto-trader/docs/walk-forward-results.md)
- Cross-stage comparison: [strategy-performance-comparison.md](/home/wdsr88/workspace/crypto-trader/docs/strategy-performance-comparison.md)
