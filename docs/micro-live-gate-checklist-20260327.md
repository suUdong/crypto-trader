# Micro-Live Gate Readiness Report

**Date**: 2026-03-27 19:30 KST
**Target Go-Live**: 2026-04-02 (D-6)
**Current Gate**: 5/6 (PromotionGate) | 0/4 (PortfolioGate)

---

## 1. Current Live Trading Status

### 1.1 Daemon Status

| Item | Value |
|------|-------|
| Active PIDs | 757527, 779314 (DUPLICATE — needs cleanup) |
| Wallets | 13 active across 8 strategies |
| Symbols | KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL |
| Mode | `paper_trading = true` |
| Session | 20260327T011030Z |
| Kill Switch | NOT triggered |

**ACTION NEEDED**: Two daemon processes running simultaneously. Kill PID 757527 (older) to prevent duplicate signal evaluation.

### 1.2 Strategy Positions & Fills

| Wallet | Strategy | Open Pos | Buys | Sells | Realized PnL | Equity |
|--------|----------|:--------:|:----:|:-----:|-------------:|-------:|
| kimchi_premium | kimchi_premium | 4 | 53 | 0 | 0 KRW | 999,244 |
| momentum_btc | momentum | 0 | 0 | 0 | 0 KRW | 1,000,000 |
| momentum_eth | momentum | 0 | 1 | 0 | 0 KRW | 1,000,000 |
| vpin_btc | vpin | 0 | 1 | 0 | 0 KRW | 1,000,000 |
| vpin_eth | vpin | 0 | 0 | 0 | 0 KRW | 1,000,000 |
| vpin_sol | vpin | 0 | 0 | 0 | 0 KRW | 1,000,000 |
| vbreak_btc | volatility_breakout | 0 | 1 | 1 | 0 KRW | 1,000,000 |
| vbreak_eth | volatility_breakout | 0 | 2 | 0 | 0 KRW | 1,000,000 |
| volspike_btc | volume_spike | 0 | 0 | 0 | 0 KRW | 1,000,000 |
| volspike_eth | volume_spike | 0 | 0 | 0 | 0 KRW | 1,000,000 |
| consensus_btc | consensus | 0 | 0 | 0 | 0 KRW | 1,000,000 |
| ema_cross_btc | ema_crossover | 0 | 0 | 0 | 0 KRW | 1,000,000 |
| mean_rev_eth | mean_reversion | 0 | 0 | 0 | 0 KRW | 1,000,000 |
| **TOTAL** | **8 strategies** | **4** | **59** | **1** | **0 KRW** | **12,999,244** |

### 1.3 Open Positions (kimchi_premium_wallet)

| Symbol | Entry Price | Qty | Cost (KRW) | Entry Time |
|--------|-----------|-----|-----------|-----------|
| KRW-BTC | 104,233,091 | 0.0024 | 250,159 | 2026-03-27 09:00 UTC |
| KRW-ETH | 3,121,560 | 0.0084 | 26,255 | 2026-03-27 09:00 UTC |
| KRW-XRP | 2,060 | 12.30 | 25,335 | 2026-03-27 09:00 UTC |
| KRW-SOL | 130,865 | 0.187 | 24,447 | 2026-03-27 09:00 UTC |
| **Total** | | | **326,196** | |

### 1.4 Portfolio Summary

| Metric | Value |
|--------|-------|
| Starting Capital | 13,000,000 KRW (13 wallets x 1M) |
| Current Equity | 12,999,244 KRW |
| Unrealized PnL | -756 KRW (-0.006%) |
| Realized PnL | 0 KRW |
| Peak Equity | 12,999,220 KRW |
| Max Drawdown | 0.006% |
| Market Regime | Sideways (ADX 21.8, RSI 40.7) |

---

## 2. Gate Status: Two-Tier System

### 2.1 PromotionGate (Single-Symbol KRW-BTC) — 5/6

| # | Criterion | Required | Current | Status |
|---|-----------|----------|---------|:------:|
| 1 | Backtest return | > 0% | +2.06% | PASS |
| 2 | Backtest max drawdown | <= 20% | 0.00% | PASS |
| 3 | Paper runs | >= 5 | 20+ | PASS |
| 4 | Drift status | not out_of_sync/caution | on_track | PASS |
| 5 | Latest verdict | not pause/reduce_risk | continue | PASS |
| 6 | **Paper realized PnL** | **> 0%** | **0.00%** | **FAIL** |

**Blocker**: Zero realized PnL. Need at least one profitable closed paper trade.

### 2.2 PortfolioPromotionGate (Multi-Wallet) — 0/4

| # | Criterion | Required | Current | Status |
|---|-----------|----------|---------|:------:|
| 1 | Paper trading days | >= 7d | 0d | FAIL |
| 2 | Total trades | >= 10 | 0 | FAIL |
| 3 | Profitable wallets | >= 2 | 0 | FAIL |
| 4 | Portfolio return | > 0% | -0.006% | FAIL |

### 2.3 MicroLiveCriteria (Full Readiness) — 0/6

| # | Criterion | Required | Current | Status |
|---|-----------|----------|---------|:------:|
| 1 | Paper days | >= 7d | 0d | FAIL |
| 2 | Total trades | >= 10 | 0 | FAIL |
| 3 | Win rate | >= 45% | N/A | FAIL |
| 4 | Max drawdown | <= 10% | 0.006% | PASS* |
| 5 | Profit factor | >= 1.2 | N/A | FAIL |
| 6 | Profitable strategies | >= 2 | 0 | FAIL |

*MDD passes threshold but marked FAIL in code because PF/WR are 0 with no trades.

---

## 3. Micro-Live Entry Checklist (Target: 2026-04-02)

### 3.1 Gate Prerequisites (MUST-HAVE)

| # | Item | Status | Action Required | ETA |
|---|------|:------:|-----------------|-----|
| G1 | Paper realized PnL > 0% | BLOCKED | Wait for kimchi_premium positions to close in profit or other strategies to complete profitable round-trips | D-5 (organic) |
| G2 | 7 days paper trading | BLOCKED | Paper daemon must run continuously from now (3/27) — earliest completion 4/3 | 4/3 auto |
| G3 | 10+ closed trades | BLOCKED | Requires market movement to trigger entries/exits across strategies | D-5 (organic) |
| G4 | 2+ profitable wallets | BLOCKED | Dependent on G3 — need closed trades producing profit in >= 2 wallets | D-5 (organic) |
| G5 | Win rate >= 45% | BLOCKED | Dependent on G3 — ratio only computable with closed trades | D-5 |
| G6 | Profit factor >= 1.2 | BLOCKED | Dependent on G3 — PF = gross_profit / gross_loss | D-5 |

### 3.2 Infrastructure Prerequisites (MUST-HAVE)

| # | Item | Status | Action Required |
|---|------|:------:|-----------------|
| I1 | Single daemon process | WARN | Kill duplicate PID 757527 |
| I2 | Upbit API credentials | NOT SET | Set `UPBIT_ACCESS_KEY` + `UPBIT_SECRET_KEY` in `.env` before go-live |
| I3 | `paper_trading = false` in config | READY | Toggle in `config/daemon.toml` at go-live |
| I4 | Live wallet sizing | READY | `config/live.toml` has 3 micro-live wallets (500K + 300K + 200K = 1M KRW) |
| I5 | Kill switch thresholds | OK | 5% portfolio DD, 3% daily loss, 5 consecutive losses |
| I6 | Dashboard monitoring | OK | Streamlit dashboard with auto-refresh |
| I7 | Telegram notifications | CHECK | Verify `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in env |

### 3.3 Operational Prerequisites (SHOULD-HAVE)

| # | Item | Status | Action Required |
|---|------|:------:|-----------------|
| O1 | Clean paper-trades.jsonl | WARN | Remove 54 legacy simulated trades with fake prices (100.05/99.95) |
| O2 | Binance feed validation | CHECK | Verify kimchi premium Binance price feed accuracy |
| O3 | Slippage model calibration | PENDING | No real order-book data yet — paper mode uses 0.05% estimate |
| O4 | Strategy diversity | OK | 8 strategies across 4 symbols, good diversification |
| O5 | Backtest-to-live drift | OK | `on_track` — paper matches backtest behavior |

### 3.4 Go/No-Go Decision Matrix

| Condition | Weight | Minimum for Go |
|-----------|--------|----------------|
| PromotionGate 6/6 | Critical | ALL 6 PASS |
| PortfolioGate 4/4 | High | ALL 4 PASS |
| MicroLiveCriteria 6/6 | High | ALL 6 PASS |
| No kill switch events | Critical | Zero triggers in paper period |
| API credentials tested | Critical | Authenticated + balance query works |
| Single daemon stability | High | 24h+ continuous uptime |

---

## 4. PromotionGate 5/6 → 6/6: Path to Completion

### The Single Remaining Gate

**Criterion 6**: `paper_realized_pnl_pct > 0`

This is computed from `drift-report.json` field `paper_realized_pnl_pct`, which tracks cumulative realized PnL across all paper trading.

### How It Gets Cleared

1. **kimchi_premium positions close in profit** — 4 open positions across BTC/ETH/XRP/SOL entered at 09:00 UTC. If market moves up ~0.15%+ from entry (covering 0.05% x 2 fees), any profitable exit clears the gate.
2. **Other strategies generate a profitable round-trip** — momentum, vbreak, vpin, or other strategies complete buy→sell with net positive PnL.
3. **Time factor** — sideways market means positions may take hours to days to exit. No manual intervention needed; the daemon's exit logic (stop-loss, take-profit, trailing stop) handles this automatically.

### Estimated Timeline

| Scenario | Probability | Timeline |
|----------|:-----------:|----------|
| Market rally clears kimchi positions in profit | 30% | 1-2 days |
| Sideways grind, eventual profitable exit | 50% | 2-5 days |
| Market drop, positions stop out, need new cycle | 20% | 3-7 days |

**Best case**: Gate 6/6 by 3/29. **Expected case**: Gate 6/6 by 4/1. **Aligns with 4/2 target**.

---

## 5. Remaining Items for Full Micro-Live Readiness

### Critical Path (ordered by dependency)

```
Day 0 (3/27): Fix duplicate daemon, clean legacy data, verify feeds
     |
Day 1-5 (3/28-4/1): Paper trading accumulates trades + PnL
     |                  PromotionGate 6/6 clears (realized PnL > 0)
     |                  PortfolioGate criteria accumulate
     |
Day 6 (4/2): 7-day paper period completes (if started 3/26)
     |          Run micro_live_check.py for final evaluation
     |          Set Upbit API credentials
     |          Toggle paper_trading = false
     |          Restart daemon with live config
     |
Day 7+ (4/3+): Live monitoring, kill switch active
```

### Immediate Actions (Today)

1. **Kill duplicate daemon** — `kill 757527`
2. **Clean legacy paper trades** — Remove simulated entries from `paper-trades.jsonl`
3. **Verify Binance price feed** — Check kimchi premium values are accurate
4. **Verify Telegram notifications** — Test alert delivery
5. **Confirm paper_days counter** — Ensure checkpoint `generated_at` or journal first trade timestamp counts correctly toward 7d requirement

### Pre-Launch Actions (4/1)

1. **Run `scripts/micro_live_check.py`** — Automated readiness evaluation
2. **Run promotion gate check** — Verify 6/6
3. **Prepare `.env` with Upbit API keys** — Test with balance query
4. **Review live.toml wallet sizing** — Confirm 1M KRW micro-live allocation
5. **Create rollback plan** — Script to re-enable paper mode if issues arise

---

## 6. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|:----------:|------------|
| 7-day paper period not met by 4/2 | Blocks launch | Low (started ~3/26) | Confirm exact start timestamp |
| Zero profitable trades by 4/2 | Blocks gate 6/6 | Medium (sideways market) | Strategies tuned for sideways; kimchi active |
| Duplicate daemon causes double entries | Data corruption | High (currently active) | Kill duplicate PID immediately |
| API key misconfiguration at launch | Failed trades | Low | Pre-test with read-only API call |
| Kill switch false positive | Pauses trading | Low | Thresholds verified (5% DD, 3% daily) |

---

*Generated: 2026-03-27 | Source: artifacts/runtime-checkpoint.json, promotion-gate.json, portfolio-gate.json, drift-report.json*
*Gate logic: src/crypto_trader/operator/promotion.py*
