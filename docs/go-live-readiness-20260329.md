# Go-Live Readiness Report

**Date**: 2026-03-29
**Portfolio**: KRW 5,700,000 (3 active wallets)
**Mode**: Paper Trading
**Target Go-Live**: TBD (criteria not yet met)

---

## 1. Paper Operation Period

| Metric | Current | Required | Status |
|--------|---------|----------|:------:|
| Paper start date | 2026-03-27 | - | - |
| Paper days elapsed | **2 days** (3/27 ~ 3/29) | >= 14 days | FAIL |
| Earliest eligible | 2026-04-10 | - | - |

Paper trading began 2026-03-27 with the first recorded trade at 07:00 UTC.
The 3-wallet P0 configuration (vpin_eth, momentum_sol, volspike_btc) was deployed
on 2026-03-29. Since the config change, **no new trades have been generated** due
to Fear & Greed Index = 12 (extreme fear) causing signal suppression.

---

## 2. Paper Performance vs POLICY Criteria

### 2.1 Portfolio Summary (all 9 closed trades)

| Metric | Current | POLICY Target | Gap | Status |
|--------|---------|---------------|-----|:------:|
| Win rate | **11.1%** (1W/8L) | >= 55% | -43.9pp | FAIL |
| Cumulative return | **-0.135%** (-7,695 KRW) | >= +2% (+114K) | -2.135pp | FAIL |
| MDD | **0.168%** (9,568 KRW) | <= 5% (285K) | within limit | PASS |
| Sharpe ratio | **0.16** (weekly) | >= 1.0 | -0.84 | FAIL |
| Paper period | **2 days** | >= 14 days | -12 days | FAIL |

**Result: 1/5 POLICY criteria met.**

### 2.2 Per-Wallet Breakdown

| Wallet | Trades | W/L | WR | PnL (KRW) | PnL% | Sharpe | Status |
|--------|:------:|-----|---:|----------:|-----:|-------:|:------:|
| vpin_eth | 3 | 1W/2L | 33% | +2,406 | +0.04% | ~1.14 | Best performer |
| momentum_sol | 1 | 0W/1L | 0% | -533 | -0.04% | N/A | Too few trades |
| volspike_btc | 0 | - | - | 0 | 0% | N/A | No trades (no_volume_spike) |
| *momentum_eth* | *1* | *0W/1L* | *0%* | *-3,376* | *-1.35%* | *~0* | *Disabled 3/29* |
| *kimchi_premium* | *2* | *0W/2L* | *0%* | *-3,820* | *-2.28%* | *N/A* | *Disabled (removed)* |
| *vbreak_btc/xrp* | *2* | *0W/2L* | *0%* | *-2,371* | - | *N/A* | *Disabled (removed)* |

*Italic = disabled wallets, trades from legacy config*

### 2.3 Active 3-Wallet Config (P0, since 2026-03-29)

| Wallet | Capital | Allocation | Backtest Sharpe | Backtest WR | Paper Trades |
|--------|--------:|:----------:|:--------------:|:-----------:|:------------:|
| vpin_eth | 3,500,000 | 61.4% | 1.11 | 60% | 3 (1W/2L) |
| momentum_sol | 1,200,000 | 21.1% | 1.55 | 50% | 1 (0W/1L) |
| volspike_btc | 1,000,000 | 17.5% | 3.00 | 71% | 0 |

**Critical issue**: Only 4 trades from active wallets. volspike_btc has zero trades
(spike_mult=3.0 unreachable in sideways market). Statistical significance requires 30+ trades.

---

## 3. Go-Live Readiness Checklist

### 3.1 Performance Gates (ALL required)

| # | Criterion | Required | Current | Status |
|---|-----------|----------|---------|:------:|
| P1 | Paper operation period | >= 14 days | 2 days | FAIL |
| P2 | Win rate | >= 55% | 11.1% | FAIL |
| P3 | Cumulative return | >= +2% | -0.135% | FAIL |
| P4 | Max drawdown | <= 5% | 0.168% | PASS |
| P5 | Sharpe ratio | >= 1.0 | 0.16 | FAIL |
| P6 | Minimum closed trades | >= 30 (statistical) | 9 | FAIL |

### 3.2 Infrastructure Gates (ALL required)

| # | Criterion | Status | Notes |
|---|-----------|:------:|-------|
| I1 | Upbit API credentials | NOT SET | Set before go-live |
| I2 | Single daemon process | OK | Fixed (was duplicate) |
| I3 | Kill switch configured | PASS | 8% portfolio DD, 3% daily, 3 consecutive |
| I4 | Telegram alerts | NOT VERIFIED | Bot token/chat ID empty in config |
| I5 | Staged go-live config | READY | `go_live_wallets = ["vpin_eth_wallet"]` |
| I6 | Dashboard monitoring | OK | Streamlit operational |
| I7 | Macro integration | OK | macro-intelligence active, F&G feeding |

### 3.3 Operational Gates (SHOULD-HAVE)

| # | Criterion | Status | Notes |
|---|-----------|:------:|-------|
| O1 | Backtest-to-live drift | on_track | Drift monitor active |
| O2 | Slippage model calibrated | PENDING | Using 0.05% estimate, no real data |
| O3 | Rollback plan documented | PENDING | Need script to re-enable paper mode |
| O4 | 2+ profitable wallets | FAIL | Only vpin_eth profitable |
| O5 | No kill switch triggers | PASS | Zero triggers in paper period |

---

## 4. Gap Analysis & Roadmap

### 4.1 Critical Gaps

| Gap | Severity | Root Cause | Resolution |
|-----|----------|------------|------------|
| 12 more paper days needed | Blocking | Started 3/27 | Wait until 4/10 minimum |
| Win rate 11% vs 55% target | Blocking | 5/9 trades from disabled losing strategies; F&G=12 suppression | P0 config should improve; need market regime shift |
| Cumulative return negative | Blocking | Legacy wallet losses (-11K) > vpin_eth gains (+2.4K) | Active 3-wallet config untested at scale |
| Sharpe 0.16 vs 1.0 target | Blocking | Too few trades, mostly losses | Needs 30+ trades from optimized config |
| volspike_btc idle | High | spike_mult=3.0 too high for sideways | Consider lowering to 2.0 or wait for volatility |

### 4.2 Roadmap to Go-Live

```
Phase 1: Observation (3/29 ~ 4/05) — 7 days
  - Run P0 3-wallet config continuously
  - Monitor for trades when F&G recovers above 20
  - Track vpin_eth as anchor wallet
  - If volspike_btc still zero trades by 4/02, lower spike_mult to 2.0

Phase 2: Evaluation (4/05 ~ 4/10) — 5 days
  - 14-day paper period completes 4/10
  - Evaluate POLICY criteria against 3-wallet-only trades
  - If win rate < 55% on 30+ trades: tune parameters, restart 14-day clock
  - If cumulative return still negative: reassess strategy allocation

Phase 3: Pre-Launch (4/10 ~ 4/12) — 2 days
  - Run micro_live_check.py for automated gate evaluation
  - Set Upbit API credentials, test with read-only call
  - Verify Telegram alerts end-to-end
  - Document rollback procedure
  - Final backtest vs paper drift check

Phase 4: Go-Live (4/12+ if all gates PASS)
  - Stage 1: vpin_eth_wallet only (go_live_wallets config ready)
  - Stage 2: Add momentum_sol after 48h stable live
  - Stage 3: Add volspike_btc after 1 week stable live
  - Kill switch active from minute 1
```

### 4.3 Decision Points

| Date | Decision | Criteria |
|------|----------|----------|
| 4/02 | Lower volspike_btc spike_mult? | 0 trades in 6 days |
| 4/05 | Continue or retune? | < 15 trades from active wallets |
| 4/10 | Go/No-Go evaluation | All 5 POLICY criteria |
| 4/12 | Go-live (if passed) | Performance + infra gates green |

---

## 5. Current Market Context

| Factor | Value | Impact |
|--------|-------|--------|
| Fear & Greed Index | 12 (Extreme Fear) | Blocks momentum entries, dampens all signals (0.9x multiplier) |
| Market regime | Sideways | Low volatility = fewer volume spikes, fewer momentum signals |
| BTC price | ~101.2M KRW | Stable, no trend |
| ETH price | ~3.04M KRW | EMA trend down, VPIN holding |
| Weekend | Yes | Lower volume, reduced signal quality |

**Implication**: Current extreme-fear regime is the worst case for generating paper trades.
Performance metrics will only become meaningful once F&G recovers above 20 and market
exits the sideways regime. This is actually a good stress test — if the system avoids
large losses during extreme fear, it validates the risk management layer.

---

## 6. Summary

| Category | Score | Details |
|----------|:-----:|---------|
| Performance Gates | **1/6** | Only MDD passes; all others blocked by insufficient trades and negative PnL |
| Infrastructure Gates | **4/7** | API creds, Telegram, slippage model pending |
| Operational Gates | **3/5** | Profitable wallets and rollback plan pending |
| **Overall Readiness** | **NOT READY** | Earliest possible go-live: **2026-04-12** |

**Bottom line**: The system needs at minimum 12 more days of paper trading. The P0
3-wallet optimization (deployed today) has strong backtest numbers (Sharpe 1.11-3.00)
but zero live validation yet. The extreme-fear market regime is suppressing trade
generation. Focus on continuous paper operation and parameter monitoring rather than
rushing to go-live.

---

*Sources: artifacts/paper-trades.jsonl, artifacts/daily-performance.json, artifacts/runtime-checkpoint.json, config/daemon.toml*
*Gate logic: src/crypto_trader/operator/promotion.py*
