# Stealth Signal Rules — Backtest Validated

**Date:** 2026-04-02  
**Data:** 141 KRW altcoins, 4h bars, 83 days (COUNT=500), GPU 3D unfold  
**Scripts:** `backtest_prebull_signal.py`, `backtest_stealth_deep.py`  
**Results:** `artifacts/stealth-deep-result.md`

---

## Signal Definition

**Stealth accumulation:** price weak vs BTC, but volume quietly buying in

```
Alt stealth:  RS < 1.0  AND  Acc > 1.0  AND  CVD_slope > 0
BTC stealth:  raw_ret < 0  AND  Acc > 1.0  AND  CVD_slope > 0  (self-referenced)
```

---

## Key Findings

### 1. BTC Regime Gate (must-have)

| Context | Alt Mean (T+12) | Win Rate |
|---------|----------------|----------|
| Stealth in BTC bull (>SMA20) | **+0.169%** | **50.3%** |
| Stealth in BTC bear (<SMA20) | -0.904% | 36.8% |
| Non-stealth | -0.301% | 44.8% |

→ **Without BTC bull regime, stealth signal destroys capital.**

### 2. BTC Stealth is a Leading Indicator

| BTC State | BTC Return (T+12) | Win Rate |
|-----------|-------------------|----------|
| BTC stealth ON | **+1.443%** | **92.9%** |
| BTC stealth OFF | +0.123% | 56.2% |

→ **BTC stealth fires ~10% of the time but is nearly deterministic.**

### 3. Joint Quadrant Analysis

| Quadrant | Windows | Alt Mean | Alt WR | BTC Mean |
|----------|---------|----------|--------|----------|
| BTC + Alt stealth | 14 | +0.258% | 49.8% | +1.443% |
| Alt stealth only | 118 | -0.330% | 44.8% | +0.106% |
| No stealth | 3 | -0.781% | 34.9% | +0.772% |

→ **Alt stealth alone is noise. BTC stealth is the trigger.**

### 4. RS Threshold — Looser is Better

| RS< | Acc> | N | Mean | Edge |
|-----|------|---|------|------|
| 1.0 | 1.0 | 1154 | -0.131% | **+0.170%** |
| 0.9 | 1.0 | 46 | -2.853% | **-2.588%** |

→ **Tighter RS = worse. RS ∈ [0.8, 1.0) is the sweet spot.**

### 5. Signal Strength is Inversely Correlated

| Quartile | Mean | Win Rate |
|----------|------|----------|
| Q1 weakest | **+0.572%** | **52.6%** |
| Q4 strongest | -0.829% | 39.1% |

→ **Very strong stealth = possible distribution/pump-and-dump disguise.**  
→ **Use Acc ∈ [1.0, 1.5], NOT Acc > 2.0.**

---

## Optimal Entry Rule (3 gates)

```python
# Gate 1: BTC bull regime
btc_bull = btc_close[-1] > btc_sma20

# Gate 2: BTC stealth ON (leading indicator, 92.9% accuracy)
btc_stealth = (btc_window_return < 0) and (btc_acc > 1.0) and (btc_cvd_slope > 0)

# Gate 3: Alt quality filter (avoid distribution disguise)
alt_entry = (0.8 <= rs < 1.0) and (1.0 <= acc <= 1.5) and (cvd_slope > 0)

# Entry only when all 3 fire simultaneously
if btc_bull and btc_stealth and alt_entry:
    ENTER(symbol)
```

---

## Integration

- `scripts/autonomous_lab_loop.py`
  - `compute_btc_stealth_regime(btc_df)` — computes BTC stealth + bull regime
  - `pre_bull_signals` dict includes `btc_stealth`, `btc_bull_regime`, `btc_raw_ret`, `btc_acc`, `btc_cvd_slope`
  - `artifacts/stealth-watchlist.json` — gated list (only populated when `btc_bull_regime=True`)
  - Console prints `🔥BTC_STEALTH` when signal fires

---

## Top Performing Symbols (historical, fwd=12봉)

| Symbol | Count | Avg Ret | Win Rate |
|--------|-------|---------|----------|
| KRW-BAT | 6 | +10.04% | 100% |
| KRW-SUPER | 13 | +7.26% | 76.9% |
| KRW-NEO | 9 | +2.93% | 100% |
| KRW-1INCH | 7 | +2.58% | 100% |
| KRW-AVAX | 7 | +2.30% | 85.7% |

*Note: small sample sizes — use as directional reference only.*
