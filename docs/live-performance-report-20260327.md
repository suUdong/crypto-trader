# Crypto-Trader Live Performance Report

**Date**: 2026-03-27 07:46 KST
**Mode**: Paper Trading (Micro-Live)
**Daemon Session**: 20260326T220708Z ~ 20260327T070623Z (113 iterations)
**Initial Capital**: 11,000,000 KRW (11 wallets x 1,000,000 KRW)

---

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total Equity | 10,999,117 KRW |
| Net P&L | -883 KRW (-0.008%) |
| Realized P&L | -579 KRW (1 closed trade) |
| Unrealized P&L | ~-304 KRW |
| Total Entries | 5 buy orders filled |
| Active Positions | 5 (across 2 wallets) |
| Idle Wallets | 9 / 11 |
| Kill Switch | NOT triggered |
| Market Regime | Sideways (ADX 22.3) |

---

## 2. Strategy Performance Breakdown

### 2.1 kimchi_premium (Active - 4 positions)

| Symbol | Entry Price | Qty | Cost (KRW) | Current Price | Unrealized % |
|--------|-----------|-----|------------|---------------|-------------|
| KRW-BTC | 104,329,138 | 0.001598 | 166,741 | 104,193,000 | -0.13% |
| KRW-ETH | 3,128,563 | 0.007271 | 22,748 | 3,127,000 | -0.05% |
| KRW-XRP | 2,067 | 10.620 | 21,951 | 2,065 | -0.10% |
| KRW-SOL | 131,065 | 0.1616 | 21,180 | 131,000 | -0.05% |

- **Total invested**: 232,620 KRW
- **Wallet equity**: 999,386 KRW (-0.06%)
- **Cash remaining**: 583,733 KRW (58.4%)
- **Status**: MAX CAPACITY (4/4 slots)
- **Entry signals**: contrarian_buy (premium -0.97~-1.00%), safe_zone_rsi_entry

**Additional buys (accumulated across 3 daemon sessions)**:
- Session 1 (22:07): 4 entries (BTC/ETH/XRP/SOL)
- Session 2 (22:34): 4 buys (cost 326,323 KRW)
- Session 3 (22:40): 4 buys (cost 326,323 KRW)
- Session 4 (22:45): 4 buys (cost 326,323 KRW)
- Total 12 buy events, ~979K KRW total exposure

### 2.2 volatility_breakout (1 closed trade)

| Trade | Entry | Exit | P&L | Return |
|-------|-------|------|-----|--------|
| KRW-BTC | 104,329,138 | 104,070,938 | -579 KRW | -0.35% |

- **Exit reason**: close_below_prev_low
- **Fee rate**: 0.05% per side
- **Holding period**: < 1 hour
- **Current**: 1 open position (BTC), equity 999,731 KRW

### 2.3 Idle Strategies (No trades)

| Wallet | Strategy | Reason | Status |
|--------|----------|--------|--------|
| momentum_btc | momentum | entry_conditions_not_met | OK |
| momentum_eth | momentum | entry_conditions_not_met | OK |
| vpin_btc | vpin | entry_conditions_not_met | OK |
| vpin_eth | vpin | entry_conditions_not_met | OK |
| vpin_sol | vpin | entry_conditions_not_met | OK |
| vbreak_eth | volatility_breakout | below_ma_filter | OK |
| consensus_btc | consensus | consensus_insufficient (0/2) | OK |
| ema_cross_btc | ema_crossover | entry_conditions_not_met | OK |
| mean_rev_eth | mean_reversion | entry_conditions_not_met | OK |

**Assessment**: 9/11 wallets correctly filtering in sideways market. No false entries.

---

## 3. Slippage Analysis

| Metric | Value |
|--------|-------|
| Measured Slippage (BTC) | +0.05% |
| Measured Slippage (ETH) | +0.05% |
| Anomaly Count | 0 |
| Anomaly Rate | 0% |

- Paper trading uses 0.05% fee + simulated slippage model
- No real order book slippage data yet (paper mode)
- SlippageMonitor configured but awaiting live execution data

---

## 4. Risk Metrics

### Kill Switch Status
| Parameter | Current | Threshold | Margin |
|-----------|---------|-----------|--------|
| Daily Loss | 0.004% | 5.0% | 99.9% |
| Portfolio Drawdown | 0.005% | 15.0% | 99.97% |
| Consecutive Losses | 0 | 5 | 100% |
| Position Size Penalty | 1.0x | - | No reduction |

### Portfolio Health
- **Peak equity**: 10,999,449 KRW
- **Current drawdown**: -332 KRW from peak
- **Warning level**: NOT active
- **Kill switch**: NOT triggered

---

## 5. Signal Activity Summary

| Event Type | Count |
|------------|-------|
| Total Signals | 543 |
| Buy Signals Executed | 5 (real market) |
| Hold Signals | ~530 |
| Trade Events | 68 (includes simulated) |
| Strategy Runs | 4,650 (cumulative) |

### Signal Distribution by Strategy (last 200 runs)
| Wallet | Runs | Primary Signal |
|--------|------|---------------|
| composite_wallet | 55 | hold |
| kimchi_premium_wallet | 28 | buy/hold |
| mean_reversion_wallet | 54 | hold |
| momentum_wallet | 54 | hold |
| Others | 9 | hold |

---

## 6. Market Conditions (07:05 KST)

| Symbol | Price | 9h Change | Regime |
|--------|-------|-----------|--------|
| KRW-BTC | 104,193,000 | +0.68% | Sideways |
| KRW-ETH | 3,127,000 | +1.23% | Sideways |
| KRW-XRP | 2,065 | +0.05% | Sideways |
| KRW-SOL | 131,000 | +1.16% | Sideways |

- ADX (BTC): 22.3 (weak trend)
- BTC below MA filter -- vbreak entries blocked
- Consensus: 0/2 strategies agreeing

---

## 7. Promotion Gate Check

| Criterion | Required | Current | Status |
|-----------|----------|---------|--------|
| Paper trading days | 7d | <1d | NOT MET |
| Closed trades | 10+ | 1 | NOT MET |
| Profitable wallets | 2+ | 0 | NOT MET |
| Portfolio return | > 0% | -0.008% | NOT MET |

**Verdict**: STAY IN PAPER -- minimum 7 days of paper trading required.

---

## 8. Issues & Recommendations

### Issues Found
1. **Daemon stopped** (SIGTERM at 07:06) -- needs restart
2. **kimchi_premium at max capacity** -- 4/4 slots filled, cannot enter new opportunities
3. **Premium indicator extreme** -- Values -0.97~-1.00 near theoretical min; verify Binance feed
4. **vbreak_eth state inconsistency** -- Reports "position_open_waiting" with 0 positions
5. **Legacy simulated trades in paper-trades.jsonl** -- 54 entries with fake prices (100.05/99.95) polluting stats

### Recommendations
1. Restart daemon immediately for continuous monitoring
2. Validate Binance price feed for kimchi premium calculation
3. Clean legacy simulated trade data from paper-trades.jsonl
4. Monitor kimchi positions for stop-loss triggers at -2%
5. No parameter changes needed -- sideways market correctly filtered

---

## 9. Historical Performance Context

### Previous Sessions (from runtime checkpoint)
| Wallet | Cash | Realized P&L | Trades | Equity |
|--------|------|-------------|--------|--------|
| momentum_wallet (sim) | 999,568 | -432 | 2 | 999,568 |
| mean_reversion_wallet | 1,000,000 | 0 | 0 | 1,000,000 |
| composite_wallet | 1,000,000 | 0 | 0 | 1,000,000 |

---

*Generated: 2026-03-27 07:46 KST | Session: 20260326T220708Z | Paper Trading Mode*
*Next scheduled report: 2026-03-28*
