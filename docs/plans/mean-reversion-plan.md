# Bollinger Mean Reversion Strategy — Design Plan

**Date**: 2026-03-29
**Priority**: P2
**Status**: Design
**Market Context**: F&G 12 (Extreme Fear), BTC sideways consolidation

---

## 1. Motivation

### Why Mean Reversion Now?

| Factor | Current State | Implication |
|--------|--------------|-------------|
| Fear & Greed Index | 12 (Extreme Fear) | Panic overshoots create reversion opportunities |
| BTC Regime | Sideways / Range-bound | Mean reversion outperforms trend-following in ranges |
| Volatility | Elevated but compressing | Bollinger squeeze → expansion cycle forming |
| Existing MR Performance | Baseline -5.42%, Tuned -1.91% | Current implementation is broken — needs redesign |

### Why the Existing `MeanReversionStrategy` Fails

The current `mean_reversion.py` (461 lines) suffers from:

1. **Indicator Bloat**: 10+ indicators (MACD, OBV, ADX, EMA50, VWAP, Keltner, CMF, Williams %R) create noise and conflicting signals. Too many optional confidence boosters dilute the core signal.
2. **Weak Entry Filter**: `near_lower_band` is too loose — touching the band is not enough. No squeeze detection means entries during trending breakdowns (band-riding).
3. **No Volatility Regime Filter**: Enters during band expansion (trending) when it should only trade during mean-reverting regimes (high noise ratio + low ADX).
4. **Exit Too Greedy**: Middle band target requires `pnl >= 2%` — misses quick 0.5-1.5% reversion trades that are the bread-and-butter of MR.
5. **No Squeeze Detection**: Missing the key Bollinger pattern — squeeze (low bandwidth) followed by expansion predicts regime shifts.
6. **Weekend/Macro Overrides Add Complexity Without Proven Edge**: 9 weekend override parameters, fear/greed adjustments — all untested.

---

## 2. Strategy Design: Bollinger Mean Reversion v2

### Core Thesis

> Price tends to revert to the mean after touching Bollinger Bands, **but only in
> range-bound (non-trending) markets**. The key is filtering out trending regimes
> where band touches lead to continuation, not reversion.

### 2.1 Entry Logic (BUY)

All conditions must be true (AND-chain):

```
1. BAND TOUCH:     close <= lower_band  OR  (prev_close < prev_lower AND close > lower_band)
2. RSI OVERSOLD:   rsi_oversold_floor <= RSI <= rsi_recovery_ceiling  (default: 25 <= RSI <= 40)
3. REGIME FILTER:  ADX < adx_ceiling  (default: 25, mean-reverting market)
4. SQUEEZE AWARE:  bbw_percentile < squeeze_threshold  OR  bbw expanding from squeeze
5. VOLUME CONFIRM: volume > volume_sma(20) * volume_mult  (default: 0.8x, not dead market)
```

**Confidence Scoring**:
```python
base_confidence = 0.55
+ band_distance_bonus    # deeper below lower band = +0.0 to +0.20
+ rsi_depth_bonus        # lower RSI (more oversold) = +0.0 to +0.15
+ squeeze_bonus          # if expanding from squeeze = +0.10
+ divergence_bonus       # RSI bullish divergence = +0.10
= final_confidence       # capped at 1.0
```

### 2.2 Exit Logic (SELL)

Priority-ordered (first match wins):

```
1. MAX HOLDING:      holding_bars >= max_holding_bars  (default: 24 bars = 24h on 1H)
2. MIDDLE BAND:      close >= middle_band * 0.995  AND  pnl >= 0.003 (0.3%)
3. UPPER BAND:       close >= upper_band  (full reversion overshoot)
4. RSI OVERBOUGHT:   RSI >= rsi_overbought  (default: 65, conservative)
5. BEARISH DIVERGE:  RSI bearish divergence detected
6. TREND SHIFT:      ADX crossed above 30  (market shifted to trending)
```

### 2.3 Key Differences from v1

| Aspect | v1 (Current) | v2 (Proposed) |
|--------|-------------|---------------|
| Indicators | 10+ (bloated) | 4 core (BB, RSI, ADX, Volume) |
| Entry RSI ceiling | `oversold_floor + 12` (loose) | Fixed 40 (tight) |
| Regime filter | Noise ratio only | ADX < 25 (stronger) |
| Squeeze detection | None | BBW percentile tracking |
| Exit target | Middle band + 2% PnL | Middle band + 0.3% PnL |
| Max holding | 48 bars | 24 bars (faster turnover) |
| Weekend overrides | 9 parameters | None (simplify first) |
| Macro integration | Fear/Greed with 4 params | Optional, phase 2 |
| Confidence model | 8 additive boosters | 4 focused boosters |
| Lines of code | 461 | Target ~200 |

---

## 3. Parameters

### 3.1 Strategy Parameters

| Parameter | Default | Range (Grid Search) | Description |
|-----------|---------|-------------------|-------------|
| `bollinger_window` | 20 | [15, 20, 25] | BB lookback period |
| `bollinger_stddev` | 2.0 | [1.5, 2.0, 2.5] | BB standard deviation multiplier |
| `rsi_period` | 14 | [10, 14] | RSI calculation period |
| `rsi_oversold_floor` | 25 | [20, 25, 30] | Minimum RSI for entry (avoid catching knives) |
| `rsi_recovery_ceiling` | 40 | [35, 40, 45] | Maximum RSI for entry |
| `rsi_overbought` | 65 | [60, 65, 70] | RSI exit threshold |
| `adx_period` | 14 | [14] | ADX period (fixed) |
| `adx_ceiling` | 25 | [20, 25, 30] | Max ADX for entry (low = range-bound) |
| `volume_filter_mult` | 0.8 | [0.5, 0.8, 1.0] | Min volume ratio vs SMA(20) |
| `max_holding_bars` | 24 | [16, 24, 36] | Max bars before forced exit |
| `squeeze_lookback` | 50 | [40, 50, 60] | Bars for BBW percentile calc |
| `squeeze_threshold_pct` | 20 | [15, 20, 25] | BBW percentile below which = squeeze |

### 3.2 Risk Parameters (Per-Wallet)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `stop_loss_pct` | 0.02 | 2% stop loss (tight for MR) |
| `take_profit_pct` | 0.03 | 3% take profit |
| `risk_per_trade_pct` | 0.01 | 1% of capital per trade |
| `atr_stop_multiplier` | 1.5 | ATR-based dynamic stop |
| `trailing_stop_pct` | 0.01 | 1% trailing stop |
| `cooldown_bars` | 3 | Bars between trades |

### 3.3 Grid Search Space

Total combinations: `3 * 3 * 2 * 3 * 3 * 3 * 3 * 3 * 3 * 3 = 39,366`
With pruning (skip invalid combos): ~8,000 effective runs

---

## 4. Implementation Plan

### Phase 1: Core Strategy (1-2 hours)

**New file**: `src/crypto_trader/strategy/bollinger_mean_reversion.py`

Do NOT modify the existing `mean_reversion.py` — create a new clean implementation.

```python
class BollingerMeanReversionStrategy:
    """Bollinger Band mean reversion for range-bound markets.

    Entry: lower band touch + RSI oversold + low ADX + volume confirm
    Exit: middle band reversion + RSI recovery
    """

    def __init__(
        self,
        config: StrategyConfig,
        regime_config: RegimeConfig | None = None,
        *,
        adx_ceiling: float = 25.0,
        squeeze_lookback: int = 50,
        squeeze_threshold_pct: float = 20.0,
    ) -> None: ...

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal: ...
```

**Key implementation details**:

1. **BBW Percentile Tracking**: Compute `bollinger_band_width()` over last `squeeze_lookback` bars. Current BBW's percentile rank determines squeeze state.

2. **ADX as Primary Regime Filter**: Replace noise ratio with ADX < ceiling. ADX is a cleaner trend strength measure for crypto (noise ratio is noisy itself on volatile assets).

3. **Simplified Confidence**: Only 4 components, each with clear contribution:
   - Band distance (how deep below lower band)
   - RSI depth (how oversold)
   - Squeeze state (expanding from squeeze = bonus)
   - RSI divergence (bullish divergence = bonus)

4. **Clean Exit Cascade**: Ordered by priority, no overlapping conditions.

### Phase 2: Factory & Config Integration (30 min)

1. Register `"bollinger_mr"` in `wallet.py:create_strategy()` factory
2. Add `adx_ceiling`, `squeeze_lookback`, `squeeze_threshold_pct` to extra_params handling
3. Add wallet config example to `daemon.toml` (commented out)

### Phase 3: Backtest Validation (1-2 hours)

```bash
# Quick single-symbol test
python scripts/backtest_single.py --strategy bollinger_mr --symbol KRW-BTC --days 90

# Grid search across key params
python scripts/auto_tune.py --strategy bollinger_mr --symbols KRW-BTC,KRW-ETH,KRW-SOL,KRW-XRP --days 90

# Walk-forward validation
python scripts/walk_forward.py --strategy bollinger_mr --folds 3
```

**Promotion Gate** (must pass all):
- [ ] OOS return > 0%
- [ ] Win rate >= 50%
- [ ] Sharpe ratio > 0.5
- [ ] Max drawdown < 5%
- [ ] Profit factor > 1.2
- [ ] >= 15 trades in 90 days (sufficient sample)

### Phase 4: Paper Trading (post-backtest)

If backtest passes promotion gate:
1. Add wallet to `daemon.toml` with small allocation (~10%, ~₩570K)
2. Run paper for 7 days minimum
3. Compare paper vs backtest drift (within tolerance?)

---

## 5. Backtest Expectations

### Target Metrics (90-day, 1H candles)

| Metric | Target | Rationale |
|--------|--------|-----------|
| Win Rate | 55-65% | MR has natural edge in sideways markets |
| Avg Win / Avg Loss | 1.0-1.5x | Small, frequent wins; tight stops |
| Sharpe Ratio | 0.8-1.5 | Moderate, consistent returns |
| Max Drawdown | < 3% | Tight stops + low ADX filter |
| Trades / 90d | 20-60 | Selective but not rare |
| Annual Return | 5-15% | Modest but consistent |
| Profit Factor | 1.3-2.0 | Achievable with good regime filtering |

### Why These Targets Are Realistic

1. **Current market favors MR**: F&G 12, sideways BTC = reversion setups forming daily
2. **Tight risk**: 2% stop, 3% TP, 24-bar max hold = fast turnover, limited exposure
3. **ADX filter eliminates worst trades**: Current MR enters during trends (the main failure mode)
4. **Shorter hold period**: 24 bars vs 48 = faster capital recycling, less exposure to regime shifts

### Risk Scenarios

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| Market shifts to strong trend | ADX filter blocks entries, 0 trades | Acceptable — strategy sits out |
| Flash crash below band | Stop loss at 2% limits damage | ATR stop provides dynamic floor |
| Squeeze leads to breakdown (not reversion) | Entry near band, price continues down | ADX ceiling + RSI floor prevents deepest entries |
| Low volume / dead market | Volume filter blocks entry | Minimum 0.8x average volume required |

---

## 6. Symbols & Timeframes

### Primary Targets

| Symbol | Rationale | Expected Edge |
|--------|-----------|---------------|
| KRW-BTC | Highest liquidity, cleanest reversion | Best regime filter performance |
| KRW-ETH | Strong BTC correlation, wider bands | More frequent band touches |
| KRW-SOL | Higher volatility, more opportunities | Wider bands = larger per-trade returns |
| KRW-XRP | Range-bound historically | Natural MR candidate |

### Timeframe

- **Primary**: 1H candles (60-minute) — matches existing daemon interval
- **Why not 15m/4H**: 15m = too noisy, commission drag kills edge. 4H = too few signals.

---

## 7. Wallet Configuration Template

```toml
# --- Bollinger Mean Reversion (P2, pending backtest validation) ---
# [[wallets]]
# name = "bmr_btc_wallet"
# strategy = "bollinger_mr"
# initial_capital = 570_000.0       # ~10% of total ₩5.7M
# symbols = ["KRW-BTC"]
#
# [wallets.strategy_overrides]
# bollinger_window = 20
# bollinger_stddev = 2.0
# rsi_period = 14
# rsi_oversold_floor = 25
# rsi_recovery_ceiling = 40
# rsi_overbought = 65
# adx_ceiling = 25
# volume_filter_mult = 0.8
# max_holding_bars = 24
# squeeze_lookback = 50
# squeeze_threshold_pct = 20
#
# [wallets.risk_overrides]
# stop_loss_pct = 0.02
# take_profit_pct = 0.03
# risk_per_trade_pct = 0.01
# atr_stop_multiplier = 1.5
# trailing_stop_pct = 0.01
# cooldown_bars = 3
```

---

## 8. Consensus Integration (Future)

Once validated standalone, can be added to consensus wallet:

```toml
[[wallets]]
name = "consensus_mr_wallet"
strategy = "consensus"
symbols = ["KRW-BTC"]

[wallets.strategy_overrides]
sub_strategies = ["bollinger_mr", "vpin"]
min_agree = 2
exit_mode = "any"
```

**Why VPIN + Bollinger MR**: VPIN detects order flow toxicity (smart money), Bollinger MR detects price extremes. Both agreeing = high-conviction contrarian entry.

---

## 9. Implementation Checklist

- [ ] Create `src/crypto_trader/strategy/bollinger_mean_reversion.py` (~200 lines)
- [ ] Add `bollinger_band_width` percentile helper to indicators (or inline)
- [ ] Register `"bollinger_mr"` in `wallet.py` factory
- [ ] Write unit tests: `tests/test_bollinger_mean_reversion.py`
- [ ] Run backtest on KRW-BTC 90-day
- [ ] Grid search top 3 symbols
- [ ] Walk-forward 3-fold validation
- [ ] Document results in `docs/backtest-bmr-results.md`
- [ ] If passing gate: add commented wallet to `daemon.toml`
- [ ] If passing gate: enable paper trading for 7-day validation

---

## 10. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-29 | New file, don't modify existing MR | Existing MR is too complex, cleaner to start fresh |
| 2026-03-29 | ADX as primary regime filter | Noise ratio underperforms on crypto volatility |
| 2026-03-29 | 24-bar max hold (down from 48) | Faster turnover, reduce regime shift exposure |
| 2026-03-29 | 0.3% PnL exit threshold (down from 2%) | Capture frequent small reversions |
| 2026-03-29 | No weekend/macro overrides in v2 | Simplify first, add complexity only if backtest justifies |
| 2026-03-29 | Squeeze detection via BBW percentile | Key Bollinger pattern missing from v1 |
