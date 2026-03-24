# Strategy Playbook

> Synthesized from crypto-strategy-research (50 notes) and auto-invest-research (161 notes)
> Date: 2026-03-24
> Baseline: crypto-trader master branch (commit 0f87daf)

---

## Executive Summary

Two independent research projects produced 211 research notes covering Upbit-specific strategies,
cross-asset rotation, microstructure alpha, tax optimization, and risk management. This playbook
distills them into **implementable strategies** for the crypto-trader project, ranked by priority.

**Current architecture supports:**
- 3 strategies (Momentum, MeanReversion, Composite) via `StrategyProtocol`
- 5 indicators (SMA, StdDev, Bollinger Bands, Momentum, RSI)
- Regime detection (Bull/Sideways/Bear) via short/long momentum
- Multi-symbol (KRW-BTC, ETH, XRP, SOL), multi-wallet isolation
- Paper trading on Upbit via `pyupbit` OHLCV
- Risk management (position sizing, SL/TP, daily loss cap)

---

## Tier 1: Drop-in Strategies (New strategy class, existing architecture)

### 1.1 Volatility Breakout Strategy

| Item | Detail |
|------|--------|
| **Description** | Larry Williams-style range breakout adapted for Upbit KRW pairs. Buy when price exceeds `prev_close + k * prev_range` where k is the Noise Ratio. |
| **Source** | crypto-strategy-research Cycle 1, auto-invest Cycle 4 |
| **Expected Return** | 40-80% CAGR (backtested on Upbit KRW pairs) |
| **MDD** | -15% to -25% (with MA filter and dynamic k) |
| **Required Data** | OHLCV candles (already available via pyupbit) |
| **New Indicators** | `noise_ratio(candles, lookback)`, `range_breakout_level(candles, k)` |
| **Impl. Difficulty** | **Low** - new `VolatilityBreakoutStrategy` class + 2 indicator functions |
| **Key Parameters** | k (noise ratio, default 0.5), MA filter period (5-20d), holding period (1 candle) |
| **Risk Notes** | Needs MA filter to avoid false breakouts in sideways regimes. Combine with regime detector. |
| **Priority** | **P0 - Implement first** |

### 1.2 Altcoin Rotation via BTC Dominance

| Item | Detail |
|------|--------|
| **Description** | Rotate capital into altcoins when BTC Dominance (BTC.D) is falling while BTC is stable/rising ("Alt Season" signal). Retreat to BTC when BTC.D rises. |
| **Source** | crypto-strategy-research Cycle 25 |
| **Expected Return** | 60-66% CAGR |
| **MDD** | -25% to -40% (with Kimchi Premium <10% filter) |
| **Required Data** | BTC dominance (fetchable from CoinGecko/CoinMarketCap API) + existing OHLCV |
| **New Indicators** | `btc_dominance_trend(dominance_values, lookback)` |
| **Impl. Difficulty** | **Low-Medium** - new strategy class + external API call for BTC.D |
| **Key Parameters** | BTC.D MA crossover (7d/30d), rebalancing frequency (weekly) |
| **Risk Notes** | Altcoin rotation amplifies drawdowns in bear markets. Must combine with regime filter. |
| **Priority** | **P0** |

### 1.3 Staking Reward Dip (Mean Reversion)

| Item | Detail |
|------|--------|
| **Description** | PoS assets (ETH, SOL) experience predictable price dips at reward distribution epochs as validators sell. Buy the dip, sell recovery. |
| **Source** | crypto-strategy-research Cycle 50 |
| **Expected Return** | SOL avg -0.45% at epoch end, recovery within hours |
| **Win Rate** | 62% for mean-reversion plays |
| **Required Data** | OHLCV (existing) + epoch timing (static schedule for SOL, daily for ETH) |
| **Impl. Difficulty** | **Low** - time-based trigger + existing MeanReversion logic |
| **Key Parameters** | Epoch offset hours, recovery target (%), max hold time |
| **Priority** | **P1** |

### 1.4 Weekend Volatility Regime

| Item | Detail |
|------|--------|
| **Description** | Adjust strategy parameters for weekends when institutional liquidity drops 20-30%. Tighter stops, smaller positions, bias toward mean-reversion. |
| **Source** | crypto-strategy-research Cycles 33, 48 |
| **Expected Return** | MDD improvement, not direct alpha |
| **Required Data** | System clock (day-of-week) |
| **Impl. Difficulty** | **Low** - extend `RegimeDetector.detect()` to include time-based weekend flag |
| **Key Parameters** | Weekend start (Sat 00:00 KST), weekend end (Mon 09:00 KST), position size multiplier (0.5x) |
| **Risk Notes** | CME gap fill probability ~70% by Monday. Sunday night is highest volatility. |
| **Priority** | **P1** |

---

## Tier 2: Enhanced Signal Filters (Need new data sources)

### 2.1 Kimchi Premium Filter

| Item | Detail |
|------|--------|
| **Description** | Use the KRW premium over global price as a sentiment/risk filter. Premium <5% = safe to enter. Negative premium = strong contrarian buy. Premium >7% = exit signal. |
| **Source** | crypto-strategy-research Cycles 2, 16; auto-invest Cycle 145 |
| **Expected Return** | MDD reduced from -25% to -12% when used as filter |
| **Required Data** | Binance BTC/USDT price (REST API, no auth needed) + Upbit KRW price + USD/KRW FX rate |
| **Impl. Difficulty** | **Medium** - new `KimchiPremiumFilter` class, Binance price fetcher, FX rate source |
| **Key Parameters** | Entry ceiling (5%), exit floor (7%), contrarian buy threshold (-1%) |
| **Risk Notes** | Premium can persist during deposit/withdrawal suspensions ("fence" events). |
| **Priority** | **P0 - High impact risk filter** |

### 2.2 US BTC ETF Inflow Signal

| Item | Detail |
|------|--------|
| **Description** | US Spot BTC ETF daily inflows predict Upbit 9AM (KST) opening direction. Inflow >$100M = 68% bullish probability. 4-week consecutive inflows = 65% sustained weekend bullishness. |
| **Source** | crypto-strategy-research Cycles 31, 33 |
| **Expected Return** | 68% directional accuracy for 9-11AM KST window |
| **Required Data** | ETF flow data (Farside Investors API or scrape, delayed 1 day) |
| **Impl. Difficulty** | **Medium** - daily data fetch + regime modifier |
| **Key Parameters** | Inflow threshold ($100M), lookback (4 weeks), application window (9-11 AM KST) |
| **Priority** | **P1** |

### 2.3 Binance Funding Rate Signal

| Item | Detail |
|------|--------|
| **Description** | Binance perpetual funding rates >0.05% lead Upbit retail FOMO by 6-18 hours. Use as a leading indicator for momentum entries. |
| **Source** | crypto-strategy-research Cycle 13; auto-invest Cycles 37-39 |
| **Expected Return** | Improved entry timing, not standalone alpha |
| **Required Data** | Binance Futures funding rate API (public, no auth) |
| **Impl. Difficulty** | **Medium** - new data fetcher + signal integration |
| **Key Parameters** | Threshold (0.05%), divergence detection, lead time (6-18h) |
| **Priority** | **P1** |

### 2.4 KVSI (Korean Volume Share Indicator)

| Item | Detail |
|------|--------|
| **Description** | Ratio of Upbit volume to global volume. KVSI 20-40% = healthy pump. KVSI >80% = retail exhaustion / exit signal (72% accuracy). |
| **Source** | crypto-strategy-research Cycle 34 |
| **Expected Return** | Exit signal captures top within 5% error in 72% of altcoin pumps |
| **Win Rate** | 58% for momentum entries when KVSI crosses 7d MA |
| **Required Data** | Upbit volume (existing) + Binance/global volume (public API) |
| **Impl. Difficulty** | **Medium** - volume aggregation across exchanges |
| **Key Parameters** | Exhaustion threshold (80%), healthy range (20-40%), MA period (7d/30d) |
| **Priority** | **P1** |

### 2.5 Enhanced Regime Detection (UBMI)

| Item | Detail |
|------|--------|
| **Description** | Replace simple momentum-based regime with UBMI (Upbit Market Index) > 120-day MA for Bull/Bear classification. Reduces MDD by up to 50%. |
| **Source** | crypto-strategy-research Cycle 4 |
| **Expected Return** | MDD improvement up to 50% |
| **Required Data** | UBMI index or proxy (volume-weighted Upbit top-20 average) |
| **Impl. Difficulty** | **Medium** - extend `RegimeDetector` with UBMI calculation |
| **Priority** | **P2** |

---

## Tier 3: Microstructure Alpha (Need WebSocket / architecture changes)

### 3.1 Order Book Imbalance (OBI) Scalper

| Item | Detail |
|------|--------|
| **Description** | OBI (bid-ask volume ratio) >0.75 predicts 0.1% price moves within 30 seconds. 62% win rate. OBI explains 70-80% of short-term price discovery. |
| **Source** | crypto-strategy-research Cycles 11, 39; auto-invest Cycle 138 |
| **Expected Return** | 3-5% monthly (compounded) |
| **MDD** | -8% (with 0.5% per-trade stop) |
| **Required Data** | Real-time orderbook via Upbit WebSocket (top 5-15 levels) |
| **Impl. Difficulty** | **High** - needs WebSocket orderbook stream, sub-second execution loop |
| **Architecture Change** | New `WebSocketDataProvider`, separate fast-loop runtime |
| **Key Parameters** | OBI threshold (0.75), time-stop (60s), fee hurdle (0.15% gross) |
| **Priority** | **P2** |

### 3.2 Iceberg Order Detection

| Item | Detail |
|------|--------|
| **Description** | Detect hidden liquidity when trade volume > visible orderbook size at a price. Iceberg bids = strong support floor. Sharpe improvement +0.4 to +0.7. |
| **Source** | crypto-strategy-research Cycles 35, 41 |
| **Expected Return** | 12-20 bps slippage reduction; Sharpe +0.4 to +0.7 |
| **Required Data** | Synchronized trade + orderbook WebSocket streams (sequential_id matching) |
| **Impl. Difficulty** | **High** - sub-millisecond stream synchronization |
| **Priority** | **P3** |

### 3.3 VPIN (Volume-Synchronized Probability of Informed Trading)

| Item | Detail |
|------|--------|
| **Description** | Measures order flow toxicity. VPIN >0.8 predicts iceberg wall failure with 74% accuracy and 42s lead time. Dynamic thresholds by tick size improve F1 from 0.68 to 0.82. |
| **Source** | crypto-strategy-research Cycles 43, 44 |
| **Expected Return** | Risk signal, not direct alpha |
| **Required Data** | Tick-level trade data, volume bucketing |
| **Impl. Difficulty** | **High** - needs continuous trade flow aggregation |
| **Priority** | **P3** |

---

## Tier 4: Cross-Exchange / Advanced (Major new infrastructure)

### 4.1 Upbit-Bithumb Local Arbitrage

| Item | Detail |
|------|--------|
| **Description** | Delta-neutral arb between Upbit and Bithumb using dual-balance sync. 0.1-0.4% typical gap. |
| **Source** | auto-invest Cycle 141 |
| **Expected Return** | 15-25% APY |
| **Required Data** | Bithumb API integration |
| **Impl. Difficulty** | **Very High** - needs Bithumb exchange adapter, dual-balance management |
| **Priority** | **P3** |

### 4.2 Binance-Upbit Latency Arbitrage

| Item | Detail |
|------|--------|
| **Description** | Binance leads Upbit by 200ms-1.5s. Capture 0.2-0.5% price gaps during high volatility. |
| **Source** | crypto-strategy-research Cycles 20, 37 |
| **Expected Return** | 0.2-0.5% per event |
| **Required Data** | Binance + Upbit real-time price streams |
| **Impl. Difficulty** | **Very High** - needs co-location (AWS Seoul), sub-second execution |
| **Priority** | **P3** |

### 4.3 Listing Pump Detection

| Item | Detail |
|------|--------|
| **Description** | Monitor Upbit on-chain test wallets for pre-announcement alpha. 30min-4hr window before official listing notice. |
| **Source** | crypto-strategy-research Cycles 28, 29 |
| **Expected Return** | ~52% average, peaks >500% |
| **Accuracy** | 76% (with UDC participation filter) |
| **Required Data** | On-chain wallet monitoring (Upbit 18 / Upbit 3 addresses) |
| **Impl. Difficulty** | **Very High** - needs blockchain node or explorer API, sub-minute detection |
| **Risk Notes** | Regulatory grey area under VUAP Act. FSS monitors for front-running. |
| **Priority** | **P3 (regulatory risk)** |

### 4.4 Social Sentiment Pipeline

| Item | Detail |
|------|--------|
| **Description** | Korean social mentions (Telegram/Coinpan) lead Upbit VPIN spikes by 2-10 minutes. Mention velocity >5/min = 65% breakout predictor. |
| **Source** | crypto-strategy-research Cycle 22, 45; auto-invest Cycles 46, 150 |
| **Expected Return** | MDD reduction 15-20%; pump detection 78% accuracy |
| **Required Data** | Telegram API (Telethon), YouTube (y2i), LLM classification |
| **Impl. Difficulty** | **Very High** - NLP pipeline, external scraping infrastructure |
| **Priority** | **P3** |

---

## Risk Management Enhancements

### R1. Fractional Kelly Position Sizing

| Item | Detail |
|------|--------|
| **Description** | Replace fixed risk-per-trade with 1/2 or 1/4 Kelly Criterion based on per-strategy win rate and payoff ratio. |
| **Source** | crypto-strategy-research Cycle 12 |
| **Impact** | MDD reduction >50% vs. fixed sizing |
| **Impl. Difficulty** | **Low** - extend `RiskManager.size_position()` with Kelly formula |
| **Priority** | **P1** |

### R2. Anomaly Detection Kill-Switch

| Item | Detail |
|------|--------|
| **Description** | Hierarchical safety: Warning (reduce size 50%) -> Hard Stop (cancel all, flatten). Predict crashes 30-120s in advance using selling breadth across symbols. |
| **Source** | crypto-strategy-research Cycle 26 |
| **Impl. Difficulty** | **Medium** - multi-symbol breadth check + circuit breaker in `MultiSymbolRuntime` |
| **Priority** | **P1** |

### R3. Risk Parity Allocation

| Item | Detail |
|------|--------|
| **Description** | Inverse-volatility weighting across wallets/symbols using 60-day rolling covariance. Reduces portfolio volatility by 25%. |
| **Source** | crypto-strategy-research Cycle 23 |
| **Impl. Difficulty** | **Medium** - new allocation module, periodic rebalancing |
| **Priority** | **P2** |

---

## Tax Optimization Module

### T1. Tax-Loss Harvesting (2027 Readiness)

| Item | Detail |
|------|--------|
| **Description** | No wash-sale rule in Korea. Sell losers and immediately re-buy to realize tax losses. 22:1 benefit-to-cost ratio. Dec 15-30 is the critical window. |
| **Source** | crypto-strategy-research Cycles 32, 47, 49; auto-invest Cycles 10, 148 |
| **Tax Saving** | Up to 66% reduction on a 1,000M KRW portfolio |
| **Impl. Difficulty** | **Medium** - cost basis tracking + sell-rebuy automation |
| **Priority** | **P1 (time-sensitive for 2026 year-end)** |

### T2. Basis Reset (Dec 31, 2026)

| Item | Detail |
|------|--------|
| **Description** | 2027 tax law uses the higher of actual cost or Dec 31 2026 market value as cost basis. Auto-record Dec 31 valuations. |
| **Source** | crypto-strategy-research Cycle 32; auto-invest Cycles 10, 47 |
| **Tax Rate** | 22% (national 20% + local 2%) on gains above 2.5M KRW annual exemption |
| **Impl. Difficulty** | **Low** - snapshot portfolio valuation at midnight Dec 31 |
| **Priority** | **P0 (must be ready by Dec 2026)** |

---

## Backtest & Validation Requirements

| Method | Description | Source |
|--------|-------------|--------|
| **Walk-Forward Analysis (WFA)** | 6-month in-sample, 1-month out-of-sample rolling window. WFE >85% confirms robustness. | Cycle 14 |
| **Regime-Specific Testing** | Separate backtest results for Bull/Sideways/Bear periods. | Cycle 4 |
| **Slippage Modeling** | Use Upbit-specific 0.05% fee + 0.05% slippage assumption. TWAP for large orders. | Cycle 5 |
| **Multi-Symbol Validation** | Test each strategy across all 4 configured symbols independently. | Current architecture |

---

## Implementation Roadmap

### Phase 1 (Immediate - Week 1-2)
1. **Volatility Breakout Strategy** (P0) - new strategy class
2. **Kimchi Premium Filter** (P0) - new data source + filter
3. **Basis Reset Snapshot** (P0) - simple cron job
4. **Fractional Kelly Sizing** (P1) - extend RiskManager

### Phase 2 (Short-term - Week 3-4)
5. **Altcoin Rotation via BTC.D** (P0) - new strategy + external API
6. **Weekend Regime Adjustment** (P1) - extend RegimeDetector
7. **ETF Inflow Signal** (P1) - daily data fetch
8. **Anomaly Kill-Switch** (P1) - circuit breaker

### Phase 3 (Medium-term - Month 2)
9. **Binance Funding Rate Signal** (P1) - new data source
10. **KVSI Monitor** (P1) - cross-exchange volume
11. **Tax-Loss Harvesting Module** (P1) - portfolio tracking
12. **Risk Parity Allocation** (P2) - rebalancing logic

### Phase 4 (Long-term - Month 3+)
13. **OBI Scalper** (P2) - WebSocket infrastructure
14. **Enhanced UBMI Regime** (P2) - market index
15. **Iceberg Detection** (P3) - microstructure
16. **Cross-Exchange Arbitrage** (P3) - multi-exchange

---

## Key Numbers Reference

| Metric | Value | Source |
|--------|-------|--------|
| Volatility Breakout CAGR | 40-80% | crypto-strategy Cycle 1 |
| Altcoin Rotation CAGR | 60-66% | crypto-strategy Cycle 25 |
| Kimchi Premium MDD reduction | -25% -> -12% | crypto-strategy Cycle 2 |
| OBI Win Rate (30s window) | 62% | auto-invest Cycle 138 |
| KVSI Exit Accuracy | 72% | crypto-strategy Cycle 34 |
| ETF Inflow Directional Accuracy | 68% | crypto-strategy Cycle 31 |
| Iceberg Sharpe Improvement | +0.4 to +0.7 | crypto-strategy Cycle 35 |
| VPIN Wall Failure Prediction | 74% accuracy, 42s lead | crypto-strategy Cycle 43 |
| Binance-Upbit Lead Time | 200ms - 1.5s | crypto-strategy Cycle 37 |
| Weekend Liquidity Drop | 20-30% | crypto-strategy Cycle 48 |
| CME Gap Fill Probability | 70% within 24h | crypto-strategy Cycle 33 |
| Kelly Fraction MDD Reduction | >50% | crypto-strategy Cycle 12 |
| Risk Parity Volatility Reduction | 25% | crypto-strategy Cycle 23 |
| TLH Tax Reduction | Up to 66% | crypto-strategy Cycle 32 |
| Upbit Fee (KRW market) | 0.05% | auto-invest Cycle 138 |
| Korean Crypto Tax Rate (2027) | 22% | crypto-strategy Cycle 10 |
| Annual Exemption (2027) | 2,500,000 KRW | crypto-strategy Cycle 32 |

---

## Regulatory Guardrails

- **VUAP Act Compliance**: Avoid wash trading patterns, excessive cancellations, and self-trading.
  FSS uses AI to monitor bot behavior. (auto-invest Cycle 2)
- **API Rate Limits**: Upbit allows 10 req/s REST, 5 WebSockets per IP. Use WebSocket for market
  data, REST for execution only. (crypto-strategy Cycle 24)
- **Travel Rule**: 5-30 minute delays on cross-exchange transfers. Pre-position liquidity.
  (auto-invest Cycle 36)
- **Listing Front-Running**: Monitoring Upbit wallets for pre-listing alpha is in a regulatory
  grey area. Proceed with caution. (crypto-strategy Cycle 29)

---

## Pending Updates (2026-03-24 15:00 KST ~)

The following areas are expected to receive additional research notes after 15:00 KST today:

- [ ] Deeper backtests for Volatility Breakout with 2026 Q1 Upbit data
- [ ] Cross-validation of KVSI thresholds across different market cap tiers
- [ ] Refinement of Weekend Regime parameters based on 2026 CME gap data
- [ ] Additional Kimchi Premium analysis for newly listed tokens
- [ ] Sentiment pipeline prototype results (Telegram/YouTube)
- [ ] Updated regulatory guidance from FSS Q1 2026 review

This document will be updated as new research becomes available.
