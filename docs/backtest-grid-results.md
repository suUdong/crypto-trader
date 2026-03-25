# 90-Day Backtest Grid Search Results

Date: 2026-03-26
Scope: 6 strategies x 4 symbols (`KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`) on 90 days of `minute60` candles from Upbit

## Commands

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 --cache-dir artifacts/candle-cache --json-out artifacts/backtest-baseline-90d.json

PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized-parts/momentum.toml --cache-dir artifacts/candle-cache --json-out artifacts/auto-tune-90d/momentum.json --top-n 3 --strategies momentum
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized-parts/mean_reversion.toml --cache-dir artifacts/candle-cache --json-out artifacts/auto-tune-90d/mean_reversion.json --top-n 3 --strategies mean_reversion
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized-parts/composite.toml --cache-dir artifacts/candle-cache --json-out artifacts/auto-tune-90d/composite.json --top-n 3 --strategies composite
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized-parts/obi.toml --cache-dir artifacts/candle-cache --json-out artifacts/auto-tune-90d/obi.json --top-n 3 --strategies obi
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized-parts/vpin.toml --cache-dir artifacts/candle-cache --json-out artifacts/auto-tune-90d/vpin.json --top-n 3 --strategies vpin
PYTHONPATH=src .venv/bin/python scripts/auto_tune.py 90 config/optimized-parts/volatility_breakout.toml --cache-dir artifacts/candle-cache --json-out artifacts/auto-tune-90d/volatility_breakout.json --top-n 3 --strategies volatility_breakout

PYTHONPATH=src .venv/bin/python - <<'PY'
import json
from pathlib import Path
from scripts.auto_tune import TuneResult, write_optimized_toml, write_results_json

base = Path("artifacts/auto-tune-90d")
files = [
    base / "momentum.json",
    base / "mean_reversion.json",
    base / "composite.json",
    base / "obi.json",
    base / "vpin.json",
    base / "volatility_breakout.json",
]
all_baseline = []
all_results = []
for path in files:
    payload = json.loads(path.read_text(encoding="utf-8"))
    all_baseline.extend(payload["baseline_results"])
    for item in payload["optimized_results"]:
        all_results.append(TuneResult(**item))
write_optimized_toml(all_results, "config/optimized.toml")
write_results_json(all_baseline, all_results, "artifacts/auto-tune-90d/combined.json", 90)
PY
```

Cache note: the first parallel auto-tune attempt hit partial Upbit fetches (`200/400/0` candles). I added a local candle cache and re-ran baseline plus all strategy tuning from the same cached 2160-candle snapshots to keep the comparison valid. The cache now only accepts complete snapshots for the requested lookback.

## Baseline summary

- Total baseline trades across the 24 runs: `972`
- Baseline winner by average return: `momentum` at `+0.85%`
- Only `momentum` and `composite` finished with positive optimized Sharpe across all 4 symbols
- Final runnable config therefore targets the single best overall strategy: `momentum`

| Strategy | Baseline Return | Baseline MDD | Baseline WR | Baseline PF | Baseline Trades | Optimized Sharpe | Optimized Return | Optimized MDD | Optimized WR | Optimized PF | Optimized Trades | Winner Rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| momentum | +0.85% | 5.20% | 39.8% | 1.12 | 229 | 1.60 | +4.59% | 7.29% | 38.4% | 1.53 | 207 | 2 |
| composite | -0.18% | 0.47% | 18.8% | 0.30 | 9 | 0.83 | +2.11% | 4.80% | 49.2% | 1.41 | 63 | 1 |
| mean_reversion | -5.25% | 5.76% | 42.6% | 0.29 | 58 | -1.94 | -5.55% | 8.94% | 40.2% | 0.49 | 94 | 1 |
| vpin | -5.87% | 7.51% | 43.1% | 0.40 | 229 | -2.01 | -6.30% | 8.76% | 44.7% | 0.55 | 218 | 1 |
| volatility_breakout | -5.23% | 6.56% | 26.1% | 0.45 | 250 | -2.24 | -5.35% | 7.24% | 31.6% | 0.56 | 187 | 1 |
| obi | -5.25% | 6.32% | 32.4% | 0.43 | 197 | -2.26 | -5.27% | 7.54% | 38.8% | 0.52 | 138 | 1 |

## Final winner

- Strategy: `momentum`
- Avg Sharpe: `1.60`
- Avg Return: `+4.59%`
- Avg MDD: `7.29%`
- Avg Win Rate: `38.4%`
- Avg Profit Factor: `1.53`
- Total Trades: `207`
- Winner came from candidate set `#2`
- Selection rule: best result within the evaluated 3-candidate sweep for each strategy, not a full joint global optimum across every strategy-param and risk-param combination

Winner params:

```toml
[strategy]
momentum_lookback = 20
momentum_entry_threshold = 0.005
rsi_period = 14
rsi_overbought = 75.0
max_holding_bars = 60

[risk]
stop_loss_pct = 0.03
take_profit_pct = 0.1
risk_per_trade_pct = 0.015
trailing_stop_pct = 0.0
atr_stop_multiplier = 0.0
```

Reason for single-strategy `optimized.toml`: this config format has one global `[strategy]` and one global `[risk]` block, so mixing multiple strategies with different optimized risk profiles in one runnable file would be internally inconsistent.
Cache freshness: `artifacts/candle-cache` is treated as a session cache. Entries older than 6 hours are ignored and fetched again.

## Top 3 candidate sets by strategy

### momentum

- `#1` score `1.4186`, Sharpe `1.47`, return `+4.69%`, MDD `7.00%`, trades `208`
  params: `momentum_lookback=20`, `momentum_entry_threshold=0.005`, `rsi_period=14`, `rsi_overbought=75`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.03`, `take_profit_pct=0.10`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#2` score `1.5392`, Sharpe `1.60`, return `+4.59%`, MDD `7.29%`, trades `207`
  params: `momentum_lookback=20`, `momentum_entry_threshold=0.005`, `rsi_period=14`, `rsi_overbought=75`, `max_holding_bars=60`
  risk: `stop_loss_pct=0.03`, `take_profit_pct=0.10`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#3` score `1.0060`, Sharpe `1.05`, return `+3.14%`, MDD `7.86%`, trades `214`
  params: `momentum_lookback=20`, `momentum_entry_threshold=0.005`, `rsi_period=14`, `rsi_overbought=75`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.03`, `take_profit_pct=0.08`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`

### composite

- `#1` score `0.7850`, Sharpe `0.83`, return `+2.11%`, MDD `4.80%`, trades `63`
  params: `bollinger_window=15`, `bollinger_stddev=1.5`, `momentum_lookback=20`, `momentum_entry_threshold=0.005`, `rsi_period=14`, `rsi_recovery_ceiling=55`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`
- `#2` score `0.6135`, Sharpe `0.62`, return `+0.65%`, MDD `1.62%`, trades `66`
  params: `bollinger_window=15`, `bollinger_stddev=1.5`, `momentum_lookback=20`, `momentum_entry_threshold=0.005`, `rsi_period=14`, `rsi_recovery_ceiling=60`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.005`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`
- `#3` score `0.6135`, Sharpe `0.62`, return `+0.65%`, MDD `1.62%`, trades `66`
  params: `bollinger_window=15`, `bollinger_stddev=1.5`, `momentum_lookback=20`, `momentum_entry_threshold=0.005`, `rsi_period=14`, `rsi_recovery_ceiling=65`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.005`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`

### mean_reversion

- `#1` score `-1.7809`, Sharpe `-1.94`, return `-5.55%`, MDD `8.94%`, trades `94`
  params: `bollinger_window=15`, `bollinger_stddev=1.5`, `rsi_period=18`, `rsi_recovery_ceiling=65`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=0.0`
- `#2` score `-1.7844`, Sharpe `-1.95`, return `-5.56%`, MDD `8.97%`, trades `93`
  params: `bollinger_window=15`, `bollinger_stddev=1.5`, `rsi_period=18`, `rsi_recovery_ceiling=65`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=0.0`
- `#3` score `-1.7848`, Sharpe `-1.95`, return `-5.57%`, MDD `8.98%`, trades `93`
  params: `bollinger_window=15`, `bollinger_stddev=1.5`, `rsi_period=18`, `rsi_recovery_ceiling=65`, `max_holding_bars=60`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=0.0`

### vpin

- `#1` score `-1.8296`, Sharpe `-2.01`, return `-6.30%`, MDD `8.76%`, trades `218`
  params: `rsi_period=14`, `momentum_lookback=15`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=3.0`
- `#2` score `-1.8847`, Sharpe `-2.05`, return `-5.66%`, MDD `8.40%`, trades `209`
  params: `rsi_period=14`, `momentum_lookback=15`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.06`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.04`, `atr_stop_multiplier=0.0`
- `#3` score `-2.0074`, Sharpe `-2.20`, return `-6.17%`, MDD `8.70%`, trades `220`
  params: `rsi_period=14`, `momentum_lookback=20`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`

### volatility_breakout

- `#1` score `-2.0765`, Sharpe `-2.24`, return `-5.35%`, MDD `7.24%`, trades `187`
  params: `k_base=0.7`, `noise_lookback=20`, `ma_filter_period=20`, `max_holding_bars=24`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#2` score `-2.0765`, Sharpe `-2.24`, return `-5.35%`, MDD `7.24%`, trades `187`
  params: `k_base=0.7`, `noise_lookback=20`, `ma_filter_period=20`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`
- `#3` score `-2.0765`, Sharpe `-2.24`, return `-5.35%`, MDD `7.24%`, trades `187`
  params: `k_base=0.7`, `noise_lookback=20`, `ma_filter_period=20`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=0.0`

### obi

- `#1` score `-2.0899`, Sharpe `-2.26`, return `-5.27%`, MDD `7.54%`, trades `138`
  params: `rsi_period=14`, `momentum_lookback=15`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`
- `#2` score `-2.0899`, Sharpe `-2.26`, return `-5.27%`, MDD `7.54%`, trades `138`
  params: `rsi_period=14`, `momentum_lookback=15`, `max_holding_bars=48`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`
- `#3` score `-2.0899`, Sharpe `-2.26`, return `-5.27%`, MDD `7.54%`, trades `138`
  params: `rsi_period=14`, `momentum_lookback=20`, `max_holding_bars=36`
  risk: `stop_loss_pct=0.02`, `take_profit_pct=0.04`, `risk_per_trade_pct=0.015`, `trailing_stop_pct=0.00`, `atr_stop_multiplier=3.0`

## Artifact paths

- Baseline JSON: `artifacts/backtest-baseline-90d.json`
- Combined tune JSON: `artifacts/auto-tune-90d/combined.json`
- Runnable config: `config/optimized.toml`

## Next validation step

Use the new walk-forward validator to measure how the tuned strategy families hold up out-of-sample:

```bash
PYTHONPATH=src .venv/bin/python scripts/walk_forward.py 120 --train-days 60 --test-days 15 --cache-dir artifacts/candle-cache --json-out artifacts/walk-forward.json
```

Smoke result on the current 90-day cache for `momentum` only:

- Command: `PYTHONPATH=src .venv/bin/python scripts/walk_forward.py 90 --train-days 60 --test-days 15 --top-n 2 --strategies momentum --cache-dir artifacts/candle-cache --json-out artifacts/walk-forward-smoke.json --report-out docs/walk-forward-results.md --validated-config-out config/validated.toml --base-toml config/optimized.toml`
- Validation gate defaults: `avg_test_sharpe > 0`, `avg_test_return_pct > 0`, `total_test_trades >= 20`
- Gate status: `PASS`
- Folds: `2`
- Avg train Sharpe: `1.53`
- Avg test Sharpe: `1.89`
- Avg test return: `+0.99%`
- Avg test MDD: `2.44%`
- Total test trades: `103`
- Report artifact: `docs/walk-forward-results.md`
- Validated config artifact: `config/validated.toml`
