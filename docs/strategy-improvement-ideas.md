# Strategy Improvement Research — 3-Wallet System

**Date:** 2026-03-29
**Wallets:** vpin_eth (61.4%), momentum_sol (21.1%), volspike_btc (17.5%)
**Data source:** `artifacts/paper-trades.jsonl` (real trades 3/27-3/28)

---

## 1. Paper Trade Pattern Analysis

### 1.1 Trade Summary (Active Wallets Only)

| Wallet | Trades | W/L | Net PnL | Avg PnL% | Exit Reasons |
|--------|--------|-----|---------|-----------|--------------|
| vpin_eth | 3 | 1W/2L | +₩2,406 | -0.10% | rsi_overbought(2), atr_stop_loss(1) |
| momentum_sol | 1 | 0W/1L | -₩533 | -1.72% | atr_stop_loss(1) |
| volspike_btc | 0 | — | ₩0 | — | no trades generated |

### 1.2 Entry Time Analysis (UTC → KST)

| Trade | Entry UTC | Entry KST | Result | Note |
|-------|-----------|-----------|--------|------|
| vpin_eth #1 | 22:00 | 07:00 | **+1.60%** | Morning KST, held 18h |
| vpin_eth #2 | 16:00 | 01:00 | -0.35% | Deep night KST, exited immediately |
| vpin_eth #3 | 16:00 | 01:00 | -1.56% | Deep night KST, 7h hold → ATR stop |
| momentum_sol | 21:00 | 06:00 | -1.72% | Early morning KST, 2h hold → ATR stop |

**Key finding:** 2/3 vpin_eth losses entered at 01:00 KST (deep night, low Upbit liquidity).
The only winner entered at 07:00 KST (morning session).

### 1.3 Loss Trade Common Patterns

1. **Low-liquidity time entries:** 3/3 losses entered between 01:00-06:00 KST
2. **ATR stop-loss dominance:** 2/3 losses hit ATR stops — stops may be too tight for
   overnight volatility (ATR mult 1.5 with hourly candles)
3. **Rapid re-entry:** vpin_eth #2 entered the same bar as #1's exit (16:00 UTC) — cooldown
   bars (4) didn't prevent this because it's a different cycle's entry evaluation
4. **All losses are long-only** in a sideways/slightly-bearish micro regime

### 1.4 Win Trade Common Patterns

1. **Morning KST entry (07:00):** Aligns with Upbit's active trading hours
2. **Longer hold period (18 bars):** Patience paid — let the trend develop
3. **RSI overbought exit:** Clean technical exit at +1.6%

---

## 2. Strategy-by-Strategy Code Review & Weakness Analysis

### 2.1 VPIN (ETH) — `strategy/vpin.py`

**Entry Logic:**
- VPIN < 0.45 (low toxicity) + momentum > 0.0003 + RSI 20-65 + EMA(20) trend up
- Moderate zone: VPIN < mid_threshold + 2x momentum required

**Exit Logic:**
- VPIN >= 0.7 (toxicity exit), RSI >= 75 (overbought), max 24 bars

**Weaknesses Identified:**

| # | Weakness | Impact | Evidence |
|---|----------|--------|----------|
| V1 | No time-of-day filter | Enters during low-liquidity KST night hours | 2/3 losses at 01:00 KST |
| V2 | EMA trend uses only 4-bar slope | Too short; easily fooled by noise in 1H candles | EMA rising check: `ema[-1] > ema[-4]` |
| V3 | No volume confirmation on entry | VPIN measures order flow but ignores absolute volume level | Can enter on thin volume with "good" VPIN |
| V4 | VPIN bucket_count=24 on 1H candles = 24H window | Only 1-day lookback; may miss multi-day flow shifts | Short memory for flow toxicity |
| V5 | No multi-timeframe confirmation | Only uses 1H candles; no 4H/daily trend filter | Can enter counter-trend on higher TF |
| V6 | Confidence formula is simple linear | `0.5 + (vpin_low - vpin) * 2` doesn't account for regime | Same confidence in bull vs sideways |
| V7 | No ADX usage despite parameter existing | `adx_threshold=15.0` set but VPIN's `__init__` defaults to `0.0` | ADX filter effectively disabled |

### 2.2 Momentum (SOL) — `strategy/momentum.py`

**Entry Logic:**
- momentum >= entry_threshold (0.005) + RSI 20-75 (adaptive ceiling)
- EMA(50) macro trend gate + ADX(12) + MACD + OBV + VWAP + Keltner + Williams %R + CMF
- Volume filter, fear & greed block

**Exit Logic:**
- momentum <= exit_threshold (-0.01), RSI >= 75, Williams %R > -5, max 48 bars

**Weaknesses Identified:**

| # | Weakness | Impact | Evidence |
|---|----------|--------|----------|
| M1 | No time-of-day filter | Entered at 06:00 KST (pre-market) | Only trade was a loss at low-liquidity hour |
| M2 | Too many indicators, unclear hierarchy | 10+ indicators but most only boost confidence by 0.05 | Indicator soup — hard to backtest which matter |
| M3 | ADX threshold too low (12.0) | Permits entry in very weak trends | SOL often range-bound; ADX 12 doesn't filter |
| M4 | volume_filter_mult=0.0 (disabled) | No volume gate at all for SOL wallet | Can enter on dead volume |
| M5 | EMA(50) requires 50 candles but SOL wallet only gets 200 | Works, but leaves only 150 effective bars for signal | Thin margin with 1H candles |
| M6 | Adaptive RSI ceiling can widen to 80 | `rsi_ceiling + excess * 1000` — can spike RSI ceiling on strong momentum | May enter near overbought |
| M7 | Fear & Greed threshold=20 (extreme fear only) | Doesn't block entries in moderate fear (20-35) | Paper loss during fear_greed ~25 range |
| M8 | No regime-aware position sizing | Same size in bull, sideways, bear after regime adjustment | Regime adjusts thresholds but not size |

### 2.3 Volume Spike (BTC) — `strategy/volume_spike.py`

**Entry Logic:**
- vol_ratio >= spike_mult (2.0) + body_ratio >= 0.2 + momentum > 0 + RSI < 72
- ADX(20) filter + MACD + OBV + CMF + VWAP + EMA(50)

**Exit Logic:**
- momentum reversal, RSI overbought, bearish volume spike on high volume, max 36 bars

**Weaknesses Identified:**

| # | Weakness | Impact | Evidence |
|---|----------|--------|----------|
| S1 | Zero trades in paper period | spike_mult=2.0 still too restrictive for BTC hourly | No data to validate |
| S2 | AND-chain of filters too strict | Need spike AND body AND momentum AND RSI AND ADX all passing | Each filter reduces universe multiplicatively |
| S3 | No distinction between accumulation vs distribution spikes | Only checks `momentum > 0` — misses bearish-to-bullish reversals | Volume spike after selloff could be accumulation |
| S4 | body_ratio 0.2 is lenient but momentum > 0 is strict | Allows doji-like candles (0.2) but then requires positive momentum | Contradictory: weak body + positive momentum? |
| S5 | No time-of-day awareness | BTC volume spikes during US session (21:00-05:00 UTC) may be noise | Not all spikes are created equal |
| S6 | EMA(50) macro trend blocks mean-reversion spikes | Spike after selloff below EMA50 is filtered out | Misses V-reversal opportunities |
| S7 | spike_mult uses raw ratio — no percentile normalization | 2x avg means different things in quiet vs volatile periods | Should use rolling percentile (e.g., top 5%) |

---

## 3. Improvement Proposals

### 3.1 VPIN ETH Improvements

#### P1: KST Time-of-Day Filter
```
Block entries during 00:00-08:00 KST (Sat-Mon already filtered by regime.py)
Rationale: 2/3 losses at 01:00 KST. Upbit volume drops 60%+ after midnight.
Implementation: Add `is_low_liquidity_kst(candle.timestamp)` check before entry.
Already have `is_weekend_kst()` in regime.py — extend pattern.
```

#### P2: Activate ADX Filter
```
Current: adx_threshold defaults to 0.0 in VPINStrategy.__init__
Fix: Pass adx_threshold=15.0 from wallet config to VPIN constructor
Impact: Blocks entries in trendless markets (ADX < 15)
```

#### P3: Volume Confirmation Gate
```
Add: volume > 0.8x SMA(20) as minimum volume floor for entry
Rationale: VPIN can show "safe" reading on thin volume (denominator shrinks)
Implementation: Use existing volume_sma() from indicators.py
```

#### P4: Longer EMA Slope Check
```
Current: ema[-1] > ema[-4] (4-bar slope on 1H = 4 hours)
Proposed: ema[-1] > ema[-8] (8-bar slope = 8 hours, more stable)
Alternative: Use EMA(50) like momentum strategy for consistency
```

#### P5: Multi-Timeframe Trend Filter
```
Compute 4H trend from 1H candles: aggregate every 4 candles → check EMA direction
Block entry if 4H trend is down while 1H shows up (divergence = trap)
```

### 3.2 Momentum SOL Improvements

#### P1: KST Time-of-Day Filter (Same as VPIN)
```
Block entries 00:00-08:00 KST
The only paper trade loss was at 06:00 KST
```

#### P2: Indicator Pruning — Tiered Confirmation
```
Current: 10+ indicators each adding 0.05 confidence → noise
Proposed tier system:
  Tier 1 (MUST pass): momentum + RSI + EMA50 trend + ADX
  Tier 2 (confidence boost): MACD + OBV + volume ratio
  Tier 3 (drop or keep for logging only): Williams %R, Keltner, CMF, VWAP
Benefit: Simpler logic, easier to backtest, fewer false signals
```

#### P3: Raise ADX Threshold
```
Current: adx_threshold=12.0
Proposed: adx_threshold=20.0 (match BTC wallet)
Rationale: SOL is volatile but often range-bound. ADX 12 barely filters anything.
```

#### P4: Enable Volume Filter
```
Current: volume_filter_mult=0.0 (disabled)
Proposed: volume_filter_mult=0.8 (require 80% of SMA volume)
Rationale: Confirms institutional participation, not just noise
```

#### P5: Tighten Fear & Greed Block
```
Current: block at F&G < 20 (extreme fear only)
Proposed: block at F&G < 30 (include moderate fear)
Rationale: momentum_eth was disabled because it entered during F&G ~25
```

#### P6: Cap Adaptive RSI Ceiling
```
Current: rsi_ceiling + excess * 1000 can push ceiling to 80
Proposed: Cap multiplier so ceiling never exceeds rsi_overbought - 5
Prevents entering right before overbought exit trigger
```

### 3.3 Volume Spike BTC Improvements

#### P1: Relax Filter Chain — Use OR for Secondary Filters
```
Current: ALL of (spike + body + momentum + RSI + ADX) must pass
Proposed: spike + body required, then 2-of-3 from (momentum > 0, RSI < 72, ADX > 20)
Rationale: AND-chain produces zero trades. Relaxing secondary filters increases trade count.
```

#### P2: Percentile-Based Spike Detection
```
Current: vol_ratio >= 2.0 (fixed multiplier)
Proposed: vol_ratio >= percentile(95) of rolling 50-bar volume
Rationale: Adapts to changing volatility regimes. 2x in quiet period ≠ 2x in active period.
Implementation: Add rolling_percentile() to indicators.py
```

#### P3: Directional Filter After Spike
```
Current: Only checks current candle body + momentum > 0
Proposed: Wait 1 bar after spike for confirmation:
  - If next candle closes above spike candle high → buy (breakout confirmed)
  - If next candle closes below spike candle low → skip (distribution)
Tradeoff: Slightly later entry, but much higher directional accuracy
```

#### P4: Distinguish Accumulation vs Distribution Volume
```
Add OBV divergence check:
  - Spike + OBV rising = accumulation (bullish)
  - Spike + OBV falling = distribution (skip)
CMF already computed but only used for confidence. Make it a gate:
  - Require CMF > 0 for entry (money flowing in)
```

#### P5: Remove EMA(50) Gate or Make Optional
```
Current: `macro_trend_up` only boosts confidence (+0.05) but doesn't block
Actually harmless — but if we add a blocking gate, V-reversal spikes get filtered.
Keep as confidence boost only (current behavior is fine).
```

#### P6: Session-Aware Spike Weighting
```
BTC hourly volume profile (Upbit):
  - Peak: 09:00-11:00 KST, 21:00-01:00 KST (US open overlap)
  - Trough: 03:00-07:00 KST
A 2x spike at 04:00 KST is less meaningful than 2x at 10:00 KST.
Weight spike_mult inversely by session: require higher mult during low-volume hours.
```

---

## 4. Cross-Strategy Filter Ideas

### 4.1 Unified KST Time Filter

All three wallets should share a time-of-day gate:

```python
# In regime.py or a new time_filter.py
UPBIT_ACTIVE_HOURS_KST = range(9, 24)  # 09:00-23:59 KST

def is_active_session_kst(dt: datetime) -> bool:
    """True during Upbit high-liquidity hours."""
    kst_time = dt.astimezone(KST)
    return kst_time.hour in UPBIT_ACTIVE_HOURS_KST
```

**Recommended policy:**
- **Hard block** new entries during 00:00-08:00 KST (keep exits active)
- Weekend filter already exists in `regime.py` — extend, don't duplicate

### 4.2 Volume Profile Filter

Add a rolling volume profile that classifies current volume relative to
the same hour's historical average (e.g., 7-day same-hour SMA):

```
If current_volume < 0.5 * same_hour_7d_avg → block entry (dead market)
If current_volume > 2.0 * same_hour_7d_avg → flag as unusual (potential spike)
```

This is more nuanced than raw SMA and accounts for intraday patterns.

### 4.3 Correlation-Based Simultaneous Entry Limit

**Problem:** ETH and SOL are ~0.85 correlated with BTC. Entering both simultaneously
is effectively 2x the same bet.

**Proposal:**
- Already have `max_cluster_exposure=2` in `multi_runtime.py` (recently tightened from 6)
- Add explicit correlation check: if ETH position is open, require SOL signal
  confidence > 0.8 (higher bar) to enter
- Group assets: `{BTC, ETH, SOL}` are "crypto_major" cluster
- Max 2 concurrent positions across the cluster (already configured)

### 4.4 Regime-Gated Entry Strictness

| Regime | Entry Policy |
|--------|-------------|
| Bull | Normal thresholds — let momentum run |
| Sideways | Tighten: require ADX > 25, confidence > 0.6 |
| Bear | Block new entries entirely (or require 2x normal momentum) |

The current `RegimeDetector.adjust()` already shifts thresholds but the changes
are modest (+/-0.003 momentum, +/-10 RSI). Consider more aggressive bear blocking.

### 4.5 Macro-Intelligence Integration

The `macro/client.py` already provides `MacroSnapshot` with:
- `fear_greed_index`: Only used by momentum strategy
- Extend to VPIN and volume_spike: block entry when F&G < 25 across all strategies

---

## 5. Priority Roadmap

| Priority | Improvement | Wallet | Expected Impact | Effort |
|----------|------------|--------|-----------------|--------|
| **P0** | KST time filter (block 00:00-08:00) | All | Eliminates 3/3 observed losses | Low |
| **P0** | Activate ADX filter in VPIN | vpin_eth | Filters trendless entries | Trivial |
| **P1** | Enable volume_filter_mult for SOL | momentum_sol | Confirms real participation | Trivial |
| **P1** | Relax volspike AND-chain to 2-of-3 | volspike_btc | Generates actual trades | Medium |
| **P1** | Raise momentum ADX to 20 | momentum_sol | Filters weak-trend entries | Trivial |
| **P1** | Tighten F&G block to 30 | momentum_sol | Prevents fear-regime entries | Trivial |
| **P2** | Indicator pruning (tier system) | momentum_sol | Simpler, more testable | Medium |
| **P2** | Percentile spike detection | volspike_btc | Adaptive to regime | Medium |
| **P2** | Post-spike confirmation bar | volspike_btc | Higher directional accuracy | Medium |
| **P2** | Volume profile (same-hour avg) | All | Intraday-aware filtering | Medium |
| **P3** | Multi-TF trend filter | vpin_eth | Reduces counter-trend entries | High |
| **P3** | Accumulation/distribution OBV gate | volspike_btc | Better spike classification | Medium |
| **P3** | Regime-gated bear blocking | All | Prevents bear-market losses | Medium |

---

## 6. Backtest Validation Checklist

Before implementing any change to `daemon.toml`:

- [ ] Run 90-day backtest with proposed params
- [ ] Compare Sharpe, WR, MDD, PF against current baseline
- [ ] Verify trade count doesn't drop below 10/90d (statistical minimum)
- [ ] Walk-forward validation (train 60d, test 30d)
- [ ] Paper trade for 48h minimum before live promotion
- [ ] Update `artifacts/backtest-baseline.json` with new results
