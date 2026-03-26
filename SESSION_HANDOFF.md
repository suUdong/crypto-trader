# Session Handoff

Date: 2026-03-26 (FIRE Session #11)
Branch: `master`

## What Landed This Session (#11) — 25+ Features, 81 New Tests, 7 Waves

### Wave 1: Backtest Accuracy Fixes + Sharpe + MACD (21e78a3)
- **BUG FIX**: `holding_bars` now passed to `exit_reason()` — time_decay_exit was dead code
- **BUG FIX**: `tick_cooldown()` called each bar — cooldown_bars had no effect
- **BUG FIX**: `in_cooldown` and `is_auto_paused` checked before position opens
- Sharpe ratio added to `BacktestResult` (annualized, 8760 hrs/yr)
- MACD(12/26/9) indicator with `_ema()` helper
- MACD confidence boost (+0.1) in CompositeStrategy
- Regime breakdown (bull/sideways/bear win rate) in backtest-all CLI
- +17 tests (686)

### Wave 2: Risk Reduction + Signal Consistency (69ba628)
- **Breakeven stop**: exit at entry price if position ever gained >=1.5%
- MACD confirmation for MomentumStrategy (+0.1 confidence boost)
- Correlation guard in backtest-all: warns when strategy pairs have r>0.8
- +10 tests (696)

### Wave 3: Strategy Diversification (b878dbe)
- **New EMACrossoverStrategy**: EMA(9)/EMA(21) trend-following with MACD boost
- Registered ema_crossover in wallet, CLI, config validation, backtest-all
- MACD confirmation added to VolatilityBreakoutStrategy
- **8 strategies** now available for consensus and backtest-all ranking
- +10 tests (706)

### Wave 4: Dynamic Risk + Sortino (ec53a1f)
- **Dynamic stop tightening**: after 3+ consecutive losses, stop tightens 20%
- Sortino ratio added to `BacktestResult` (downside-only volatility)
- +12 tests (718)

### Wave 5: Calmar + Complete MACD Coverage (1f032a6)
- Calmar ratio added to `BacktestResult` (annualized return / max drawdown)
- MACD confirmation for MeanReversionStrategy — all 5 core strategies now have MACD
- ema_crossover param grids added to grid-wf for optimization
- +11 tests (729)

### Wave 6: Consensus Enhancement + Win Streak (7199db7)
- Default consensus now uses 3 sub-strategies: momentum, vpin, ema_crossover
- Win-streak position boost: +5% per consecutive win after 3+ (max 1.3x)
- Complements loss-streak stop tightening for asymmetric risk/reward
- +8 tests (737)

### Wave 7: Advanced Signals + Portfolio Risk (7ade09b)
- RSI divergence detection: bullish (price lower low + RSI higher low) and bearish
- Portfolio heat tracking: total position risk / equity for exposure control
- Fixed daemon heartbeat tests for new config fields
- +13 tests (750)

## Impact on Trading
- **Backtest accuracy**: 3 critical bugs fixed — previous results were overly optimistic
- **Risk reduction**: Breakeven stop, dynamic stop tightening, portfolio heat, cooldown, auto-pause
- **Signal quality**: MACD on all 5 core strategies, RSI divergence detection
- **Strategy diversity**: 8 independent strategies + enhanced consensus (3 sub-strategies)
- **Position sizing**: Win-streak boost + loss-streak reduction = asymmetric edge
- **Metrics completeness**: Sharpe, Sortino, Calmar all on BacktestResult

## Available Strategies (8 + consensus)
momentum, mean_reversion, composite, volatility_breakout, vpin, obi, ema_crossover, kimchi_premium

## Full Metrics on BacktestResult
Sharpe, Sortino, Calmar, Profit Factor, Win Rate, Max Drawdown,
Max Consecutive Losses/Wins, Avg/Max Trade Duration, Payoff Ratio,
Expected Value per Trade, Recovery Factor, Tail Ratio

## Previous Sessions (Still Active)
- Session #10: Composite scoring, grid-wf-all, strategy-dashboard, Kelly
- Session #9: Auto-disable wallets, PnL alerts, snapshot automation
- Session #8: Risk protection, adaptive management
- Session #7: Signal quality, risk management
- Sessions #2-6: Core infrastructure

## Validation: **750 passed, 3 skipped, 0 failures**

## Recommended Next Moves
1. Re-run `crypto-trader backtest-all` — results differ due to 3 backtest bug fixes
2. `crypto-trader strategy-dashboard` → compare regime breakdown, new strategies
3. `crypto-trader grid-wf-all --days 90 --top-n 5` → re-optimize with corrected backtests
4. Integrate RSI divergence into mean_reversion strategy for better entry timing
5. Use portfolio_heat in multi-symbol runtime to limit total exposure
6. Paper trade 7 days → micro-live gate by Apr 2
