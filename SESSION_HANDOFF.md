# Session Handoff

Date: 2026-03-25 (FIRE Session)
Branch: `master`

## What Landed This Session

### 23. Strategy optimization & live trading preparation

**Grid Search Backtest** (`scripts/grid_search.py`)
- Parameter grid search for mean_reversion, momentum, vpin, obi strategies
- Tests all parameter combinations across 4 symbols (KRW-BTC, ETH, XRP, SOL)
- Scores by Sharpe ratio weighted by drawdown penalty
- Outputs best params per strategy with per-symbol breakdown

**Kimchi Premium Overtrading Fix** (`strategy/kimchi_premium.py`)
- Increased `min_trade_interval_bars` from 4 to 12 (12h cooldown vs 4h)
- Raised `min_confidence` from 0.5 to 0.6
- Should reduce 43 trades/48h to ~8-10 trades/48h

**VPIN Zero-Signal Fix** (`strategy/vpin.py`)
- Raised `vpin_low_threshold` from 0.5 to 0.65 (easier entry condition)
- Lowered `vpin_momentum_threshold` from 0.0 to -0.005 (allow slight negative momentum)
- Raised `vpin_rsi_ceiling` from 70.0 to 75.0 (wider entry window)
- Should generate signals in sideways regime where it was previously silent

**Portfolio Optimizer** (`scripts/portfolio_optimizer.py`)
- Runs all strategies on same candle data, computes pairwise return correlation matrix
- Mean-variance optimization with Sharpe-proportional weights + MDD penalty
- Outputs recommended wallet allocation (replaces equal-weight)

**Regime-Aware Strategy Weights** (`macro/adapter.py`, `multi_runtime.py`)
- Added `STRATEGY_REGIME_WEIGHTS` to MacroRegimeAdapter:
  - Sideways: mean_reversion 1.5x, obi 1.3x, momentum 0.6x
  - Bull: momentum 1.4x, mean_reversion 0.7x
  - Bear: momentum 0.4x, kimchi_premium 0.5x
- MultiSymbolRuntime now detects market regime from first symbol's candles
- Applies per-wallet multiplier = macro_multiplier * strategy_regime_weight

**Compound Return Simulator** (`scripts/compound_simulator.py`)
- Simulates compounding at observed 48h return rate over 30/90/180/365 days
- Conservative/Base/Optimistic/Drawdown scenarios
- Key milestones (days to 2x, 3x, 10x)
- Portfolio scaling projections at different capital levels

**Kill Switch** (`risk/kill_switch.py`)
- Portfolio drawdown limit (default 5%)
- Daily loss limit (default 3%)
- Consecutive loss limit (default 5)
- Save/load state, manual reset
- 8 tests covering all trigger conditions

**Live Trading Infrastructure**
- Removed blanket live trading block; now requires Upbit API credentials
- `config/live.toml` template: micro-live config with conservative risk (0.5% per trade, 2% daily loss)
- Top 3 strategies only: mean_reversion (500K), obi (300K), momentum (200K)
- `MicroLiveCriteria` in promotion.py: 7d paper minimum, 10+ trades, 45%+ win rate, <10% MDD, 1.2+ PF, 2+ profitable strategies

**PnL Report Automation** (`operator/pnl_report.py`)
- `PnLReportGenerator` reads runtime checkpoint + trade journal
- Computes Sharpe ratio, MDD, win rate, profit factor per strategy and portfolio
- Generates markdown + JSON reports
- CLI command: `pnl-report`

### Test Coverage: 202 -> 270 tests (+68)

New test files:
- `test_kill_switch.py` (8 tests)
- `test_pnl_report.py` (5 tests)
- `test_compound_simulator.py` (6 tests)
- `test_regime_weights.py` (8 tests)
- `test_micro_live_criteria.py` (8 tests)
- Updated `test_config.py` (+1 test for live trading with credentials)

## Architecture Updates

```
src/crypto_trader/
  risk/
    kill_switch.py          # KillSwitch, KillSwitchConfig (NEW)
  operator/
    pnl_report.py           # PnLReportGenerator (NEW)
    promotion.py            # + MicroLiveCriteria (NEW class)
  macro/
    adapter.py              # + STRATEGY_REGIME_WEIGHTS, strategy_weight()
  multi_runtime.py          # + regime detection, regime-aware wallet multipliers
  config.py                 # Live trading now allowed with credentials
  cli.py                    # + pnl-report command
scripts/
  grid_search.py            # Parameter grid search (NEW)
  portfolio_optimizer.py    # Correlation + weight optimization (NEW)
  compound_simulator.py     # Compound return simulator (NEW)
config/
  live.toml                 # Micro-live trading config template (NEW)
```

## Paper -> Micro-Live Transition Checklist

1. [ ] Run paper daemon for 7+ days total
2. [ ] Achieve 10+ trades with 45%+ win rate
3. [ ] Portfolio MDD < 10%
4. [ ] Profit factor > 1.2
5. [ ] 2+ strategies net profitable
6. [ ] Run `MicroLiveCriteria.evaluate()` -> ready=True
7. [ ] Set `CT_UPBIT_ACCESS_KEY` and `CT_UPBIT_SECRET_KEY` env vars
8. [ ] Use `config/live.toml` (conservative risk, top 3 strategies, reduced capital)
9. [ ] Monitor kill switch state at `artifacts/kill-switch.json`
10. [ ] Run `pnl-report` command daily to track performance

## Commands Worth Knowing

```bash
# Grid search for optimal parameters
PYTHONPATH=src .venv/bin/python3 scripts/grid_search.py 30 mean_reversion

# Portfolio optimization
PYTHONPATH=src .venv/bin/python3 scripts/portfolio_optimizer.py 30

# Compound return simulation
PYTHONPATH=src .venv/bin/python3 scripts/compound_simulator.py 0.332 6000000

# PnL report from checkpoint
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli pnl-report --config config/daemon.toml

# All previous commands still work
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-multi --config config/daemon.toml
PYTHONPATH=src .venv/bin/python3 scripts/backtest_all.py 30
```

## Validation State

- `python3 -m pytest tests/ -q` -- 270 tests passing
- All linting clean

## Current Gaps / Risks

1. Grid search results need actual execution to determine optimal params (requires Upbit API calls)
2. Kill switch not yet integrated into MultiSymbolRuntime (module ready, wiring needed for live)
3. Telegram notifications not live-verified (no bot token configured)
4. Compound simulator assumes constant returns (real returns vary by regime)
5. Portfolio optimizer uses backtest data; live correlation may differ

## Recommended Next Moves

1. **Run grid search** on 90-day data to find optimal Mean Reversion params
2. **Run portfolio optimizer** to get data-driven wallet allocation
3. **Continue paper trading** for 5 more days to meet MicroLiveCriteria
4. **Integrate kill switch** into MultiSymbolRuntime for live mode
5. **Set up Telegram bot** for daily PnL reports
6. **Evaluate micro-live readiness** after 7 days total paper trading
