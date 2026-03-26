# Backtest Grid Search and Parameter Optimization

Date: 2026-03-26

This runbook covers the offline optimization flow for the Upbit hourly strategy set.
It turns cached candles into:

- baseline backtest results across all supported strategies
- per-strategy grid-search winners
- risk-optimized parameter sets
- runnable TOML configs with wallet-level overrides

## Commands

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 \
  --cache-dir artifacts/candle-cache \
  --json-out artifacts/backtest-grid-90d/baseline.json

PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized.toml \
  --cache-dir artifacts/candle-cache \
  --json-out artifacts/backtest-grid-90d/combined.json
```

## Ranking logic

`auto_tune.py` runs in two stages.

1. `grid_search.py` sweeps each strategy grid on every symbol and ranks parameter sets by average `sharpe * (1 - mdd)`.
2. The top candidate sets then go through a separate risk sweep over stop loss, take profit, risk-per-trade, trailing stop, and ATR stop multiplier.

The final winner per strategy is selected by:

- highest optimized score
- then highest average Sharpe
- then highest average return

## Output format

`config/optimized.toml` now preserves tuned settings in a runnable form.

- Top-level `[strategy]` and `[risk]` mirror the best-overall strategy for single-strategy CLI compatibility.
- Each `[[wallets]]` entry carries its own `[wallets.strategy_overrides]` and `[wallets.risk_overrides]`.
- Constructor-only params such as `kimchi_premium.min_trade_interval_bars` and `kimchi_premium.min_confidence` are written into the wallet override block and applied at runtime.

Example:

```toml
[[wallets]]
name = "kimchi_premium_wallet"
strategy = "kimchi_premium"
initial_capital = 1_000_000.0

[wallets.strategy_overrides]
rsi_period = 14
rsi_recovery_ceiling = 50.0
rsi_overbought = 75.0
max_holding_bars = 24
min_trade_interval_bars = 6
min_confidence = 0.4

[wallets.risk_overrides]
stop_loss_pct = 0.02
take_profit_pct = 0.04
atr_stop_multiplier = 3.0
```

## Runtime use

- Single-strategy validation: `python -m crypto_trader.cli backtest --config config/optimized.toml --strategy momentum`
- Multi-wallet paper run: `python -m crypto_trader.cli run-multi --config config/optimized.toml`

If you want only positive-Sharpe candidates in paper mode, prune the generated `[[wallets]]` list after reviewing `docs/backtest-grid-results.md`.

## Artifacts

- Baseline JSON: `artifacts/backtest-grid-90d/baseline.json`
- Combined optimization JSON: `artifacts/backtest-grid-90d/combined.json`
- Runnable config: `config/optimized.toml`
- Summary: `docs/backtest-grid-results.md`
- Detailed report: `docs/backtest-grid-90d.md`
