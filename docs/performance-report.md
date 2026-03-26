# Daemon Performance Report

**Generated**: 2026-03-26 15:35 KST (2026-03-26 06:35 UTC)
**Scope**: Current paper-trading daemon state from `artifacts/`
**Authoritative sources**: `artifacts/runtime-checkpoint.json`, `artifacts/daemon-heartbeat.json`, `artifacts/kill-switch.json`, `artifacts/daemon.log`

## Executive Summary

As of 2026-03-26 15:35 KST, the active daemon is running under PID `2892270` and reached iteration `43` with a 60-second polling cadence. Current portfolio equity is **5,998,790 KRW**, or **-1,210 KRW (-0.020%)** versus the 6,000,000 KRW paper baseline.

The only strategy carrying live exposure is **kimchi_premium**, which holds one open position and accounts for the entire unrealized loss. **momentum** and **vpin** are flat with no open positions and no realized PnL. No kill switch condition is active.

## Artifact Assessment

The artifact directory contains mixed snapshots from different daemon sessions. The report below uses the newest live checkpoint and treats older reports as stale reference material rather than current truth.

| Artifact | Timestamp | Use in this report | Notes |
|---------|-----------|--------------------|-------|
| `runtime-checkpoint.json` | 2026-03-26 06:35 UTC | Primary | Latest per-wallet equity, cash, open positions, and trade counts |
| `daemon-heartbeat.json` | 2026-03-26 06:35 UTC | Primary | Confirms daemon liveness, PID, iteration, and uptime |
| `kill-switch.json` | live snapshot | Primary | Confirms drawdown guardrails are not triggered |
| `daemon.log` | rolling through 2026-03-26 15:33 KST+ | Secondary | Confirms one filled kimchi buy and ongoing hold/cooldown behavior |
| `paper-trades.jsonl` | repeated `2025-01-02` entries | Excluded from current PnL | Contains stale fixture-like momentum trades that do not match the current wallet set |
| `pnl-report.json` | 2026-03-26 05:41 UTC | Stale | Only reflects 3 wallets and understates current portfolio size |
| `daily-performance.json` | 2026-03-26 03:44 UTC | Stale | Earlier snapshot with 1,000,000 KRW equity only |
| `positions.json` | 2026-03-26 03:44 UTC | Stale | Does not reflect the current kimchi position |
| `drift-report.json` / `regime-report.json` / `promotion-gate.json` | 2026-03-24 21:49 UTC | Historical context only | Older single-session operator artifacts |

## Portfolio PnL

| Metric | Value |
|-------|-------|
| Initial capital | 6,000,000 KRW |
| Current equity | 5,998,790 KRW |
| Mark-to-market PnL | **-1,210 KRW** |
| Portfolio return | **-0.020%** |
| Realized PnL | 0 KRW |
| Open positions | 1 |
| Closed trades | 0 |

## Strategy PnL Summary

| Strategy | Wallets | Initial Capital | Equity | PnL | Return | Realized PnL | Open Positions | Closed Trades | Status |
|----------|---------|-----------------|--------|-----|--------|--------------|----------------|---------------|------|
| momentum | 2 | 2,000,000 KRW | 2,000,000 KRW | 0 KRW | 0.000% | 0 KRW | 0 | 0 | Flat |
| vpin | 3 | 3,000,000 KRW | 3,000,000 KRW | 0 KRW | 0.000% | 0 KRW | 0 | 0 | Flat |
| kimchi_premium | 1 | 1,000,000 KRW | 998,790 KRW | **-1,210 KRW** | **-0.121%** | 0 KRW | 1 | 0 | Only active exposure |
| **Portfolio** | **6** | **6,000,000 KRW** | **5,998,790 KRW** | **-1,210 KRW** | **-0.020%** | **0 KRW** | **1** | **0** | |

## Daemon Behavior

- `daemon-heartbeat.json` shows the daemon alive at 2026-03-26 06:35 UTC with `iteration=43` and `uptime_seconds=2606.2`.
- `daemon.log` records a filled kimchi premium BTC buy at **2026-03-26 13:12:13 KST** with fill price **106,012,980 KRW**, which matches the single open position visible in the latest checkpoint.
- Since that fill, the log shows repeated `position_open_waiting` on `KRW-BTC` and `cooldown_active` on the remaining kimchi symbols, indicating the strategy is in hold/cooldown management rather than adding new exposure.
- No closed trades are visible in the latest checkpoint, so all PnL is currently unrealized mark-to-market.

## Risk And Operations

| Metric | Value | Limit | Status |
|-------|-------|-------|--------|
| Portfolio drawdown | 0.0178% | 5.0% | OK |
| Daily loss | 0.0143% | 3.0% | OK |
| Consecutive losses | 0 | 15 | OK |
| Kill switch | `false` | must remain `false` | OK |

The active loss is immaterial from a portfolio-risk perspective. The practical issue is not drawdown but inactivity: five of six wallets are idle and one wallet carries all current risk.

## Conclusions

1. The daemon is operational and healthy, but current performance is effectively flat with a small unrealized loss.
2. Current strategy-level PnL is concentrated entirely in `kimchi_premium`; `momentum` and `vpin` have not contributed any PnL in the latest live snapshot.
3. Older generated reports in `artifacts/` should not be treated as current because they are materially stale and represent different wallet sets or earlier sessions.
4. For the next report cycle, `runtime-checkpoint.json` should remain the source of truth unless the snapshot/export pipeline is updated to regenerate `pnl-report.json` and `positions.json` on every daemon tick.
