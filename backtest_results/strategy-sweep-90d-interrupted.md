# 3-Month Strategy Sweep Interrupted

- Status: `cancelled`
- Cancelled at: `2026-03-28T03:41:17Z`
- Command:
  `.venv/bin/python scripts/backtest_strategy_sweep.py --days 90 --cache-dir artifacts/candle-cache --output-dir backtest_results`
- Target strategies: `momentum`, `mean_reversion`, `volatility_breakout`
- Symbols: `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`
- Last observed process sample: elapsed `45:12`, CPU time `46:49`, CPU `103%`, memory `0.2%`, state `R`

## Saved State

- No numerical backtest artifacts were flushed before cancellation.
- The interruption manifest is saved in `backtest_results/strategy-sweep-90d-interrupted.json`.
- The code changes needed to rerun the sweep remain committed separately.

## Resume Command

```bash
.venv/bin/python scripts/backtest_strategy_sweep.py --days 90 --cache-dir artifacts/candle-cache --output-dir backtest_results
```
