# 90-Day Backtest Grid Search Results

Canonical report for the current 7-strategy, 90-day grid-search run.
This supersedes older summaries that predate `kimchi_premium`.

Date: 2026-03-26
Scope: 7 strategies x 4 symbols (`KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`) on 90 days of `minute60` candles from Upbit

## Commands

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
from crypto_trader.backtest.candle_cache import fetch_upbit_candles
for symbol in ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]:
    candles = fetch_upbit_candles(symbol, 90, cache_dir="artifacts/candle-cache")
    print(symbol, len(candles))
PY

PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/baseline.json

PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 artifacts/backtest-grid-90d/strategies/momentum.toml --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/strategies/momentum.json --top-n 3 --strategies momentum
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 artifacts/backtest-grid-90d/strategies/mean_reversion.toml --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/strategies/mean_reversion.json --top-n 3 --strategies mean_reversion
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 artifacts/backtest-grid-90d/strategies/composite.toml --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/strategies/composite.json --top-n 3 --strategies composite
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 artifacts/backtest-grid-90d/strategies/kimchi_premium.toml --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/strategies/kimchi_premium.json --top-n 3 --strategies kimchi_premium
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 artifacts/backtest-grid-90d/strategies/obi.toml --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/strategies/obi.json --top-n 3 --strategies obi
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 artifacts/backtest-grid-90d/strategies/vpin.toml --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/strategies/vpin.json --top-n 3 --strategies vpin
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 artifacts/backtest-grid-90d/strategies/volatility_breakout.toml --cache-dir artifacts/candle-cache --json-out artifacts/backtest-grid-90d/strategies/volatility_breakout.json --top-n 3 --strategies volatility_breakout

PYTHONPATH=src .venv/bin/python - <<'PY'
import json
from pathlib import Path
from scripts.auto_tune import TuneResult, write_optimized_toml, write_results_json

base = Path("artifacts/backtest-grid-90d/strategies")
strategy_files = [
    base / "momentum.json",
    base / "mean_reversion.json",
    base / "composite.json",
    base / "kimchi_premium.json",
    base / "obi.json",
    base / "vpin.json",
    base / "volatility_breakout.json",
]
all_results = []
for path in strategy_files:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload["optimized_results"]:
        all_results.append(TuneResult(**item))
baseline_payload = json.loads(Path("artifacts/backtest-grid-90d/baseline.json").read_text(encoding="utf-8"))
write_optimized_toml(all_results, "config/optimized.toml")
write_results_json(baseline_payload["results"], all_results, "artifacts/backtest-grid-90d/combined.json", 90)
PY
```

## Cache note

- `fetch_upbit_candles()` had a pagination boundary bug: feeding the earliest returned candle back into `pyupbit.get_ohlcv(..., to=...)` without a KST/UTC adjustment created a 9-hour overlap per batch.
- I fixed the fetch path to move the `to` boundary by `9h + 1s`, normalized overlapping batches, and added cache self-healing for out-of-order/duplicate timestamps.
- After the fix, all four cache files loaded as valid `2160`-candle snapshots and both baseline and tuning ran off the same dataset.

## Baseline summary

- Total baseline trades across the 28 runs: `1251`
- All 7 strategies generated at least one trade
- Baseline best average return: `composite` at `+0.11%`, but only `6` total trades
- Baseline best practical trade generator before tuning was still `momentum` with `199` trades and the only PF above `1.0`
- Tuning materially improved `momentum` and `kimchi_premium`; the rest remained negative on a 4-symbol average basis

| Strategy | Baseline Return | Baseline MDD | Baseline WR | Baseline PF | Baseline Trades | Optimized Sharpe | Optimized Return | Optimized MDD | Optimized WR | Optimized PF | Optimized Trades | Winner Rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| momentum | -0.60% | 6.39% | 42.4% | 1.03 | 199 | 1.34 | +4.80% | 7.53% | 37.9% | 1.23 | 306 | #1 |
| kimchi_premium | -4.03% | 7.30% | 53.0% | 0.63 | 129 | 1.22 | +5.29% | 6.13% | 51.0% | 1.49 | 160 | #1 |
| composite | +0.11% | 0.18% | 25.0% | 0.79 | 6 | 1.16 | +0.04% | 0.01% | 50.0% | inf | 2 | #1 |
| mean_reversion | -5.28% | 6.12% | 48.2% | 0.35 | 68 | -1.51 | -1.91% | 8.00% | 46.3% | 0.61 | 87 | #1 |
| vpin | -5.66% | 6.73% | 41.6% | 0.39 | 250 | -1.86 | -5.13% | 7.03% | 43.1% | 0.66 | 257 | #3 |
| volatility_breakout | -5.29% | 6.81% | 27.0% | 0.58 | 351 | -2.25 | -5.95% | 8.97% | 29.2% | 0.60 | 231 | #1 |
| obi | -5.42% | 6.49% | 34.3% | 0.50 | 248 | -2.33 | -5.23% | 7.07% | 36.3% | 0.52 | 160 | #1 |

## Final winner

- Strategy: `momentum`
- Avg Sharpe: `1.34`
- Avg Return: `+4.80%`
- Avg MDD: `7.53%`
- Avg Win Rate: `37.9%`
- Avg Profit Factor: `1.23`
- Total Trades: `306`
- Winner came from candidate set `#1`
- Selection rule: best average Sharpe across the evaluated 3-candidate sweep for each strategy

Why not `kimchi_premium`?

- `kimchi_premium` had the best tuned average return at `+5.29%` and the best PF at `1.49`.
- `momentum` still won on the actual ranking metric because its average Sharpe (`1.34`) was higher than `kimchi_premium` (`1.22`).
- `composite` posted positive Sharpe too, but only with `2` trades total, so it is not the stronger deployment candidate.

Winner params:

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

## Top 3 candidate sets by strategy

### momentum

- `#1` score `1.2613`, Sharpe `1.34`, return `+4.80%`, MDD `7.53%`, trades `306`
  params: `momentum_lookback=15`, `momentum_entry_threshold=0.003`, `rsi_period=14`, `rsi_overbought=75`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.03`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#2` score `0.9248`, Sharpe `0.93`, return `+2.58%`, MDD `6.27%`, trades `212`
  params: `momentum_lookback=15`, `momentum_entry_threshold=0.005`, `rsi_period=14`, `rsi_overbought=75`, `max_holding_bars=60`
  risk: `stop_loss_pct=0.03`, `take_profit_pct=0.06`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#3` score `1.2063`, Sharpe `1.28`, return `+4.53%`, MDD `7.83%`, trades `304`
  params: `momentum_lookback=15`, `momentum_entry_threshold=0.003`, `rsi_period=14`, `rsi_overbought=75`, `max_holding_bars=60`
  risk: `stop_loss_pct=0.03`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`

### kimchi_premium

- `#1` score `1.1787`, Sharpe `1.22`, return `+5.29%`, MDD `6.13%`, trades `160`
  params: `rsi_period=14`, `rsi_recovery_ceiling=50`, `rsi_overbought=75`, `max_holding_bars=24`, `min_trade_interval_bars=6`, `min_confidence=0.4`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.01`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`
- `#2` score `1.1787`, Sharpe `1.22`, return `+5.29%`, MDD `6.13%`, trades `160`
  params: `rsi_period=14`, `rsi_recovery_ceiling=50`, `rsi_overbought=75`, `max_holding_bars=24`, `min_trade_interval_bars=6`, `min_confidence=0.6`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.01`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`
- `#3` score `1.1787`, Sharpe `1.22`, return `+5.29%`, MDD `6.13%`, trades `160`
  params: `rsi_period=14`, `rsi_recovery_ceiling=50`, `rsi_overbought=75`, `max_holding_bars=24`, `min_trade_interval_bars=12`, `min_confidence=0.4`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.01`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`

### composite

- `#1` score `1.1552`, Sharpe `1.16`, return `+0.04%`, MDD `0.01%`, trades `2`
  params: `bollinger_window=20`, `bollinger_stddev=1.8`, `momentum_lookback=20`, `momentum_entry_threshold=0.008`, `rsi_period=14`, `rsi_recovery_ceiling=55`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.04`, `take_profit_pct=0.06`, `risk_per_trade_pct=0.005`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#2` score `1.1552`, Sharpe `1.16`, return `+0.04%`, MDD `0.01%`, trades `2`
  params: `bollinger_window=20`, `bollinger_stddev=1.8`, `momentum_lookback=20`, `momentum_entry_threshold=0.008`, `rsi_period=14`, `rsi_recovery_ceiling=55`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.04`, `take_profit_pct=0.06`, `risk_per_trade_pct=0.005`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#3` score `1.1552`, Sharpe `1.16`, return `+0.04%`, MDD `0.01%`, trades `2`
  params: `bollinger_window=20`, `bollinger_stddev=1.8`, `momentum_lookback=20`, `momentum_entry_threshold=0.008`, `rsi_period=14`, `rsi_recovery_ceiling=60`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.04`, `take_profit_pct=0.06`, `risk_per_trade_pct=0.005`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`

### mean_reversion

- `#1` score `-1.3855`, Sharpe `-1.51`, return `-1.91%`, MDD `8.00%`, trades `87`
  params: `bollinger_window=15`, `bollinger_stddev=2.2`, `rsi_period=10`, `rsi_recovery_ceiling=55`, `max_holding_bars=60`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=2.0`
- `#2` score `-1.3855`, Sharpe `-1.51`, return `-1.91%`, MDD `8.00%`, trades `87`
  params: `bollinger_window=15`, `bollinger_stddev=2.2`, `rsi_period=10`, `rsi_recovery_ceiling=60`, `max_holding_bars=60`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=2.0`
- `#3` score `-1.3855`, Sharpe `-1.51`, return `-1.91%`, MDD `8.00%`, trades `87`
  params: `bollinger_window=15`, `bollinger_stddev=2.2`, `rsi_period=10`, `rsi_recovery_ceiling=65`, `max_holding_bars=60`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=2.0`

### vpin

- `#1` score `-1.9947`, Sharpe `-2.15`, return `-5.85%`, MDD `7.38%`, trades `255`
  params: `rsi_period=10`, `momentum_lookback=15`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.02`, `atr_stop_multiplier=0.0`
- `#2` score `-1.8089`, Sharpe `-1.95`, return `-5.49%`, MDD `7.41%`, trades `264`
  params: `rsi_period=14`, `momentum_lookback=15`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.02`, `atr_stop_multiplier=2.0`
- `#3` score `-1.7268`, Sharpe `-1.86`, return `-5.13%`, MDD `7.03%`, trades `257`
  params: `rsi_period=14`, `momentum_lookback=15`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=2.0`

### volatility_breakout

- `#1` score `-2.0502`, Sharpe `-2.25`, return `-5.95%`, MDD `8.97%`, trades `231`
  params: `k_base=0.5`, `noise_lookback=15`, `ma_filter_period=20`, `max_holding_bars=24`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.06`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#2` score `-2.0502`, Sharpe `-2.25`, return `-5.95%`, MDD `8.97%`, trades `231`
  params: `k_base=0.5`, `noise_lookback=15`, `ma_filter_period=20`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.06`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#3` score `-2.0502`, Sharpe `-2.25`, return `-5.95%`, MDD `8.97%`, trades `231`
  params: `k_base=0.5`, `noise_lookback=15`, `ma_filter_period=20`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.06`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`

### obi

- `#1` score `-2.1687`, Sharpe `-2.33`, return `-5.23%`, MDD `7.07%`, trades `160`
  params: `rsi_period=14`, `momentum_lookback=15`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=2.0`
- `#2` score `-2.1687`, Sharpe `-2.33`, return `-5.23%`, MDD `7.07%`, trades `160`
  params: `rsi_period=14`, `momentum_lookback=15`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=2.0`
- `#3` score `-2.1687`, Sharpe `-2.33`, return `-5.23%`, MDD `7.07%`, trades `160`
  params: `rsi_period=14`, `momentum_lookback=20`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=2.0`

## Artifact paths

- Baseline JSON: `artifacts/backtest-grid-90d/baseline.json`
- Combined tune JSON: `artifacts/backtest-grid-90d/combined.json`
- Per-strategy tune JSONs: `artifacts/backtest-grid-90d/strategies/*.json`
- Runnable config: `config/optimized.toml`

## Takeaways

- `momentum` is still the best deployment candidate on the chosen ranking metric.
- `kimchi_premium` is now a real contender after the mock-premium path was wired into both baseline and auto-tune flows.
- `composite` needs a minimum-trade guard before it should be allowed to win on Sharpe alone; `2` trades is not enough evidence.
- The corrected candle pagination/cache path was required for any 90-day comparison to be valid across all 4 symbols.
