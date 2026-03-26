# Backtest Grid Search and Parameter Optimization

Date: 2026-03-26

This runbook covers the offline optimization flow for the 7-strategy Upbit hourly set.
It uses cached candles to produce:

- baseline backtest coverage across all supported strategies
- one optimized parameter set per strategy
- a runnable multi-wallet config in `config/optimized.toml`
- a fixed-parameter walk-forward validation pass over those optimized candidates

## Commands

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 \
  --cache-dir artifacts/candle-cache \
  --json-out artifacts/backtest-grid-90d/baseline.json

PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized.toml \
  --cache-dir artifacts/candle-cache \
  --json-out artifacts/backtest-grid-90d/combined.json
```

Walk-forward validation for this run was executed by reading the tuned candidates
from `artifacts/backtest-grid-90d/combined.json` and evaluating them with
`validate_with_walk_forward()` across the same 4-symbol, 90-day cache.

## Ranking Logic

`auto_tune.py` runs in two stages.

1. Strategy parameter grid search ranks candidates by average score across symbols.
2. A separate risk sweep tunes stop loss, take profit, risk-per-trade, trailing stop, and ATR stop multiplier.

The selected winner per strategy is ordered by:

- highest optimized score
- then highest average Sharpe
- then highest average return

## Current Outcome

- Revalidated baseline leader: `momentum` (`+1.40%`, `496` trades)
- In-sample leader by Sharpe: `momentum` (`1.34`)
- In-sample leader by return: `kimchi_premium` (`+5.29%`)
- Walk-forward outcome: all `7` optimized candidates failed the out-of-sample gate

That means `config/optimized.toml` is the current research output, while
`config/validated.toml` records a failed promotion state rather than a deployable config.

## Output Format

`config/optimized.toml` preserves tuned settings in a runnable multi-wallet form.

- Top-level `[strategy]` and `[risk]` mirror the best in-sample candidate for single-strategy compatibility.
- Each `[[wallets]]` entry carries its own `[wallets.strategy_overrides]` and `[wallets.risk_overrides]`.
- Constructor-only fields such as `min_trade_interval_bars` and `min_confidence` are preserved in wallet overrides.

## Runtime Use

- Research backtest: `python -m crypto_trader.cli backtest --config config/optimized.toml --strategy momentum`
- Multi-wallet paper run: `python -m crypto_trader.cli run-multi --config config/optimized.toml`
- Validation review: see [walk-forward-results.md](/home/wdsr88/workspace/crypto-trader/docs/walk-forward-results.md)
- Cross-stage comparison: see [strategy-performance-comparison.md](/home/wdsr88/workspace/crypto-trader/docs/strategy-performance-comparison.md)

Do not promote `config/optimized.toml` to validated deployment automatically from this run.

## Artifacts

- Baseline JSON: `artifacts/backtest-grid-90d/baseline.json`
- Combined optimization JSON: `artifacts/backtest-grid-90d/combined.json`
- Optimized config: `config/optimized.toml`
- Walk-forward JSON: `artifacts/walk-forward-90d/fixed-params-summary.json`
- Optimization summary: [backtest-grid-results.md](/home/wdsr88/workspace/crypto-trader/docs/backtest-grid-results.md)
- Walk-forward summary: [walk-forward-results.md](/home/wdsr88/workspace/crypto-trader/docs/walk-forward-results.md)
- Strategy comparison summary: [strategy-performance-comparison.md](/home/wdsr88/workspace/crypto-trader/docs/strategy-performance-comparison.md)
