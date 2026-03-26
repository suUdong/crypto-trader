# 24H Live Monitoring Report — 2026-03-27 07:10 KST

## Executive Summary

| Metric | Value |
|--------|-------|
| Report Period | 2026-03-26 22:07 ~ 2026-03-27 07:06 KST |
| Total Trades | 5 (all BUY entries, no exits) |
| Active Positions | 5 across 2 wallets |
| Realized P&L | 0 KRW |
| Unrealized P&L | ~-880 KRW (-0.008% of total equity) |
| Total Equity | ~10,999,117 KRW / 11,000,000 KRW initial |
| Kill Switch | NOT triggered |
| Daemon Status | SIGTERM at 07:06 after 113 iterations |
| Mode | Paper Trading |

## 1. Trade Execution Log

### Session: 20260326T220708Z (5 iterations before restart)

| # | Time (UTC) | Wallet | Strategy | Symbol | Side | Entry Price | Qty | Reason |
|---|-----------|--------|----------|--------|------|-------------|-----|--------|
| 1 | 22:07:11 | vbreak_btc | volatility_breakout | KRW-BTC | BUY | 104,329,138.5 | 0.001598 | breakout above 104,239,450 |
| 2 | 22:07:12 | kimchi_premium | kimchi_premium | KRW-ETH | BUY | 3,128,563.5 | 0.007271 | contrarian_buy (premium=-0.97%) |
| 3 | 22:07:13 | kimchi_premium | kimchi_premium | KRW-XRP | BUY | 2,067.033 | 10.620 | contrarian_buy (premium=-1.00%) |
| 4 | 22:07:13 | kimchi_premium | kimchi_premium | KRW-SOL | BUY | 131,065.5 | 0.1616 | contrarian_buy (premium=-0.99%) |

### Session: Daemon restart (04:34 KST)

| # | Time | Wallet | Strategy | Symbol | Side | Entry Price | Qty | Reason |
|---|------|--------|----------|--------|------|-------------|-----|--------|
| 5 | 04:34:36 | kimchi_premium | kimchi_premium | KRW-BTC | BUY | 103,537,743 | 0.002197 | safe_zone_rsi_entry |

## 2. Position Status by Strategy

### kimchi_premium_wallet (4 positions — MAX CAPACITY)

| Symbol | Entry Price | Current Price | Unrealized % | Status |
|--------|------------|---------------|-------------|--------|
| KRW-BTC | 104,329,138 | 104,193,000 | -0.13% | Holding |
| KRW-ETH | 3,128,563 | 3,127,000 | -0.05% | Holding |
| KRW-XRP | 2,067 | 2,065 | -0.10% | Holding |
| KRW-SOL | 131,065 | 131,000 | -0.05% | Holding |

- Cash remaining: 583,733 KRW (58.4% of wallet capital)
- Wallet equity: 999,386 KRW (-0.06% from initial 1M)
- **4/4 concurrent positions** — no new entries possible until exits

### vbreak_btc_wallet (1 position)

| Symbol | Entry Price | Current Price | Unrealized % | Status |
|--------|------------|---------------|-------------|--------|
| KRW-BTC | 104,329,138 | 104,193,000 | -0.13% | Holding |

- Cash remaining: 833,167 KRW (83.3% of wallet capital)
- Wallet equity: 999,731 KRW (-0.03% from initial 1M)

### Idle Wallets (0 positions, 0 trades)

| Wallet | Strategy | Reason |
|--------|----------|--------|
| momentum_btc | momentum | entry_conditions_not_met |
| momentum_eth | momentum | entry_conditions_not_met |
| vpin_btc | vpin | entry_conditions_not_met |
| vpin_eth | vpin | entry_conditions_not_met |
| vpin_sol | vpin | entry_conditions_not_met |
| vbreak_eth | volatility_breakout | below_ma_filter / position_open_waiting |
| consensus_btc | consensus | consensus_insufficient (0/2) |
| ema_cross_btc | ema_crossover | entry_conditions_not_met |
| mean_rev_eth | mean_reversion | entry_conditions_not_met |

## 3. Risk & Anomaly Check

### Kill Switch Status
- **Triggered**: No
- Daily loss: 0.004% (limit: 5%)
- Portfolio drawdown: 0.005% (limit: 15%)
- Consecutive losses: 0 (limit: 5)
- Peak equity: 10,999,449 KRW

### Anomaly Flags

| Flag | Severity | Detail |
|------|----------|--------|
| kimchi_premium at max capacity | MEDIUM | 4/4 positions filled — cannot enter new opportunities |
| kimchi_premium indicator extreme | HIGH | Premium values -0.97 to -1.00 are near theoretical minimum. Verify Binance price feed is valid |
| vbreak_eth "position_open_waiting" without position | LOW | Wallet has 0 positions but reports position_open_waiting — possible state inconsistency |
| 9/11 wallets idle | INFO | Sideways market regime; strategies correctly filtering out low-confidence entries |
| No exits in 9+ hours | INFO | All positions within stop/TP range — no trailing stop triggers yet |
| Daemon SIGTERM at 07:06 | ACTION | Daemon stopped — needs restart to continue monitoring |

### Slippage Analysis
- BTC fills: entry at 104,329,138.5 vs market 104,277,000 = **+0.05% slippage** (acceptable for paper)
- ETH fills: entry at 3,128,563.5 vs market 3,127,000 = **+0.05% slippage**
- Fee rate: 0.05% per trade (configured)

## 4. Market Conditions

| Symbol | Price (07:05) | 9h Change | Regime |
|--------|--------------|-----------|--------|
| KRW-BTC | 104,193,000 | +0.68% | Sideways |
| KRW-ETH | 3,127,000 | +1.23% | Sideways |
| KRW-XRP | 2,065 | +0.05% | Sideways |
| KRW-SOL | 131,000 | +1.16% | Sideways |

- ADX (BTC): 22.3 — weak trend
- BTC below MA filter — vbreak/vbreak_eth entries blocked
- Consensus: 0/2 strategies agreeing — no high-confidence signals

## 5. Promotion Gate

| Criterion | Required | Current | Status |
|-----------|----------|---------|--------|
| Paper trading days | 7d | 0d | NOT MET |
| Total trades | 10+ | 0 (closed) | NOT MET |
| Profitable wallets | 2+ | 0 | NOT MET |
| Portfolio return | > 0% | -0.004% | NOT MET |

**Verdict: STAY IN PAPER** — minimum 7 days of paper trading required before live promotion.

## 6. Recommendations

1. **Restart daemon immediately** — SIGTERM at 07:06 means no monitoring active
2. **Investigate kimchi_premium feed** — Premium values near -1.0 suggest Binance comparison price may be stale or miscalculated
3. **Monitor kimchi positions** — All 4 slots filled with small unrealized losses; watch for stop-loss triggers at -2%
4. **No parameter changes needed** — System operating within design parameters, sideways market correctly filtered by most strategies
5. **Check vbreak_eth state** — "position_open_waiting" with 0 positions may indicate a checkpoint/state desync

---
*Generated: 2026-03-27 07:10 KST | Session: 20260326T220708Z | Paper Trading Mode*
