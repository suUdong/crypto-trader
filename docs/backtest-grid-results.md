# 90-Day Backtest Grid Search Summary

Date: 2026-03-26
Scope: 7 strategies x 4 symbols (`KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`) on 90 days of `minute60` candles from Upbit

This file is the short summary. The detailed source-of-truth report lives in
`docs/backtest-grid-90d.md`.

## Runbook

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/baseline.json
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized.toml --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/combined.json
```

Detailed execution notes and the generated config structure live in
`docs/parameter-optimization.md`.

## Headline outcome

- Baseline coverage: `28` runs, `1251` total trades, all `7` strategies produced trades
- Best tuned strategy by ranking metric: `momentum`
- Best tuned return: `kimchi_premium` at `+5.29%`
- `config/optimized.toml` now emits one tuned wallet per strategy using
  `wallets.strategy_overrides` and `wallets.risk_overrides`

## Tuned ranking

| Strategy | Avg Sharpe | Avg Return | Avg MDD | Avg WR | Avg PF | Trades | Winner Rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| momentum | 1.34 | +4.80% | 7.53% | 37.9% | 1.23 | 306 | #1 |
| kimchi_premium | 1.22 | +5.29% | 6.13% | 51.0% | 1.49 | 160 | #1 |
| composite | 1.16 | +0.04% | 0.01% | 50.0% | inf | 2 | #1 |
| mean_reversion | -1.51 | -1.91% | 8.00% | 46.3% | 0.61 | 87 | #1 |
| vpin | -1.86 | -5.13% | 7.03% | 43.1% | 0.66 | 257 | #3 |
| volatility_breakout | -2.25 | -5.95% | 8.97% | 29.2% | 0.60 | 231 | #1 |
| obi | -2.33 | -5.23% | 7.07% | 36.3% | 0.52 | 160 | #1 |

## Best-overall params

```toml
[strategy]
momentum_lookback = 15
momentum_entry_threshold = 0.003
rsi_period = 14
rsi_overbought = 75.0
max_holding_bars = 48

[risk]
stop_loss_pct = 0.03
take_profit_pct = 0.04
risk_per_trade_pct = 0.015
trailing_stop_pct = 0.0
atr_stop_multiplier = 0.0
```

## Generated wallet format

The optimized config is no longer limited to a single runnable strategy. Each tuned
wallet now persists its own overrides, including constructor-only fields that were
previously dropped from the generated TOML.

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

## Artifacts

- Baseline JSON: `artifacts/backtest-grid-90d/baseline.json`
- Combined tune JSON: `artifacts/backtest-grid-90d/combined.json`
- Runnable config: `config/optimized.toml`
- Detailed report: `docs/backtest-grid-90d.md`
