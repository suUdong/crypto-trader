# Session Handoff

Date: 2026-03-26 (FIRE Session)
Branch: `master`

## What Landed This Session (5 commits, 100 new tests)

### 24. Full 7-strategy grid search + risk optimization + advanced exits

**7-Strategy Grid Search** (`scripts/grid_search.py`)
- All strategies covered: mean_reversion, momentum, composite, vpin, obi, volatility_breakout, kimchi_premium
- Kimchi premium backtestable via simulated MA-deviation premium
- Scores by Sharpe * (1 - MDD) across 4 symbols (KRW-BTC, ETH, XRP, SOL)

**Auto-Tune Optimizer** (`scripts/auto_tune.py`)
- Two-phase: strategy params → risk params (incl. trailing stop + ATR stops)
- Risk grid: stop_loss × take_profit × risk_per_trade × trailing_stop × atr_multiplier
- Writes optimized TOML with per-strategy results

**Volatility Breakout Strategy** (`strategy/volatility_breakout.py`)
- Larry Williams breakout with dynamic k adjusted by noise ratio
- MA trend filter, exit on close below previous candle low

**Kelly Criterion Position Sizing** (`risk/manager.py`)
- Half-Kelly from trade history (min 10 trades, capped 25%)
- Integrated into BacktestEngine via record_trade()

**Weekend Regime Detection** (`strategy/regime.py`)
- KST timezone (Sat 00:00 - Mon 09:00) low-liquidity detection
- Tightened params + WEEKEND_POSITION_MULTIPLIER = 0.5

**Kill Switch Runtime Integration** (`multi_runtime.py`)
- Wired into MultiSymbolRuntime: portfolio DD, daily loss, consecutive losses
- Auto-saves to artifacts/kill-switch.json, halts all trading on breach

**Trailing Stop** (`risk/manager.py`)
- Position.high_watermark tracks peak price since entry
- Exits when price drops trailing_stop_pct below watermark
- Only triggers after profitable move (locks in gains)

**ATR-Based Dynamic Stops** (`risk/manager.py`)
- stop = entry - ATR × multiplier, TP at 2:1 R:R
- Overrides fixed stops, falls back when no ATR data
- BacktestEngine auto-computes ATR(14) per bar

**Regime-Adaptive Backtest Sizing** (`backtest/engine.py`)
- Optional regime_aware=True: Bull 1.2x, Sideways 1.0x, Bear 0.6x
- More realistic backtests matching live runtime behavior

### Test Coverage: 270 → 370 tests (+100)

New test files:
- `test_grid_search.py` (35): offline grid search, 7 strategy backtests, Kelly integration
- `test_volatility_breakout.py` (9): breakout signals, noise ratio, exits
- `test_kelly_sizing.py` (10): Kelly fraction, position sizing, edge cases
- `test_weekend_regime.py` (11): KST weekend detection, param adjustments
- `test_kill_switch_runtime.py` (13): kill switch triggers, auto-tune validation
- `test_trailing_stop.py` (18): trailing stop, ATR stops, regime-aware backtest
- Updated `test_kimchi_premium.py` (+4): cooldown, confidence filter

## Architecture Updates

```
src/crypto_trader/
  strategy/
    volatility_breakout.py  # VolatilityBreakoutStrategy (NEW)
    regime.py               # + is_weekend_kst(), WEEKEND_POSITION_MULTIPLIER
    indicators.py           # + noise_ratio(), average_true_range()
    kimchi_premium.py       # + timestamp cooldown
  risk/
    kill_switch.py          # KillSwitch, KillSwitchConfig
    manager.py              # + kelly_fraction(), trailing_stop_pct, atr_stop_multiplier
  backtest/
    engine.py               # + record_trade(), ATR feed, regime_aware sizing
  models.py                 # + Position.high_watermark, update_watermark()
  multi_runtime.py          # + KillSwitch integration, weekend regime
  wallet.py                 # + volatility_breakout
  config.py                 # + volatility_breakout in valid_strategies
scripts/
  grid_search.py            # 7-strategy grid (was 4)
  auto_tune.py              # Strategy + risk optimizer with TOML output (NEW)
  backtest_all.py           # + volatility_breakout
```

## Commands Worth Knowing

```bash
# Auto-tune: full grid search + risk optimization → TOML
PYTHONPATH=src .venv/bin/python3 scripts/auto_tune.py 30 config/optimized.toml

# Grid search for specific strategy
PYTHONPATH=src .venv/bin/python3 scripts/grid_search.py 30 mean_reversion

# Backtest all 6 strategies
PYTHONPATH=src .venv/bin/python3 scripts/backtest_all.py 30

# Portfolio optimization
PYTHONPATH=src .venv/bin/python3 scripts/portfolio_optimizer.py 30

# Run multi-symbol daemon
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-multi --config config/daemon.toml

# PnL report
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli pnl-report --config config/daemon.toml
```

## Validation State

- `python3 -m pytest tests/ -q` -- 370 tests passing
- All linting clean

## Current Gaps / Risks

1. Telegram notifications not live-verified (no bot token)
2. Compound simulator assumes constant returns
3. Kimchi premium backtest uses simulated premium (MA deviation proxy)
4. Auto-tune needs real Upbit data run for meaningful results

## Recommended Next Moves

1. **Run auto-tune** with 90-day real data → `config/optimized.toml`
2. **Continue paper trading** to meet MicroLiveCriteria (7d, 10+ trades, 45%+ WR)
3. **Set up Telegram bot** for daily PnL reports
4. **Add walk-forward validation** to prevent overfitting in grid search
5. **Add regime-adaptive Kelly** that adjusts aggressiveness per market regime
