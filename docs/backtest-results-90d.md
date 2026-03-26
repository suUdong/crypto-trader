# 90-Day Backtest Results

Date: 2026-03-26
Last revalidated: 2026-03-26T15:26:54+09:00
Scope: 7 strategies x 4 symbols (`KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`) on 90 days of `minute60` candles from Upbit

## Command

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 --cache-dir artifacts/candle-cache --json-out artifacts/backtest-results-90d.json
```

Raw JSON output was generated at `artifacts/backtest-results-90d.json` during the run.
This report was revalidated on `2026-03-26T15:26:54+09:00` and now reflects the current worktree state.

## Executive Summary

- All 28 backtest combinations completed successfully with `2160` candles per symbol.
- Total trades across the full matrix: `1465`
- All 7 strategies generated at least one trade.
- No symbol had a positive average return across all 7 strategies.
- `KRW-ETH` was the least-bad market on average at `-0.98%`; `KRW-XRP` was the weakest at `-3.86%`.
- By average return, `momentum` ranked first at `+0.69%` with `266` trades and the best strategy-level average PF at `1.18`.
- `composite` stayed near flat at `+0.10%`, but it still only produced `6` trades total and is not the most actionable winner.
- `vpin` was the next strongest broad trade generator with `235` trades and `-0.53%` average return.

## Strategy Summary

| Strategy | Avg Return | Avg MDD | Avg Win Rate | Avg PF | Total Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| momentum | +0.69% | 5.22% | 44.4% | 1.18 | 266 |
| composite | +0.10% | 0.17% | 25.0% | 0.77 | 6 |
| vpin | -0.53% | 4.58% | 51.3% | 0.94 | 235 |
| obi | -2.30% | 4.60% | 42.6% | 0.75 | 290 |
| kimchi_premium | -3.43% | 6.55% | 50.7% | 0.68 | 166 |
| volatility_breakout | -4.73% | 6.07% | 25.9% | 0.58 | 420 |
| mean_reversion | -5.21% | 6.05% | 44.4% | 0.33 | 82 |

Notes:

- `momentum` is now the strongest baseline candidate on average return and average PF.
- `composite` kept drawdown near zero, but the sample is still too thin at `6` trades.
- `volatility_breakout` was the busiest strategy at `420` trades, but still averaged `-4.73%`.

## Symbol Summary

| Symbol | Avg Return | Avg MDD | Total Trades | Best Combo | Worst Combo |
| --- | ---: | ---: | ---: | --- | --- |
| KRW-ETH | -0.98% | 4.14% | 361 | `momentum` `+6.57%` | `mean_reversion` `-5.41%` |
| KRW-BTC | -1.92% | 3.84% | 356 | `vpin` `+0.90%` | `mean_reversion` `-5.20%` |
| KRW-SOL | -2.04% | 5.13% | 375 | `vpin` `+0.38%` | `mean_reversion` `-5.15%` |
| KRW-XRP | -3.86% | 5.89% | 373 | `composite` `+0.00%` | `kimchi_premium` `-5.20%` |

## Best and Worst Runs

Best return combinations:

| Rank | Strategy | Symbol | Return | MDD | Win Rate | Trades | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | momentum | KRW-ETH | +6.57% | 2.77% | 52.9% | 70 | 2.00 |
| 2 | vpin | KRW-ETH | +1.80% | 2.82% | 57.4% | 68 | 1.16 |
| 3 | vpin | KRW-BTC | +0.90% | 2.05% | 53.7% | 54 | 1.15 |
| 4 | momentum | KRW-BTC | +0.87% | 4.17% | 44.6% | 56 | 1.13 |
| 5 | composite | KRW-ETH | +0.44% | 0.41% | 66.7% | 3 | 2.17 |

Worst return combinations:

| Rank | Strategy | Symbol | Return | MDD | Win Rate | Trades | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | mean_reversion | KRW-ETH | -5.41% | 5.72% | 37.5% | 16 | 0.29 |
| 2 | mean_reversion | KRW-BTC | -5.20% | 5.85% | 47.8% | 23 | 0.33 |
| 3 | kimchi_premium | KRW-XRP | -5.20% | 7.47% | 42.9% | 28 | 0.42 |
| 4 | vpin | KRW-XRP | -5.19% | 7.91% | 34.5% | 29 | 0.42 |
| 5 | mean_reversion | KRW-SOL | -5.15% | 7.01% | 50.0% | 24 | 0.43 |

## Takeaways

- `momentum` is now the strongest baseline strategy on both average return and average PF.
- `vpin` remains the most resilient secondary candidate, staying positive on `KRW-BTC`, `KRW-ETH`, and `KRW-SOL`.
- `KRW-XRP` is still the weakest market in the matrix and remains a candidate for separate tuning or removal from shared-parameter deployment.
- `mean_reversion` is now the weakest strategy by average return and contributed three of the five worst runs.

## Validation History

- `2026-03-26T15:16:45+09:00`: rerun matched the original 90-day baseline exactly.
- `2026-03-26T15:21:21+09:00`: rerun matched the original 90-day baseline exactly.
- `2026-03-26T15:26:54+09:00`: rerun produced an updated result set under the current worktree state and superseded the earlier same-day snapshot.
