# 90-Day Backtest Results

Date: 2026-03-26
Last revalidated: 2026-03-26T15:21:21+09:00
Scope: 7 strategies x 4 symbols (`KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`) on 90 days of `minute60` candles from Upbit

## Command

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 --cache-dir artifacts/candle-cache --json-out artifacts/backtest-results-90d.json
```

Raw JSON output was generated at `artifacts/backtest-results-90d.json` during the run.
This report was revalidated on `2026-03-26T15:21:21+09:00` and matched the prior 90-day baseline exactly.

## Executive Summary

- All 28 backtest combinations completed successfully with `2160` candles per symbol.
- Total trades across the full matrix: `1218`
- All 7 strategies generated at least one trade.
- No symbol had a positive average return across all 7 strategies.
- `KRW-ETH` was the least-bad market on average at `-0.75%`; `KRW-XRP` was the weakest at `-4.75%`.
- By average return, `composite` ranked first at `+0.11%`, but it only produced `6` trades total and is not the most actionable winner.
- By practical balance of return, volume, and profit factor, `momentum` remained the strongest baseline candidate with `199` total trades, `-0.60%` average return, and the only strategy-level average PF above `1.0`.
- `vpin` was the next strongest trade generator with `225` trades and `-0.11%` average return, but its average PF stayed below `1.0` at `0.97`.

## Strategy Summary

| Strategy | Avg Return | Avg MDD | Avg Win Rate | Avg PF | Total Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| composite | +0.11% | 0.18% | 25.0% | 0.79 | 6 |
| vpin | -0.11% | 5.09% | 51.9% | 0.97 | 225 |
| momentum | -0.60% | 6.39% | 42.4% | 1.03 | 199 |
| obi | -2.61% | 5.21% | 40.4% | 0.71 | 240 |
| kimchi_premium | -4.03% | 7.30% | 53.0% | 0.63 | 129 |
| mean_reversion | -5.28% | 6.12% | 48.2% | 0.35 | 68 |
| volatility_breakout | -5.29% | 6.81% | 27.0% | 0.58 | 351 |

Notes:

- `composite` kept drawdown near zero, but the sample is too thin at `6` trades.
- `volatility_breakout` was the busiest strategy at `351` trades and also the worst average return at `-5.29%`.
- `momentum` was the only strategy with average PF above `1.0`.

## Symbol Summary

| Symbol | Avg Return | Avg MDD | Total Trades | Best Combo | Worst Combo |
| --- | ---: | ---: | ---: | --- | --- |
| KRW-ETH | -0.75% | 4.30% | 329 | `momentum` `+7.07%` | `volatility_breakout` `-5.49%` |
| KRW-BTC | -1.76% | 4.17% | 323 | `vpin` `+1.49%` | `volatility_breakout` `-5.42%` |
| KRW-SOL | -2.91% | 6.14% | 310 | `vpin` `+0.95%` | `kimchi_premium` `-5.42%` |
| KRW-XRP | -4.75% | 6.59% | 256 | `composite` `+0.00%` | `kimchi_premium` `-5.87%` |

## Best and Worst Runs

Best return combinations:

| Rank | Strategy | Symbol | Return | MDD | Win Rate | Trades | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | momentum | KRW-ETH | +7.07% | 2.99% | 52.9% | 70 | 1.99 |
| 2 | vpin | KRW-ETH | +2.69% | 3.03% | 57.4% | 68 | 1.22 |
| 3 | vpin | KRW-BTC | +1.49% | 2.05% | 53.7% | 54 | 1.23 |
| 4 | momentum | KRW-BTC | +1.37% | 4.98% | 44.6% | 56 | 1.17 |
| 5 | vpin | KRW-SOL | +0.95% | 6.96% | 59.5% | 84 | 1.05 |

Worst return combinations:

| Rank | Strategy | Symbol | Return | MDD | Win Rate | Trades | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | kimchi_premium | KRW-XRP | -5.87% | 8.12% | 50.0% | 20 | 0.40 |
| 2 | mean_reversion | KRW-XRP | -5.83% | 6.40% | 44.4% | 18 | 0.31 |
| 3 | momentum | KRW-XRP | -5.65% | 8.94% | 28.1% | 32 | 0.47 |
| 4 | vpin | KRW-XRP | -5.56% | 8.30% | 36.8% | 19 | 0.38 |
| 5 | volatility_breakout | KRW-ETH | -5.49% | 7.55% | 24.3% | 74 | 0.50 |

## Takeaways

- `momentum` on `KRW-ETH` was the clearest standalone winner in this baseline sweep.
- `vpin` was more robust than the strategy-average headline suggests, posting positive returns on `KRW-BTC`, `KRW-ETH`, and `KRW-SOL`.
- `KRW-XRP` was the consistent drag across the matrix and deserves either separate tuning or removal from a shared-parameter deployment set.
- `composite` needs a minimum-trade guard before it should be treated as a top baseline performer.

## Validation History

- `2026-03-26T15:16:45+09:00`: rerun matched the original 90-day baseline exactly.
- `2026-03-26T15:21:21+09:00`: rerun matched the original 90-day baseline exactly.
