# Daemon Performance Report

**Generated**: 2026-03-26 17:59 KST (2026-03-26 08:59 UTC)
**Scope**: `artifacts/` snapshot analysis for the latest daemon state plus the most recent observed log session
**Primary sources**: `artifacts/runtime-checkpoint.json`, `artifacts/daemon-heartbeat.json`, `artifacts/daemon.log`, `artifacts/kill-switch.json`

## Executive Summary

The latest snapshot in `artifacts/` shows a **3-wallet BTC/ETH paper-trading setup** with total equity of **2,999,568.01 KRW**, or **-431.99 KRW (-0.014%)** versus the 3,000,000 KRW paper baseline.

All realized loss is concentrated in **momentum**. `mean_reversion` and `composite` are flat, and the latest checkpoint shows **no open positions**. Operationally, the daemon artifact set is inconsistent: the newest checkpoint describes a 3-wallet session, while the newest observable `daemon.log` session ended earlier on 2026-03-26 16:36 KST after running a broader multi-wallet configuration. This means the repo has enough evidence to assess directionally, but not enough artifact consistency to claim a single uninterrupted production narrative.

## Latest Snapshot At 17:59 KST

Source of truth for this section:
- `artifacts/runtime-checkpoint.json`
- `artifacts/daemon-heartbeat.json`

| Metric | Value |
|-------|-------|
| Snapshot time | 2026-03-26 17:59:03 KST |
| PID | `3495008` |
| Iteration | `3` |
| Symbols | KRW-BTC, KRW-ETH |
| Wallet count | 3 |
| Total equity | 2,999,568.01 KRW |
| Net PnL | **-431.99 KRW** |
| Portfolio return | **-0.014%** |
| Realized PnL | **-431.99 KRW** |
| Open positions | 0 |
| Closed trades | 2 |

## Strategy Breakdown

| Wallet | Strategy | Equity | Realized PnL | Trades | Open Positions | Status |
|-------|----------|--------|-------------|--------|----------------|--------|
| `momentum_wallet` | Momentum | 999,568.01 KRW | **-431.99 KRW** | 2 | 0 | Only strategy with realized activity |
| `mean_reversion_wallet` | Mean Reversion | 1,000,000.00 KRW | 0 KRW | 0 | 0 | Idle |
| `composite_wallet` | Composite | 1,000,000.00 KRW | 0 KRW | 0 | 0 | Idle |
| **Portfolio** | | **2,999,568.01 KRW** | **-431.99 KRW** | **2** | **0** | |

Interpretation:
- The current loss is small in absolute terms and comes entirely from `momentum`.
- The latest snapshot is effectively flat from a portfolio-risk perspective.
- The more important issue is inactivity: 2 of 3 wallets are idle, and there is no open exposure to learn from at the snapshot time.

## Observed Session History From `daemon.log`

`artifacts/daemon.log` remains the best operational trail for what actually ran before the latest snapshot was written.

| Metric | Value |
|-------|-------|
| Log-covered runtime starts | 5 |
| Log-covered runtime stops | 5 |
| Last stop observed | 2026-03-26 16:36:05 KST |
| Longest visible run tail | 98 iterations |
| Filled orders in log | 5 |
| Filled buys | 5 |
| Filled sells | 0 |
| Filled orders by wallet | `kimchi_premium_wallet` only |

Signal behavior in the most recent log set:
- `entry_conditions_not_met`: 1,428 holds
- `cooldown_active`: 565 holds
- `position_open_waiting`: 184 holds
- `below_ma_filter`: 176 holds

Key observations from the log:
- The log shows repeated session restarts on 2026-03-26 rather than one long stable daemon stretch.
- Every recorded filled order belongs to `kimchi_premium_wallet`; there are **no filled sells** in the visible log.
- `mean_reversion_wallet` repeatedly emitted `buy` signals for XRP, but those signals do not appear with `order=filled` in the log excerpted set. That warrants follow-up because signal generation and execution evidence are not aligned.

## Artifact Reliability Assessment

The `artifacts/` directory contains mixed outputs from multiple daemon configurations and timestamps. This report uses each file only for the scope it can actually support.

| Artifact | Timestamp | Use | Assessment |
|---------|-----------|-----|------------|
| `runtime-checkpoint.json` | 2026-03-26 17:59 KST | Latest portfolio snapshot | Primary for current balances and trade counts |
| `daemon-heartbeat.json` | 2026-03-26 17:59 KST | Latest liveness marker | Primary, but metadata quality is weak because `uptime_seconds=0.0` and `poll_interval_seconds=0` despite `iteration=3` |
| `daemon.log` | through 2026-03-26 16:36 KST | Session history | Primary for observed runtime behavior before the latest snapshot |
| `kill-switch.json` | live snapshot | Risk guardrail status | Safe to use; `triggered=false` |
| `performance-dashboard.md` | 2026-03-26 14:04 KST | Historical reference only | Stale and configuration-misaligned with the latest checkpoint |
| `pnl-report.json` / `pnl-report.md` | 2026-03-26 14:41 / 14:41 KST | Historical reference only | Stale wallet set; should not be treated as current |
| `daily-performance.json` / `positions.json` | 2026-03-26 12:44 KST | Historical reference only | Earlier single-wallet style snapshot, not current truth |
| `paper-trades.jsonl` / archive | repeated `2025-01-02` rows | Excluded from live performance | Fixture-like momentum data, not trustworthy as current daemon evidence |

## Risk Status

`artifacts/kill-switch.json` shows:
- `triggered=false`
- `consecutive_losses=0`
- portfolio drawdown and daily loss effectively near zero

Conclusion:
- No active risk breach is visible.
- The present concern is not drawdown. It is **artifact coherence** and **strategy inactivity**.

## Conclusions

1. The newest snapshot is mildly negative but operationally low risk: **-431.99 KRW realized, no open positions, no kill-switch breach**.
2. The latest portfolio state and the latest daemon log do **not** describe the same configuration. Snapshot artifacts point to a 3-wallet BTC/ETH setup, while the latest full log trail shows broader multi-wallet sessions ending earlier the same day.
3. The current artifact pipeline is not reliable enough for automated executive reporting without a freshness gate.
4. The next reporting improvement should be to stamp every generated artifact with the same session id, config path, wallet set, and snapshot time so `runtime-checkpoint`, `heartbeat`, `pnl-report`, and dashboard outputs stay consistent.
