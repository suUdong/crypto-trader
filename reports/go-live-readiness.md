# Go-Live Readiness Report: crypto-trader

**Date:** 2026-03-28
**Capital:** ₩5,700,000 (confirmed via health.json: ₩5,703,454 total equity)
**Current Mode:** `paper_trading = true`
**Daemon Status:** Running, healthy, 5 wallets, 1 open position

---

## Executive Summary

**VERDICT: NOT READY FOR LIVE TRADING**

There are **2 critical blockers** and **1 warning** that must be resolved before switching `paper_trading = false`.

| Category | Status | Details |
|----------|--------|---------|
| Live Broker Implementation | BLOCKER | No live order execution engine exists |
| API Credentials | BLOCKER | Upbit keys empty in daemon.toml |
| Kill Switch / Safety Rails | PASS | Tiered system fully implemented |
| Risk Configuration | PASS | Conservative and within hard limits |
| Daemon Infrastructure | PASS | Restart script, checkpointing, health checks |
| Telegram Alerts | WARNING | Bot token/chat_id empty — no live alerts |

---

## 1. Critical Blockers

### BLOCKER 1: No Live Broker Implementation

The system has **only a `PaperBroker`** (`src/crypto_trader/execution/paper.py`). There is no `LiveBroker`, `UpbitBroker`, or any code that submits real orders to Upbit.

**Evidence:**
- `execution/` directory contains only `paper.py` and `__init__.py`
- `cli.py:1751` always creates `PaperBroker(...)` regardless of `paper_trading` flag
- `pipeline.py` calls `broker.submit_order()` which only exists on `PaperBroker`
- `pyupbit` is imported **only for market data** (candle fetching), not for order execution
- No `buy_market_order`, `sell_market_order`, or any Upbit trading API calls exist in the codebase

**Impact:** Setting `paper_trading = false` would either:
- Continue paper trading (orders stay simulated), or
- Crash at startup due to missing credentials validation (`config.py:1069-1077`)

**Required Work:**
1. Implement `LiveBroker` class wrapping `pyupbit.Upbit` for real order execution
2. Add order confirmation and fill verification
3. Handle partial fills, network timeouts, rate limits
4. Add dry-run mode for integration testing before real capital deployment
5. Wire `paper_trading` flag to broker selection in CLI wallet builder

### BLOCKER 2: API Credentials Not Configured

```toml
[credentials]
upbit_access_key = ""
upbit_secret_key = ""
```

**Evidence:** `config.py:1069-1077` validates credentials for live mode:
```python
if (
    not allow_missing_live_credentials
    and not config.trading.paper_trading
    and not config.credentials.has_upbit_credentials
):
    errors.append("Live trading requires Upbit API credentials...")
```

Setting `paper_trading = false` with empty credentials will raise `ValueError` on startup.

**Required Work:**
1. Generate Upbit API keys with trading permissions
2. Set via environment variables (`CT_UPBIT_ACCESS_KEY`, `CT_UPBIT_SECRET_KEY`) — NOT in TOML file
3. Restrict API key IP whitelist to daemon host

---

## 2. Safety Rail Verification (PASS)

### 2.1 Hard Safety Constants (`config.py`)

| Constant | Value | Status |
|----------|-------|--------|
| `HARD_MAX_DAILY_LOSS_PCT` | 5% | Enforced — config cannot exceed |
| `SAFE_MAX_CONSECUTIVE_LOSSES` | 3 | Enforced — auto-stop after 3 losses |
| `SAFE_DEFAULT_MAX_POSITION_PCT` | 10% | Enforced — no single position > 10% |

All three constants are imported and enforced in both `RiskManager` and `KillSwitch`.

### 2.2 Kill Switch (`risk/kill_switch.py`)

**Tiered Response System:**

| Tier | Threshold | Action |
|------|-----------|--------|
| WARN | 50% of limit | Warning active, gradual position size penalty |
| REDUCE | 75% of limit | Position size cut to 50% |
| HALT | 100% of limit | All trading stopped |

**Kill Switch Config (daemon.toml):**

| Parameter | Value | Hard Limit | Compliant? |
|-----------|-------|------------|------------|
| `max_portfolio_drawdown_pct` | 8% | — | YES |
| `max_daily_loss_pct` | 3% | 5% hard cap | YES (below cap) |
| `max_consecutive_losses` | 3 | 3 hard cap | YES |
| `max_strategy_drawdown_pct` | 6% | — | YES |
| `cooldown_minutes` | 120 | — | YES (conservative) |

**Kill switch state persistence:** Saves/loads to `artifacts/kill-switch.json`. Auto-loads on live startup (`multi_runtime.py:101-103`).

### 2.3 Risk Manager (`risk/manager.py`)

| Feature | Status | Detail |
|---------|--------|--------|
| Position sizing | Kelly fraction (half-Kelly capped at 25%) | Safe |
| Drawdown scaling | Exponential reduction as drawdown increases | Safe |
| Streak multiplier | -15% per consecutive loss (floor 40%) | Safe |
| Loss streak stop | Auto-halt at 3 consecutive losses | Safe |
| Auto-pause | PF < 0.7 over 20 trades pauses strategy | Safe |
| Daily loss circuit breaker | Force-close all positions at limit | Safe |
| Concurrent position throttle | Reduces allowed positions as losses mount | Safe |
| Max position cap | Hard 10% cap, never expanded by streaks | Safe |

### 2.4 Daemon Risk Config (daemon.toml `[risk]`)

| Parameter | Value | Assessment |
|-----------|-------|------------|
| `risk_per_trade_pct` | 1% | Conservative |
| `stop_loss_pct` | 3% | Standard |
| `take_profit_pct` | 8% | 2.67:1 reward:risk — good |
| `max_daily_loss_pct` | 3% | Below 5% hard cap |
| `max_concurrent_positions` | 3 | Reasonable for 5 wallets |
| `max_position_pct` | 10% | At safety limit |
| `min_entry_confidence` | 0.45 | Moderate filter |
| `partial_tp_pct` | 50% | Takes profits incrementally |

---

## 3. Daemon Infrastructure (PASS)

### 3.1 Restart Script (`scripts/restart_daemon.sh`)

- Graceful SIGTERM with 30s timeout, then SIGKILL
- PID matching by config path (multi-daemon safe)
- Checkpoint verification before restart
- Position restoration check from logs
- Heartbeat confirmation (30s timeout)

### 3.2 Runtime Features

| Feature | Status |
|---------|--------|
| Auto-restart with backoff | 15s backoff, unlimited retries |
| Runtime checkpoint | `artifacts/runtime-checkpoint.json` — wallet states, positions, correlation |
| Health check | `artifacts/health.json` — confirmed working |
| Heartbeat | `artifacts/daemon-heartbeat.json` |
| Strategy run journal | JSONL append log |
| Paper trade journal | JSONL append log |
| Daily performance tracking | JSON snapshots |

### 3.3 Wallet Allocation

| Wallet | Strategy | Capital | Share | 90d ROI |
|--------|----------|---------|-------|---------|
| vpin_sol | VPIN | ₩2,500,000 | 43.9% | +1.64% |
| volspike_btc | Volume Spike | ₩1,300,000 | 22.8% | +1.03% |
| momentum_sol | Momentum | ₩1,100,000 | 19.3% | +0.78% |
| momentum_eth | Momentum | ₩450,000 | 7.9% | +0.24% |
| vpin_eth | VPIN | ₩350,000 | 6.1% | +0.23% |
| **Total** | | **₩5,700,000** | **100%** | |

Allocation is ROI-weighted with low-sample caps. Two negative-ROI wallets correctly disabled.

---

## 4. Warning: No Telegram Alerts

```toml
[telegram]
bot_token = ""
chat_id = ""
```

Live trading without alert notifications is risky. Kill switch triggers, position changes, and daily PnL reports won't reach you. Configure before go-live.

---

## 5. Go-Live Action Plan

### Phase 1: Build Live Broker (Required)
- [ ] Implement `LiveBroker` class in `src/crypto_trader/execution/live.py`
- [ ] Wrap `pyupbit.Upbit.buy_market_order()` / `sell_market_order()`
- [ ] Add order status polling and fill confirmation
- [ ] Handle network errors, rate limits, partial fills
- [ ] Wire `paper_trading` flag to broker selection in CLI
- [ ] Integration test with small real order (₩5,000 minimum)

### Phase 2: Credentials & Alerts (Required)
- [ ] Generate Upbit API keys (trading permission, IP whitelist)
- [ ] Set `CT_UPBIT_ACCESS_KEY` / `CT_UPBIT_SECRET_KEY` environment variables
- [ ] Configure Telegram bot token and chat_id
- [ ] Verify alert delivery (kill switch test notification)

### Phase 3: Staged Rollout (Recommended)
- [ ] Start with 1 wallet only (smallest: vpin_eth ₩350,000)
- [ ] Run 48h live with kill switch at tighter limits (5% portfolio drawdown)
- [ ] Compare live fills vs paper broker assumptions (slippage, fees)
- [ ] Gradually add wallets over 1-2 weeks
- [ ] Monitor slippage_monitor deviations

### Phase 4: Full Live
- [ ] Set `paper_trading = false` in daemon.toml
- [ ] Restart daemon via `scripts/restart_daemon.sh`
- [ ] Confirm heartbeat and position state
- [ ] Monitor first 24h with tighter kill switch, then relax to current config

---

## Appendix: Config Validation Chain

```
daemon.toml
  └─ load_config() (config.py:267)
      ├─ paper_trading = True → PaperBroker (current)
      ├─ paper_trading = False + no credentials → ValueError (crash)
      └─ paper_trading = False + credentials → PaperBroker (BUG: no LiveBroker exists)
          └─ kill_switch.load() auto-triggered for live mode
```

The `paper_trading` flag currently only controls:
1. Credential validation gate (`config.py:1069`)
2. Kill switch state auto-load (`multi_runtime.py:101`)

It does **NOT** switch the broker implementation — this is the core gap.
