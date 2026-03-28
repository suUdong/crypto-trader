# Paper Trading Performance Analysis

**Generated:** 2026-03-29
**Period:** 2026-03-27 ~ 2026-03-28 (active paper trading)
**Portfolio:** ₩5,701,836 initial → ₩5,703,663 current (+₩1,827, +0.032%)
**Market Regime:** Neutral | Fear & Greed Index: 12 (Extreme Fear)

---

## 1. Trade Summary (paper-trades.jsonl)

| # | Symbol | Wallet | Strategy | Entry → Exit | PnL (₩) | PnL % | Exit Reason |
|---|--------|--------|----------|-------------|---------|-------|-------------|
| 1 | BTC | vbreak_btc | volatility_breakout | 104,329K → 104,071K | -579 | -0.35% | close_below_prev_low |
| 2 | ETH | momentum_eth | momentum | 3,128K → 3,088K | -3,376 | -1.35% | momentum_reversal |
| 3 | ETH | momentum_eth | momentum | 3,128K → 3,093K | -2,977 | -1.19% | momentum_reversal |
| 4 | BTC | kimchi_premium | kimchi_premium | 102,681K → 100,772K | -1,715 | -1.96% | atr_stop_loss |
| 5 | ETH | kimchi_premium | kimchi_premium | 3,085K → 3,007K | -2,105 | -2.60% | atr_stop_loss |
| 6 | XRP | vbreak_xrp | volatility_breakout | 2,031 → 2,018 | -1,792 | -0.72% | close_below_prev_low |
| 7 | ETH | vpin_eth | vpin | 3,021K → 3,073K | **+3,524** | **+1.60%** | rsi_overbought |
| 8 | ETH | vpin_eth | vpin | 3,078K → 3,071K | -204 | -0.35% | rsi_overbought |

**Totals:** 8 trades, 1 win / 7 losses, **win rate 12.5%**, total realized PnL **-₩9,225**

> Note: Daily report shows +₩3,320 realized (last 24h window only = trades 7-8). The full paper trading history shows -₩9,225.

---

## 2. Strategy Performance Comparison

| Strategy | Trades | Wins | Losses | Win Rate | Total PnL (₩) | Avg PnL (₩) | Worst Trade |
|----------|--------|------|--------|----------|---------------|-------------|-------------|
| **vpin** | 2 | 1 | 1 | 50% | **+3,320** | +1,660 | -204 |
| volatility_breakout | 2 | 0 | 2 | 0% | -2,372 | -1,186 | -1,792 |
| kimchi_premium | 2 | 0 | 2 | 0% | -3,820 | -1,910 | -2,105 |
| momentum | 2 | 0 | 2 | 0% | -6,353 | -3,177 | -3,376 |

### Key Findings

- **VPIN is the only profitable strategy** (+₩3,320, Sharpe 1.12). Best trade: +₩3,524 on ETH with 0.76 confidence.
- **Momentum is the worst performer** (-₩6,353). Both ETH trades hit momentum_reversal exit — entering during a downtrend in extreme fear market.
- **Kimchi premium** lost -₩3,820 with both trades hitting ATR stop-loss — signals are unreliable in current regime.
- **Volatility breakout** lost -₩2,372. close_below_prev_low exits suggest false breakouts in range-bound market.

---

## 3. Open Positions

| Wallet | Symbol | Qty | Entry Price | Current Price | Unrealized PnL | PnL % |
|--------|--------|-----|------------|--------------|----------------|-------|
| vpin_sol | KRW-SOL | 1.796 | ₩127,095 | ₩126,400 | -₩1,248 | -0.55% |
| vpin_eth | KRW-ETH | 0.019 | ₩3,073,303 | ₩3,068,000 | -₩101 | -0.17% |

**Total unrealized:** -₩1,350
**Both positions are VPIN strategy** — small losses, within normal ATR range. No immediate concern.

---

## 4. Wallet Capital Allocation vs Performance

| Wallet | Capital (₩) | % of Portfolio | Strategy | Weekly PnL | Status |
|--------|------------|----------------|----------|-----------|--------|
| volspike_btc | 2,092,813 | 36.7% | volume_spike | ₩0 | **IDLE — 0 trades** |
| vpin_sol | 2,280,508 | 40.0% | vpin | -₩1,363 (unrealized) | Active, 1 open |
| vpin_eth | 583,153 | 10.2% | vpin | +₩3,189 | **BEST performer** |
| momentum_eth | 436,408 | 7.7% | momentum | -₩6,353 | **WORST performer** |
| momentum_sol | 308,954 | 5.4% | momentum | ₩0 | Idle |

### Capital Allocation Problems

1. **volspike_btc holds 36.7% of capital but has 0 trades** — dead capital earning nothing
2. **vpin_eth is the only profitable wallet but only has 10.2% allocation**
3. **momentum_eth lost ₩6,353 on 7.7% allocation** — negative ROI strategy consuming capital

---

## 5. Signal Quality Analysis

| Strategy | Total Signals | Buy Signals | Trades Executed | Rejection Rate | Avg Confidence |
|----------|--------------|-------------|-----------------|---------------|----------------|
| vpin (ETH) | 603 | 7 | 5 | 44% | 0.21 |
| vpin (SOL) | 243 | 1 | 1 | 0% | 0.20 |
| volume_spike (BTC) | 243 | 0 | 0 | — | 0.10 |
| momentum (all) | 150 | 0 | 0 | — | 0.20 |
| kimchi_premium | 118 | 0 | 0 | — | 0.20 |

- **Volume spike avg confidence is only 0.10** — way below min_entry_confidence (0.45). This explains zero trades.
- Most strategies sit at default 0.20 confidence — signals are too weak to pass the 0.45 threshold.
- VPIN is the only strategy generating actionable signals (confidence > 0.45).

---

## 6. Risk Metrics

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Portfolio return | +0.032% | — | Barely positive |
| Portfolio Sharpe (daily) | 0.36 | >1.0 target | Poor |
| Portfolio Sharpe (weekly) | 0.14 | >0.5 target | Very poor |
| Max drawdown | 0.12% | 8% kill switch | Safe |
| Win rate (all trades) | 12.5% | >40% target | **Critical** |
| Win rate (VPIN only) | 50% | >40% target | Acceptable |
| Consecutive losses | 6 (trades 1-6) | 3 max | **Triggered kill switch** |

---

## 7. Improvement Recommendations

### Immediate Config Changes (P0)

#### 7.1 Disable momentum_eth_wallet
**Why:** 0% win rate, -₩6,353 loss, enters against extreme-fear regime.
```toml
# In daemon.toml [[wallets]] section for momentum_eth_wallet:
# Set enabled = false or remove from active wallets
```

#### 7.2 Increase vpin_eth allocation
**Why:** Only profitable strategy. Sharpe 1.12. Should get more capital.
```toml
# Reallocate momentum_eth capital (₩436K) to vpin_eth
# vpin_eth: ₩583K → ₩1,019K (17.9% of portfolio)
```

#### 7.3 Reduce volspike_btc allocation or add symbols
**Why:** ₩2.09M (36.7%) sitting idle with zero trades. volume_spike confidence averaging 0.10 is too low.
```toml
# Option A: Cut volspike_btc capital to ₩1M, redistribute to vpin wallets
# Option B: Lower volume_spike confidence threshold in strategy params
```

### Strategy Parameter Tuning (P1)

#### 7.4 Tighten stop-loss for momentum strategy
Current `stop_loss_pct = 0.03` (3%) allowed the -2.6% kimchi loss to persist. For momentum in extreme-fear:
```toml
# Per-wallet risk override for momentum wallets:
# stop_loss_pct = 0.015  (1.5% tighter stop)
```

#### 7.5 Add regime filter for momentum entries
Momentum should not enter during extreme fear (F&G < 20). The macro integration exists — ensure momentum strategy respects `regime.bear_threshold` and skips entries when macro sentiment is extreme fear.

#### 7.6 VPIN confidence threshold optimization
VPIN's best trade had confidence 0.76 (+₩3,524). The losing trade had 0.70 (-₩204). Consider:
```toml
# Raise min_entry_confidence for vpin from 0.45 to 0.55
# Fewer trades but higher quality signals
```

### Structural Changes (P2)

#### 7.7 Disable kimchi_premium in current config
0% win rate, both trades hit ATR stop-loss. Kimchi premium arbitrage requires specific market conditions not present in extreme-fear regime. Keep disabled until regime shifts to neutral/bull.

#### 7.8 Weekend mean_reversion needs more data
1 trade executed, no result yet. Keep monitoring but don't increase allocation.

---

## 8. Summary

| Metric | Current | Target | Gap |
|--------|---------|--------|-----|
| Win rate (all) | 12.5% | >40% | -27.5pp |
| Win rate (VPIN) | 50% | >50% | On target |
| Sharpe (weekly) | 0.14 | >0.5 | -0.36 |
| Capital utilization | 17.9% active | >60% | -42.1pp |
| Profitable strategies | 1/4 | 2+/4 | -1 |

**Bottom line:** VPIN is the only viable strategy in the current extreme-fear regime. The system is capital-inefficient — 76.7% of capital (volspike_btc + momentum_sol) produced zero trades. Immediate action: disable losers (momentum_eth, kimchi), concentrate on VPIN, and wait for regime shift before re-enabling breakout strategies.
