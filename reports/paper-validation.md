# Momentum Strategy Paper Trading Validation Report

**Date**: 2026-03-29 01:08–01:40 KST (32 minutes)
**Session ID**: `20260328T160854Z-14605`
**Config**: `config/daemon.toml` | `paper_trading=true`
**Market Regime**: sideways | Weekend session

---

## 1. Session Overview

| Metric | Value |
|--------|-------|
| Duration | 32 min (~32 ticks at 60s poll) |
| Active wallets | 5 (momentum_sol, momentum_eth, vpin_sol, vpin_eth, volspike_btc) |
| Total signal evaluations | 100 |
| Daemon status | healthy, 0 failures, 0 restarts |
| Total equity | ₩5,704,871 |
| Realized PnL (24h) | +₩3,320 (+0.06%) |
| Open positions | 2 (vpin_sol KRW-SOL, vpin_eth KRW-ETH) |

## 2. Momentum Strategy Signal Analysis

### 2.1 Evaluation Count

| Wallet | Evaluations | Signal | Reason |
|--------|-------------|--------|--------|
| momentum_sol_wallet | 1 | hold (1) | volume_too_low |
| momentum_eth_wallet | 6 | hold (6) | volume_too_low |
| **Total** | **7** | **hold: 7** | — |

Momentum wallets were evaluated 7 out of ~32 ticks. The remaining ticks were blocked by the
**portfolio drawdown gate** — a portfolio-level risk control that limits new position entries
when open positions already exist. This is correct behavior: the gate prevents over-exposure
by restricting concurrent entries across wallets.

### 2.2 Indicator Snapshots

**momentum_sol_wallet (KRW-SOL)**

| Indicator | Value | Threshold | Status |
|-----------|-------|-----------|--------|
| Momentum | 0.0111 | entry >= 0.002 | PASS |
| RSI | 66.0 | 30–72 (adaptive) | PASS |
| ADX | 24.7 | >= 20.0 | PASS |
| Volume Ratio | 0.124 | >= 1.0x avg (volume filter) | **BLOCKED** |

**momentum_eth_wallet (KRW-ETH)** — averaged across 6 evaluations

| Indicator | Value Range | Threshold | Status |
|-----------|-------------|-----------|--------|
| Momentum | 0.0155–0.0179 | entry >= 0.002 | PASS |
| RSI | 71.5–73.1 | 30–72 (adaptive) | BORDERLINE/FAIL |
| ADX | 23.3 | >= 20.0 | PASS |
| Volume Ratio | 0.090–0.225 | >= 1.0x avg | **BLOCKED** |

### 2.3 Hold Reason Analysis

All 7 momentum evaluations returned `hold` with reason `volume_too_low`:

- **KRW-SOL**: volume_ratio=0.12 (12% of average) — weekend low-activity period
- **KRW-ETH**: volume_ratio=0.09–0.23 (9–23% of average) — consistent low volume

The volume filter is working correctly: weekend overnight volume is ~10–25% of the
hourly average, correctly preventing entries in illiquid conditions. Additionally,
KRW-ETH RSI at 71.5–73.1 is at/above the overbought threshold (72), which would
also block entries even if volume were sufficient.

## 3. Cross-Strategy Comparison (same session)

| Strategy | Evaluations | Signals | Notes |
|----------|-------------|---------|-------|
| momentum | 7 | hold: 7 | Volume filter blocking (correct) |
| vpin | 62 | buy: 7, sell: 2, hold: 53 | Active trading, positions opened |
| volume_spike | 31 | hold: 31 | No volume spike detected |

VPIN was the most active strategy — entered/exited positions on KRW-ETH and KRW-SOL.
Volume spike and momentum both held due to market conditions (sideways regime, low weekend volume).

## 4. Paper Trade Execution Verification

### 4.1 Virtual Fills This Session

| Wallet | Side | Symbol | Qty | Fill Price | Status |
|--------|------|--------|-----|------------|--------|
| vpin_eth_wallet | sell | KRW-ETH | 0.0728 | ₩3,072,694 | filled (rsi_overbought) |
| vpin_sol_wallet | buy | KRW-SOL | 1.7957 | ₩127,095 | filled (vpin_safe_momentum_entry) |
| vpin_eth_wallet | buy | KRW-ETH | 0.0191 | ₩3,078,307 | filled (re-entry) |
| vpin_eth_wallet | sell/buy | KRW-ETH | multiple | various | 5 additional fills |

**Momentum wallets**: No fills (all signals were hold). This is expected — the volume
filter correctly prevented entries during low-volume weekend hours.

### 4.2 Position State

```json
{
  "open_positions": 2,
  "vpin_sol_wallet": { "symbol": "KRW-SOL", "qty": 1.7957, "entry": 127095, "unrealized_pnl": -171 KRW },
  "vpin_eth_wallet": { "symbol": "KRW-ETH", "position_open_waiting": true }
}
```

### 4.3 PaperBroker Health

- Fee simulation: 0.05% per side (Upbit standard)
- Slippage simulation: 0.075% per fill
- No execution errors or order rejections
- All fills processed correctly with realistic cost modeling

## 5. Risk Management Verification

| Component | Status | Evidence |
|-----------|--------|----------|
| Kill switch | inactive | max_drawdown 8% not reached (MDD: 1.46%) |
| Portfolio drawdown gate | active | Blocked momentum entries when vpin positions open |
| Correlation guard | active | Prevented correlated entries (DEBUG level) |
| Volume filter | active | Blocked all momentum entries (correct for weekend) |
| RSI overbought exit | active | Triggered vpin_eth sell at RSI > 72 |
| Consecutive loss limit | inactive | 0 consecutive losses |

## 6. Findings and Recommendations

### Validated (Working Correctly)

1. **Momentum strategy evaluates correctly** — indicators calculated, thresholds applied, hold signals generated with proper reasons
2. **Volume filter prevents bad entries** — weekend volume at 10–25% of average correctly blocked
3. **RSI boundary detection** — KRW-ETH RSI 71.5–73.1 near overbought, strategy correctly cautious
4. **Portfolio risk gates** — drawdown gate and correlation guard limit concurrent exposure
5. **PaperBroker execution** — fills with fee/slippage simulation working
6. **Daemon stability** — 32 minutes, 0 crashes, 0 restarts, healthy status throughout

### Observations

1. **Momentum wallet evaluation frequency**: Only 7/32 ticks (22%) due to portfolio gates. In production with dedicated capital allocation, momentum wallets would evaluate every tick when no position is held.
2. **Weekend low-volume period**: All momentum holds were `volume_too_low` — the volume filter is aggressive but appropriate. Consider a weekend-specific volume threshold if weekend trading is desired.
3. **ETH RSI near overbought (72–73)**: Even with sufficient volume, ETH would likely not trigger a buy entry. Market is extended.
4. **SOL indicators more favorable**: Momentum 0.011 > threshold 0.002, RSI 66 < 72, ADX 24.7 > 20. Only volume blocks entry — a volume surge during market hours could trigger a valid entry.

### Action Items

- [ ] Monitor weekday session (KST 09:00–18:00) for momentum entries with normal volume
- [ ] Consider adding INFO-level log when portfolio gate blocks a wallet (currently DEBUG only)
- [ ] Run extended 24h paper session to capture at least one full market cycle
- [ ] Validate momentum entry/exit with a manual backtest on recent high-volume period

---

*Generated by paper trading validation pipeline | Session 20260328T160854Z-14605*
