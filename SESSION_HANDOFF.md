# Session Handoff

Date: 2026-03-26 (FIRE Session)
Branch: `master`

## What Landed This Session

### 24. Full 7-strategy grid search + risk optimization + kill switch integration

**7-Strategy Grid Search** (`scripts/grid_search.py`)
- Parameter grid search for ALL strategies: mean_reversion, momentum, composite, vpin, obi, volatility_breakout, kimchi_premium
- Composite grid: bollinger_window, bollinger_stddev, momentum_lookback, momentum_entry_threshold, rsi_period, rsi_recovery_ceiling, max_holding_bars
- Volatility breakout grid: k_base, noise_lookback, ma_filter_period, max_holding_bars
- Kimchi premium grid: rsi_period, rsi_recovery_ceiling, rsi_overbought, min_trade_interval_bars, min_confidence + backtest-compatible via simulated MA-deviation premium
- Scores by Sharpe ratio * (1 - MDD) across 4 symbols (KRW-BTC, ETH, XRP, SOL)

**Auto-Tune Optimizer** (`scripts/auto_tune.py`)
- Two-phase optimization: strategy params -> risk params per strategy
- Risk parameter grid: stop_loss_pct x take_profit_pct x risk_per_trade_pct (36 combos)
- Validates take_profit > stop_loss constraint
- Writes optimized config to TOML with per-strategy results
- Usage: `PYTHONPATH=src .venv/bin/python3 scripts/auto_tune.py 30 config/optimized.toml`

**Volatility Breakout Strategy** (`strategy/volatility_breakout.py`)
- Larry Williams-style breakout with dynamic k adjusted by noise ratio
- MA trend filter prevents entries against the trend
- Exit on close below previous candle low (trailing stop)
- 9 tests covering all signal types

**Kelly Criterion Position Sizing** (`risk/manager.py`)
- Half-Kelly fraction from trade history (min 10 trades)
- Capped at 25% to prevent over-leverage
- Falls back to fixed sizing when insufficient history or negative Kelly
- Integrated into BacktestEngine: `record_trade()` called after each closed trade
- 10 tests covering fraction calculation and sizing

**Weekend Regime Detection** (`strategy/regime.py`)
- KST timezone-aware weekend detection (Sat 00:00 - Mon 09:00 KST)
- Weekend tightens: higher entry threshold, lower RSI ceiling, halved max holding bars
- `WEEKEND_POSITION_MULTIPLIER = 0.5` for reduced position sizes
- Applied in MultiSymbolRuntime via regime analysis
- 11 tests covering KST conversion, param adjustments

**Kill Switch Runtime Integration** (`multi_runtime.py`)
- Wired KillSwitch into MultiSymbolRuntime with automatic check after each tick
- Tracks portfolio equity, daily loss, and consecutive trade losses
- Saves/loads state from `artifacts/kill-switch.json`
- Halts all trading when any limit is breached
- 13 tests covering all trigger conditions + save/load

**Backtest Improvements**
- BacktestEngine now records trades for Kelly sizing via `record_trade()`
- `backtest_all.py` includes volatility_breakout strategy
- Kimchi premium backtestable via simulated premium from MA deviation

### Test Coverage: 270 -> 352 tests (+82)

New test files:
- `test_grid_search.py` (34): offline grid search, all 7 strategy backtests, Kelly integration, param coverage
- `test_volatility_breakout.py` (9): breakout signals, noise ratio, exits
- `test_kelly_sizing.py` (10): Kelly fraction, position sizing, edge cases
- `test_weekend_regime.py` (11): KST weekend detection, param adjustments
- `test_kill_switch_runtime.py` (13): drawdown/daily/consecutive triggers, auto-tune validation
- Updated `test_kimchi_premium.py` (+4): cooldown, confidence filter, exit tests

## Architecture Updates

```
src/crypto_trader/
  strategy/
    volatility_breakout.py  # VolatilityBreakoutStrategy (NEW)
    regime.py               # + is_weekend_kst(), WEEKEND_POSITION_MULTIPLIER, RegimeAnalysis
    indicators.py           # + noise_ratio(), average_true_range(), true_range()
    kimchi_premium.py       # + cooldown_hours, timestamp-based cooldown
  risk/
    kill_switch.py          # KillSwitch, KillSwitchConfig
    manager.py              # + kelly_fraction(), record_trade(), Kelly-aware size_position()
  backtest/
    engine.py               # + record_trade() integration for Kelly sizing
  multi_runtime.py          # + KillSwitch integration, weekend regime, _check_kill_switch_after_tick()
  wallet.py                 # + volatility_breakout in create_strategy()
  config.py                 # + volatility_breakout in valid_strategies
scripts/
  grid_search.py            # 7-strategy grid search (was 4)
  auto_tune.py              # Strategy + risk param optimizer with TOML output (NEW)
  backtest_all.py           # + volatility_breakout
```

## Paper -> Micro-Live Transition Checklist

1. [ ] Run paper daemon for 7+ days total
2. [ ] Achieve 10+ trades with 45%+ win rate
3. [ ] Portfolio MDD < 10%
4. [ ] Profit factor > 1.2
5. [ ] 2+ strategies net profitable
6. [ ] Run `MicroLiveCriteria.evaluate()` -> ready=True
7. [ ] Set `CT_UPBIT_ACCESS_KEY` and `CT_UPBIT_SECRET_KEY` env vars
8. [ ] Run `auto_tune.py` to generate optimized config
9. [ ] Use `config/optimized.toml` or `config/live.toml` (conservative risk)
10. [ ] Monitor kill switch state at `artifacts/kill-switch.json`
11. [ ] Run `pnl-report` command daily to track performance

## Commands Worth Knowing

```bash
# Auto-tune: full grid search + risk optimization → TOML output
PYTHONPATH=src .venv/bin/python3 scripts/auto_tune.py 30 config/optimized.toml

# Grid search for specific strategy
PYTHONPATH=src .venv/bin/python3 scripts/grid_search.py 30 mean_reversion

# Backtest all strategies (now includes volatility_breakout)
PYTHONPATH=src .venv/bin/python3 scripts/backtest_all.py 30

# Portfolio optimization
PYTHONPATH=src .venv/bin/python3 scripts/portfolio_optimizer.py 30

# Compound return simulation
PYTHONPATH=src .venv/bin/python3 scripts/compound_simulator.py 0.332 6000000

# PnL report from checkpoint
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli pnl-report --config config/daemon.toml

# Run multi-symbol daemon
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-multi --config config/daemon.toml
```

## Validation State

- `python3 -m pytest tests/ -q` -- 352 tests passing
- All linting clean

## Current Gaps / Risks

1. Telegram notifications not live-verified (no bot token configured)
2. Compound simulator assumes constant returns (real returns vary by regime)
3. Portfolio optimizer uses backtest data; live correlation may differ
4. Kimchi premium backtest uses simulated premium (MA deviation proxy, not actual Binance/FX data)
5. Auto-tune TOML output needs real Upbit data run to produce meaningful results

## Recommended Next Moves

1. **Run auto-tune** with 90-day real data for production-ready optimized config
2. **Continue paper trading** to meet MicroLiveCriteria
3. **Set up Telegram bot** for daily PnL reports
4. **Evaluate micro-live readiness** after 7 days total paper trading
5. **Add trailing stop** as an additional exit mechanism across strategies
6. **Add regime-adaptive Kelly** that adjusts aggressiveness per market regime
