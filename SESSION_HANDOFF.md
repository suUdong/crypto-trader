# Session Handoff

Date: 2026-03-26 (FIRE Session #7)
Branch: `master`

## What Landed This Session (#7) — 10 User Stories in 3 Waves

### Wave 1: Signal Quality (US-023 to US-026)
- **US-023**: Adaptive RSI ceiling — strong momentum widens RSI ceiling from 60 toward 80
- **US-024**: Partial take-profit (scale-out) — sells 50% at half TP target, lets rest ride
- **US-025**: Widened mean reversion Bollinger (1.8→1.5 stddev) + RSI confirmation filter
- **US-026**: ADX trend strength filter — blocks entries when ADX < 20 (choppy market)

### Wave 2: Risk & Exit Management (US-028 to US-030)
- **US-028**: Volume-weighted entry filter (opt-in via volume_filter_mult) for momentum & vbreak
- **US-029**: Default ATR-based stops (atr_stop_multiplier 0→2.0) for dynamic stop distances
- **US-030**: Time-decay exit — closes underwater positions held > 75% of max_holding_bars

### Wave 3: Profit Locking & Comparison (US-032 to US-033)
- **US-032**: Trailing stop auto-activates at 2% after partial take-profit (locks remaining profits)
- **US-033**: `backtest-all` CLI — runs all strategies, outputs comparison table + JSON export

## Previous Session Deliverables (Still Active)

### Session #6: Risk & Backtest Tooling (13 stories)
- Drawdown sizing, regime-aware grid search, equity curve export
- Adaptive confidence, profit factor scoring, consecutive loss kill switch

### Session #5: Grid-WF + Consensus + Daemon Expansion
- `grid-wf` CLI, `ConsensusStrategy`, 3 new daemon wallets (9 total)

### Session #4: Walk-Forward CLI + PnL History
### Session #3: Per-Strategy PnL Tracking
### Session #2: Per-Symbol Wallets

## Architecture Updates

```
src/crypto_trader/
  config.py             # + adx_period, adx_threshold, volume_filter_mult in StrategyConfig
                        # + partial_tp_pct in RiskConfig
                        # bollinger_stddev 1.8→1.5, atr_stop_multiplier 0→2.0
  cli.py                # + backtest-all command
  models.py             # + partial_tp_taken on Position
  strategy/
    momentum.py         # + adaptive RSI ceiling, ADX filter, volume filter
    volatility_breakout.py  # + ADX filter, volume filter
    mean_reversion.py   # + RSI confirmation filter (oversold_floor+10)
    indicators.py       # + average_directional_index(), volume_sma()
  risk/
    manager.py          # + partial_take_profit, time_decay_exit, auto-trailing after partial TP
  wallet.py             # + partial TP sell logic, holding_bars passed to exit_reason
  backtest/
    grid_wf.py          # + ATR stop in backtest runner

tests/ (39 new tests)
  test_adaptive_rsi_ceiling.py    # 4 tests
  test_partial_take_profit.py     # 5 tests
  test_adx_indicator.py           # 8 tests
  test_mean_reversion_rsi_filter.py # 4 tests
  test_volume_filter.py           # 7 tests
  test_time_decay_exit.py         # 5 tests
  test_trailing_after_partial_tp.py # 4 tests
  test_backtest_all_cli.py        # 2 tests
```

## Validation State

- `pytest tests/ -q` → **578 passed, 3 skipped, 0 failures**
- +39 new tests this session across 3 commits
- 3 commits pushed to master

## Current Gaps / Risks

1. **3 new wallets not deployed** — daemon restart needed
2. **No closed trades yet** — strategies waiting for entry signals
3. ~~Momentum RSI conflict~~ **FIXED** — adaptive RSI ceiling
4. Kimchi premium uses simulated premium — live may diverge
5. Telegram not live-verified (no bot token)
6. **Volume filter disabled by default** — enable via `volume_filter_mult: 1.2` in config
7. **ATR stops now default** — may change exit behavior vs. fixed % stops

## Recommended Next Moves

1. **Restart daemon** with updated config (all 9 wallets + new features)
2. **Run `backtest-all`** to compare all strategies on current market data
3. **Run regime-aware grid-wf** — `crypto-trader grid-wf --strategy momentum --days 90`
4. **Enable volume filter** in production: set `volume_filter_mult: 1.2` in daemon.toml
5. **Monitor partial TP + trailing** — verify scale-out works as expected in paper trading
6. **Automate snapshots** — cron `crypto-trader snapshot` every 6h
7. **Telegram bot setup** for daily PnL alerts
8. **Paper trading 7 days** → micro-live gate by Apr 2
