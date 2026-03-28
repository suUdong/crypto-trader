# Strategy Priority Report — Live Deployment Readiness

**Generated**: 2026-03-28
**Data Sources**: 90-day backtest (hourly, 4 symbols), walk-forward OOS validation, 200-candle recent snapshot
**Universe**: KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL (Upbit)

---

## 1. Executive Summary

Out of 13 strategies backtested over 90 days, only **4 strategies** show positive risk-adjusted returns (Sharpe > 0). The **consensus ensemble** dominates recent snapshots (Sharpe 5.67) but trades infrequently. **Momentum** is the most robust single strategy across all validation windows. **VPIN** offers the best absolute return with acceptable risk. The bottom 6 strategies are net-negative and should remain disabled.

**Recommended live priority**: momentum → vpin → consensus → composite (staged rollout, smallest wallet first).

---

## 2. Full Strategy Ranking (90-Day Backtest)

| Rank | Strategy | Avg Sharpe | Avg Sortino | Avg Calmar | Avg MDD% | Avg Return% | Win Rate% | Trades | Profit Factor | Verdict |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | **momentum** | **0.98** | 1.66 | 2.96 | 0.34 | +0.16 | 51.0 | 54 | 2.65 | ✅ Deploy |
| 2 | **composite** | 0.92 | 4.29 | 8.75 | 0.07 | +0.02 | 50.0 | 4 | ∞ | ⚠️ Low sample |
| 3 | **vpin** | **0.65** | 0.92 | 1.52 | 0.67 | +0.24 | 55.5 | 68 | 1.31 | ✅ Deploy |
| 4 | **consensus** | **0.39** | 0.78 | 1.66 | 0.47 | +0.08 | 53.9 | 55 | 1.39 | ✅ Deploy |
| 5 | funding_rate | -0.10 | 0.12 | 1.65 | 0.51 | +0.03 | 39.3 | 29 | 1.32 | 🔬 Research |
| 6 | kimchi_premium | -0.26 | -0.27 | -0.03 | 0.59 | -0.12 | 53.1 | 34 | 1.48 | 🔬 Research |
| 7 | ema_crossover | -0.60 | -0.73 | -0.49 | 0.76 | -0.23 | 47.9 | 28 | 0.81 | ❌ Disable |
| 8 | obi | -0.94 | -1.16 | -1.09 | 0.54 | -0.18 | 47.9 | 47 | 0.76 | ❌ Disable |
| 9 | volatility_breakout | -0.98 | -0.69 | -0.47 | 0.36 | +0.04 | 34.8 | 55 | 0.77 | ❌ Disable |
| 10 | momentum_pullback | -1.13 | -1.49 | -1.89 | 0.60 | -0.27 | 41.7 | 36 | 0.54 | ❌ Disable |
| 11 | volume_spike | -1.45 | -1.94 | -2.66 | 0.44 | -0.28 | 31.9 | 23 | 0.36 | ❌ Disable |
| 12 | mean_reversion | -2.18 | -2.53 | -2.83 | 0.57 | -0.41 | 30.6 | 22 | 0.29 | ❌ Disable |
| 13 | bollinger_rsi | -2.30 | -2.72 | -2.51 | 0.98 | -0.58 | 50.0 | 41 | 0.41 | ❌ Disable |

---

## 3. Top Strategy Deep Dive

### 3.1 Momentum (Rank #1)

Best all-around single strategy. Positive Sharpe across validation windows.

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-SOL | **+0.41** | 0.21 | **2.60** | 4.54 | 63.6 | 11 | 6.92 |
| KRW-XRP | +0.18 | 0.69 | 0.60 | 0.87 | 57.1 | 14 | 1.22 |
| KRW-ETH | +0.08 | 0.11 | 0.83 | 1.41 | 33.3 | 9 | 1.49 |
| KRW-BTC | -0.02 | 0.34 | -0.12 | -0.18 | 50.0 | 20 | 0.96 |

**Strengths**: Lowest MDD (0.34%), highest Sortino (1.66), robust across symbols.
**Weakness**: BTC slightly negative — regime-dependent.
**Best pair**: SOL (Sharpe 2.60, PF 6.92).

### 3.2 VPIN (Rank #3)

Highest absolute return among reliable strategies. Order-flow based.

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-SOL | **+0.58** | 0.81 | **1.14** | 1.61 | 59.3 | 27 | 1.55 |
| KRW-BTC | +0.16 | 0.35 | 0.61 | 0.89 | 60.0 | 15 | 1.32 |
| KRW-XRP | +0.14 | 0.92 | 0.46 | 0.65 | 55.6 | 9 | 1.18 |
| KRW-ETH | +0.10 | 0.60 | 0.38 | 0.53 | 47.1 | 17 | 1.17 |

**Strengths**: Positive return on ALL 4 symbols, highest trade count (68), consistent PF > 1.
**Weakness**: Higher MDD (0.67%) than momentum; OOS walk-forward showed -1.37% (regime-sensitive).
**Best pair**: SOL (Return +0.58%, PF 1.55).

### 3.3 Consensus (Rank #4)

Multi-strategy ensemble filter. Exceptional in recent snapshots.

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-ETH | **+0.51** | 0.24 | **2.74** | 4.82 | 60.0 | 10 | 3.10 |
| KRW-SOL | -0.02 | 0.62 | -0.03 | -0.04 | 55.6 | 27 | 0.99 |
| KRW-XRP | -0.06 | 0.74 | -0.20 | -0.28 | 50.0 | 10 | 0.90 |
| KRW-BTC | -0.11 | 0.28 | -0.93 | -1.38 | 50.0 | 8 | 0.57 |

**Strengths**: Recent snapshot Sharpe 5.67 (best), low MDD, good noise filter.
**Weakness**: 90d backtest shows mixed per-symbol results; only ETH clearly positive.
**Best pair**: ETH (Sharpe 2.74, PF 3.10).

### 3.4 Composite (Rank #2 — Low Confidence)

| Symbol | Return% | MDD% | Sharpe | Sortino | WinRate% | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| KRW-BTC | +0.07 | 0.01 | 2.43 | 14.51 | 100.0 | 1 | ∞ |
| KRW-XRP | +0.04 | 0.03 | 1.48 | 3.00 | 100.0 | 1 | ∞ |
| KRW-ETH | -0.04 | 0.24 | -0.24 | -0.35 | 0.0 | 2 | 0.00 |
| KRW-SOL | +0.00 | 0.00 | 0.00 | 0.00 | 0.0 | 0 | — |

**Only 4 trades total** — metrics are statistically meaningless. Not deployable until more data.

---

## 4. Cross-Validation Matrix

Comparing three measurement windows to detect overfitting and alpha decay:

| Strategy | 90d IS Sharpe | OOS Sharpe | Recent Sharpe | Consistency | Assessment |
| --- | ---: | ---: | ---: | --- | --- |
| **momentum** | 0.98 | 0.29 | -0.40 | Medium | Robust IS, OOS positive, recent dip = regime |
| **vpin** | 0.65 | -1.23 | 1.51 | Low | Strong IS + recent, OOS weak = regime-sensitive |
| **consensus** | 0.39 | N/A | 5.67 | Unknown | Ensemble masks individual weakness |
| composite | 0.92 | N/A | N/A | Unknown | Too few trades |
| obi | -0.94 | -0.94 | 2.46 | Very Low | Recent spike may be noise |
| momentum_pullback | -1.13 | 0.14 | -4.11 | Very Low | Defensive only |

**Key finding**: Only **momentum** maintains positive returns across both IS and OOS windows. VPIN is strong in IS and recent but failed OOS — it needs regime filtering for safety.

---

## 5. Live Deployment Priority

### Tier 1 — Deploy First (High Confidence)

| Priority | Strategy | Symbol(s) | Rationale |
| ---: | --- | --- | --- |
| **1** | momentum | KRW-SOL | Sharpe 2.60, PF 6.92, OOS positive. Best risk-adjusted edge. |
| **2** | vpin | KRW-SOL | Return +0.58%, 27 trades, PF 1.55. Highest absolute return. |
| **3** | momentum | KRW-ETH | Sharpe 0.83, low MDD 0.11%. Conservative secondary sleeve. |

### Tier 2 — Deploy After Tier 1 Validates (Medium Confidence)

| Priority | Strategy | Symbol(s) | Rationale |
| ---: | --- | --- | --- |
| **4** | vpin | KRW-BTC | Sharpe 0.61, PF 1.32. Positive but lower conviction than SOL. |
| **5** | consensus | KRW-ETH | Sharpe 2.74 in 90d, but needs more OOS data. |
| **6** | vpin | KRW-ETH | Sharpe 0.38, PF 1.17. Marginal but positive. |

### Tier 3 — Research Only (Not Ready)

| Strategy | Issue |
| --- | --- |
| composite | 4 trades — no statistical significance |
| funding_rate | Near-zero Sharpe, XRP blowup (-3.24 Sharpe) |
| kimchi_premium | Negative avg return, only SOL positive |

### Tier 4 — Disabled (Negative Edge)

| Strategy | Avg Sharpe | Avg Return% | Action |
| --- | ---: | ---: | --- |
| ema_crossover | -0.60 | -0.23 | Hibernate |
| obi | -0.94 | -0.18 | Hibernate |
| volatility_breakout | -0.98 | +0.04 | Hibernate (despite XRP edge) |
| momentum_pullback | -1.13 | -0.27 | Hibernate |
| volume_spike | -1.45 | -0.28 | Hibernate |
| mean_reversion | -2.18 | -0.41 | Hibernate — worst performer |
| bollinger_rsi | -2.30 | -0.58 | Hibernate — highest MDD |

---

## 6. Recommended Capital Allocation (₩5.7M)

Based on current daemon.toml wallets mapped to priority tiers:

| Wallet | Strategy | Symbol | Capital | % | Tier | Status |
| --- | --- | --- | ---: | ---: | --- | --- |
| vpin_sol_wallet | vpin | KRW-SOL | ₩2,500,000 | 43.9% | T1 | ✅ Live first |
| momentum_sol_wallet | momentum | KRW-SOL | ₩1,100,000 | 19.3% | T1 | ✅ Live first |
| momentum_eth_wallet | momentum | KRW-ETH | ₩450,000 | 7.9% | T1 | ✅ Live first |
| volspike_btc_wallet | volume_spike | KRW-BTC | ₩1,300,000 | 22.8% | **T4** | ⚠️ **Mismatch** |
| vpin_eth_wallet | vpin | KRW-ETH | ₩350,000 | 6.1% | T2 | Paper first |

### Allocation Issues Identified

1. **volspike_btc_wallet (₩1.3M, 22.8%)** — volume_spike has avg Sharpe **-1.45** and avg return **-0.28%** in the 90d backtest. The wallet-specific 90d ROI (+1.03%) comes from only **7 trades**, making it statistically unreliable. This is the highest-risk wallet in the current config.

2. **Recommended reallocation**: Move ₩1.3M from volspike_btc to higher-confidence strategies:
   - +₩600K to vpin_sol (→ ₩3.1M, 54.4%) — highest validated ROI
   - +₩400K to momentum_sol (→ ₩1.5M, 26.3%) — best Sharpe
   - +₩300K to vpin_eth (→ ₩650K, 11.4%) — diversification into T2

---

## 7. Risk Assessment

### Concentration Risk
- Current: 43.9% in vpin_sol + 19.3% in momentum_sol = **63.2% in KRW-SOL**.
- After reallocation: SOL exposure would rise to **80.7%**.
- **Mitigation**: Cap SOL exposure at 65% total; allocate remainder to ETH sleeves.

### Regime Risk
- VPIN showed -1.37% in OOS walk-forward (trending regime).
- **Mitigation**: Enable regime filter — only allow VPIN entries in sideways/high-volatility regimes.
- Momentum OOS was +0.71% — more regime-resilient.

### Sample Size Risk
- composite (4 trades), volspike_btc (7 trades) — insufficient for live deployment.
- **Rule**: Require ≥30 trades in 90d backtest before live capital allocation.

### Staged Rollout Plan
1. **Week 1**: `vpin_eth_wallet` goes live (smallest, ₩350K) — already configured in `go_live_wallets`.
2. **Week 2**: If Week 1 PnL ≥ -1%, add `momentum_eth_wallet` (₩450K).
3. **Week 3**: Add `momentum_sol_wallet` (₩1.1M).
4. **Week 4**: Add `vpin_sol_wallet` (₩2.5M) — largest allocation last.
5. **Gate**: Each stage requires: no kill switch triggers, MDD < 2%, realized PnL ≥ -0.5%.

---

## 8. Action Items

- [ ] Reallocate volspike_btc capital to vpin_sol / momentum_sol / vpin_eth
- [ ] Add regime filter gate to VPIN strategy entries
- [ ] Re-run composite backtest with longer window (180d) for statistical validity
- [ ] Set minimum 30-trade threshold in promotion gate logic
- [ ] Monitor Week 1 live performance of vpin_eth_wallet
- [ ] Re-tune obi/vpin parameters on 14-day window per comparison report recommendation
