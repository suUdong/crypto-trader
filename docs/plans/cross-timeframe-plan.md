# Cross-Timeframe Momentum (CTF-Momentum) Strategy — Design Plan

**Date**: 2026-03-29
**Priority**: P2
**Status**: Design
**Source**: Research #3 — multi-timeframe momentum alignment

---

## 1. Current State

### What Exists

| Component | File | Status |
|-----------|------|--------|
| MomentumStrategy | `strategy/momentum.py` | ✅ Single-TF (1h), production on SOL |
| EMA(50) macro gate | `strategy/momentum.py:108-118` | ✅ Crude higher-TF proxy |
| RegimeDetector | `strategy/regime.py` | ✅ Dual-window (10/30 bar) on single TF |
| PyUpbit client | `data/pyupbit_client.py` | ✅ Supports all intervals |
| Indicators | `strategy/indicators.py` | ✅ EMA, momentum, RSI, ADX, etc. |
| ConsensusStrategy | `strategy/consensus.py` | ✅ Weighted voting framework |
| Backtest engine | `backtest/engine.py` | ⚠️ Single-TF only |
| Multi-TF data fetch | — | ❌ Not implemented |
| Cross-TF strategy | — | ❌ Not implemented |

### Current Limitations

1. **Single timeframe**: Pipeline fetches only `minute60` candles (200 bars)
2. **EMA(50) as proxy**: 50-bar EMA on 1h candles ≈ ~2-day trend, not true 4h/1d alignment
3. **No trend confluence**: Cannot confirm if 4h and daily trends agree with 1h entry
4. **False signals**: 1h momentum can trigger entries against higher-TF downtrends

---

## 2. Upbit Multi-Timeframe API Feasibility

### 2.1 Supported Intervals

| Interval | PyUpbit String | Max Count | Notes |
|----------|---------------|-----------|-------|
| 1 hour | `"minute60"` | 200 | Current production TF |
| 4 hour | `"minute240"` | 200 | 200 bars ≈ 33 days |
| 1 day | `"day"` | 200 | 200 bars ≈ 6.5 months |

### 2.2 API Cost

- 3 calls per symbol per cycle (1h + 4h + 1d) vs current 1 call
- Rate limit: 10 req/sec per IP — fits comfortably (daemon polls every 60s)
- Added latency: ~200-300ms total for 2 extra calls (acceptable)

### 2.3 Data Requirements

| Timeframe | Purpose | Min Candles Needed |
|-----------|---------|-------------------|
| 1h | Entry trigger + short-term momentum | 50 (for EMA50 + lookback) |
| 4h | Medium-term trend confirmation | 50 (for EMA50) |
| 1d | Long-term trend direction | 50 (for EMA50) |

---

## 3. Strategy Design

### 3.1 Core Concept

**Trend alignment filter**: Only enter when EMA trends on multiple timeframes agree.

Each timeframe produces a **trend vote**: BULLISH (+1), NEUTRAL (0), or BEARISH (-1).

```
Trend Vote = sign(close - EMA(period)) * (1 if EMA rising else 0.5)

EMA rising := EMA[-1] > EMA[-4]  (4-bar lookback on that TF)
```

### 3.2 Alignment Scoring

| Alignment | Score | Action | Confidence Modifier |
|-----------|-------|--------|-------------------|
| 3/3 agree bullish | +3 | **Strong BUY gate open** | +0.15 |
| 2/3 agree bullish | +2 | **Normal BUY gate open** | +0.05 |
| Mixed / 1 agree | ≤1 | **BUY blocked** | — |
| 2/3+ bearish | ≤-2 | **Force exit if holding** | — |

### 3.3 Detailed Logic

```python
class CrossTimeframeMomentumStrategy:
    """
    Wraps MomentumStrategy with multi-timeframe trend alignment gate.

    Data flow:
      1. Fetch 1h, 4h, 1d candles in parallel
      2. Compute EMA trend vote per timeframe
      3. Sum votes -> alignment_score
      4. If alignment_score >= min_alignment (default 2):
           delegate to MomentumStrategy.evaluate(candles_1h)
           boost confidence by alignment modifier
         Else:
           HOLD (trend not confirmed)
      5. Override exit: if alignment_score <= -2, force SELL
    """
```

### 3.4 Configuration

```toml
# New fields in [strategy] or [wallets.strategy_overrides]
ctf_ema_period = 20          # EMA period for trend detection (per TF)
ctf_ema_rising_lookback = 4  # bars to check if EMA is rising
ctf_min_alignment = 2        # minimum bullish votes to allow entry (2 or 3)
ctf_intervals = ["minute60", "minute240", "day"]  # timeframes to check
ctf_force_exit_threshold = -2  # alignment score to force exit
```

### 3.5 Confidence Scoring

```
base_confidence = MomentumStrategy.confidence  (from 1h evaluation)

if alignment == 3:
    confidence = min(1.0, base_confidence + 0.15)
elif alignment == 2:
    confidence = min(1.0, base_confidence + 0.05)
```

---

## 4. Architecture

### 4.1 New Components

```
src/crypto_trader/strategy/cross_timeframe_momentum.py   # New strategy
src/crypto_trader/strategy/timeframe.py                   # TF trend helpers
tests/test_cross_timeframe_momentum.py                    # Tests
```

### 4.2 Class Diagram

```
CrossTimeframeMomentumStrategy
├── MomentumStrategy (delegate for 1h signal generation)
├── TimeframeTrendAnalyzer (new)
│   ├── compute_trend_vote(candles, ema_period) -> TrendVote
│   └── compute_alignment(votes: list[TrendVote]) -> int
└── MarketDataClient ref (for fetching multi-TF candles)
```

### 4.3 Data Flow

```
Pipeline.run_once(symbol)
  │
  ├── market_data.get_ohlcv(symbol, "minute60", 200)   ─┐
  ├── market_data.get_ohlcv(symbol, "minute240", 50)    ─┤  parallel
  └── market_data.get_ohlcv(symbol, "day", 50)          ─┘
  │
  ▼
TimeframeTrendAnalyzer
  ├── trend_1h  = vote(candles_1h, ema_period=20)
  ├── trend_4h  = vote(candles_4h, ema_period=20)
  └── trend_1d  = vote(candles_1d, ema_period=20)
  │
  alignment_score = sum(votes)
  │
  ▼
if alignment_score >= min_alignment:
  MomentumStrategy.evaluate(candles_1h, position)
    → Signal with boosted confidence
else:
  Signal(HOLD, "ctf_alignment_blocked")
```

### 4.4 Pipeline Integration

**Option A (Recommended): Strategy-level integration**

`CrossTimeframeMomentumStrategy` receives `MarketDataClient` ref and fetches extra TFs internally.
- Pro: No pipeline changes needed, works with existing backtest
- Con: Strategy knows about data fetching (breaks pure strategy pattern slightly)

**Option B: Pipeline-level multi-TF fetch**

Pipeline fetches all TFs and passes them to strategy.
- Pro: Clean separation
- Con: Requires pipeline protocol changes, breaks `evaluate(candles, position)` signature

**Decision**: Option A — strategy fetches its own supplementary data. The 1h candles still come through the normal pipeline path; 4h and 1d are fetched on-demand by the strategy with caching.

### 4.5 Caching

Multi-TF candles change slowly relative to the 1h poll cycle:
- **4h candles**: Cache for 60 min (only changes every 4 hours)
- **1d candles**: Cache for 4 hours (only changes once per day)
- Use simple dict cache keyed by `(symbol, interval)` with TTL

---

## 5. Synergy & Conflict Analysis

### 5.1 vs Existing MomentumStrategy

| Aspect | momentum | ctf_momentum |
|--------|----------|-------------|
| Entry gate | EMA(50) macro + regime | 3-TF alignment + regime |
| False signal rate | Medium (1h noise) | Low (TF confluence) |
| Trade frequency | Higher | Lower (more selective) |
| Best regime | Bull/sideways | Strong trends (bull/bear) |
| Latency to enter | Fast (1 TF) | Slightly slower (3 TF checks) |

**Synergy**: CTF-momentum is a stricter filter — pairs well in consensus with looser strategies (vpin, volume_spike) to reduce false entries.

**Conflict**: Should NOT run alongside plain `momentum` on same symbol — they share the same core signal with different gating. Use one or the other per wallet.

### 5.2 vs ConsensusStrategy

CTF-momentum can be a sub-strategy in consensus voting:
```toml
[wallets.strategy_overrides]
sub_strategies = ["ctf_momentum", "vpin", "volume_spike"]
min_agree = 2
```

This gives a "strong trend + volume confirmation" combo.

### 5.3 vs RegimeDetector

CTF alignment naturally captures regime (3-TF bullish ≈ bull regime), but RegimeDetector adds weekend/fear-greed adjustments. Keep both — they serve different purposes:
- RegimeDetector: threshold adjustments (adaptive params)
- CTF alignment: entry gating (go/no-go)

### 5.4 Macro Integration

Cross-TF alignment + macro regime creates a two-layer filter:
1. **CTF gate**: Is the chart trending? (technical)
2. **Macro gate**: Is the macro environment favorable? (fundamental)

Both must pass for entry. This should dramatically reduce losses in bear/fear environments (the ETH wallet problem — entered against extreme-fear regime).

---

## 6. Backtest Considerations

### 6.1 Challenge

Backtest engine currently loops through a single candle list. CTF strategy needs 3 TF candle lists aligned by timestamp.

### 6.2 Solution

```python
# In backtest engine, pre-fetch all 3 TFs
candles_1h = cache.load(symbol, "minute60", days)
candles_4h = cache.load(symbol, "minute240", days)
candles_1d = cache.load(symbol, "day", days)

# For each 1h bar, find corresponding 4h and 1d bars
# by timestamp alignment (floor to TF boundary)
```

The strategy's internal caching handles this automatically in live mode.
For backtest, provide a `MockMarketDataClient` that serves from pre-loaded candle lists.

### 6.3 Validation Targets

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Win rate | > 55% | Higher than plain momentum (50%) |
| Sharpe | > 1.5 | Match or beat momentum SOL (1.55) |
| Max drawdown | < 8% | Tighter than current 5% daily limit |
| Trade count / 90d | > 10 | Must not be too selective |
| False signal reduction | > 30% vs momentum | Primary value proposition |

---

## 7. Implementation Steps

### Phase 1: Foundation (P2)

1. **`strategy/timeframe.py`**: `TrendVote` enum, `compute_trend_vote()`, `compute_alignment()`
2. **`strategy/cross_timeframe_momentum.py`**: Main strategy class wrapping MomentumStrategy
3. **Register**: Add `"ctf_momentum"` to `wallet.py:create_strategy()`, `config.py:valid_strategies`, `cli.py` choices
4. **Config**: Add `ctf_*` fields to `StrategyConfig`, `_STRATEGY_EXTRA_OVERRIDE_FIELDS`
5. **Tests**: Unit tests for trend vote, alignment scoring, gate logic

### Phase 2: Backtest (P2)

6. **Candle cache**: Extend `candle_cache.py` to support multi-TF pre-loading
7. **Backtest adapter**: `MockMarketDataClient` for multi-TF backtest
8. **Validate**: Run backtest on BTC, ETH, SOL — compare vs plain momentum

### Phase 3: Production (P3)

9. **daemon.toml**: Add `ctf_momentum` wallet config (paper first)
10. **Monitoring**: Log alignment scores, track alignment-blocked trades
11. **Grid search**: Optimize `ctf_ema_period`, `ctf_min_alignment` per symbol
12. **Promote**: If paper results meet targets, allocate capital

---

## 8. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Over-filtering (too few trades) | Low returns | `ctf_min_alignment=2` allows 2/3 consensus |
| API rate limit with 3x calls | Missed cycles | TTL caching reduces actual calls to ~1.5x |
| TF misalignment in backtest | Inaccurate results | Strict timestamp floor alignment |
| Stale higher-TF data | Late exits | 4h cache=60min, 1d cache=4h (conservative) |
| Complexity overhead | Maintenance burden | Delegates to existing MomentumStrategy for core logic |

---

## 9. Open Questions

1. **EMA period per TF**: Should each TF use the same EMA period (20) or different (e.g., 1h=20, 4h=50, 1d=200)?
2. **Weighted votes**: Should daily trend carry more weight than 1h? (e.g., 1h=1, 4h=1.5, 1d=2)
3. **Partial alignment exit**: When alignment drops from 3 to 2 mid-trade, should we tighten stops?
4. **ADX per TF**: Should we also check ADX on higher TFs to confirm trend strength?
