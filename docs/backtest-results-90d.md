# 90-Day Backtest Results

Date: 2026-03-26
Last revalidated: 2026-03-26T17:11:32+09:00
Scope: 7 strategies x 4 symbols (`KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`) on 90 days of `minute60` candles from Upbit

## Command

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 --cache-dir artifacts/candle-cache --json-out artifacts/backtest-results-90d.json
```

Raw JSON output was generated at `artifacts/backtest-results-90d.json` during the run.
This report was revalidated on `2026-03-26T17:11:32+09:00` and now reflects the current worktree state.

## Executive Summary

- All 28 backtest combinations completed successfully with `2160` candles per symbol.
- Total trades across the full matrix: `1699`
- All 7 strategies generated at least one trade.
- No symbol had a positive average return across all 7 strategies.
- `KRW-SOL` was the least-bad market on average at `-0.36%`; `KRW-XRP` was still the weakest at `-3.27%`.
- By average return, `momentum` ranked first at `+1.40%` with `496` trades and the best strategy-level average PF among high-volume strategies at `1.14`.
- `composite` improved to `+0.38%`, but it still only produced `22` trades total and remains a thin-sample candidate.
- `vpin` remained the next strongest broad trade generator with `239` trades and `-0.62%` average return.

## Strategy Summary

| Strategy | Avg Return | Avg MDD | Avg Win Rate | Avg PF | Total Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| momentum | +1.40% | 3.84% | 45.8% | 1.14 | 496 |
| composite | +0.38% | 0.87% | 39.6% | 1.57 | 22 |
| vpin | -0.62% | 4.62% | 50.8% | 0.93 | 239 |
| volatility_breakout | -2.18% | 4.90% | 30.2% | 0.80 | 395 |
| obi | -2.32% | 4.61% | 43.1% | 0.74 | 293 |
| kimchi_premium | -4.20% | 6.93% | 51.3% | 0.67 | 197 |
| mean_reversion | -5.42% | 5.96% | 26.8% | 0.20 | 57 |

Notes:

- `momentum` remains the strongest baseline candidate on average return while keeping drawdown below 4%.
- `composite` is now positive with a strong PF, but the sample is still too thin at `22` trades.
- `volatility_breakout` stayed highly active at `395` trades and improved materially versus the earlier snapshot, but still remained negative on average.

## Symbol Summary

| Symbol | Avg Return | Avg MDD | Total Trades | Best Combo | Worst Combo |
| --- | ---: | ---: | ---: | --- | --- |
| KRW-SOL | -0.36% | 4.78% | 512 | `momentum` `+5.17%` | `mean_reversion` `-5.70%` |
| KRW-ETH | -1.78% | 4.15% | 385 | `composite` `+1.28%` | `mean_reversion` `-5.53%` |
| KRW-BTC | -1.99% | 3.63% | 394 | `momentum` `+1.43%` | `mean_reversion` `-5.29%` |
| KRW-XRP | -3.27% | 5.57% | 408 | `composite` `-0.31%` | `vpin` `-5.21%` |

## Best and Worst Runs

Best return combinations:

| Rank | Strategy | Symbol | Return | MDD | Win Rate | Trades | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | momentum | KRW-SOL | +5.17% | 3.71% | 46.0% | 161 | 1.44 |
| 2 | volatility_breakout | KRW-SOL | +2.10% | 4.67% | 42.0% | 112 | 1.15 |
| 3 | momentum | KRW-BTC | +1.43% | 2.42% | 44.9% | 98 | 1.16 |
| 4 | composite | KRW-ETH | +1.28% | 0.78% | 50.0% | 6 | 3.48 |
| 5 | momentum | KRW-ETH | +1.20% | 2.88% | 44.4% | 124 | 1.10 |

Worst return combinations:

| Rank | Strategy | Symbol | Return | MDD | Win Rate | Trades | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | mean_reversion | KRW-SOL | -5.70% | 6.29% | 33.3% | 12 | 0.22 |
| 2 | mean_reversion | KRW-ETH | -5.53% | 5.64% | 10.0% | 10 | 0.05 |
| 3 | mean_reversion | KRW-BTC | -5.29% | 5.85% | 18.2% | 11 | 0.10 |
| 4 | volatility_breakout | KRW-ETH | -5.23% | 5.98% | 23.0% | 61 | 0.45 |
| 5 | vpin | KRW-XRP | -5.21% | 7.85% | 32.1% | 28 | 0.42 |

## Takeaways

- `momentum` remains the strongest baseline strategy and is now clearly carried by `KRW-SOL`, `KRW-BTC`, and `KRW-ETH`.
- `composite` improved into the second-best average-return strategy, but its sample is still too small to outrank higher-volume strategies with confidence.
- `KRW-SOL` is now the cleanest market in the matrix, while `KRW-XRP` remains the weakest and still looks like a candidate for separate tuning or removal.
- `mean_reversion` remains the weakest strategy by average return and now contributes three of the five worst runs outright.

## Validation History

- `2026-03-26T15:16:45+09:00`: rerun matched the original 90-day baseline exactly.
- `2026-03-26T15:21:21+09:00`: rerun matched the original 90-day baseline exactly.
- `2026-03-26T15:26:54+09:00`: rerun produced an updated result set under the current worktree state and superseded the earlier same-day snapshot.
- `2026-03-26T17:11:32+09:00`: rerun produced a new 1699-trade baseline snapshot and superseded the earlier same-day report.
