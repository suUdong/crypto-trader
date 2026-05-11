# Operations Guide

This is the day-to-day manual for the W11 paper daemon. Policy is
**paper-first**. Live mode requires the separate migration runbook and must not
be entered casually.

## 1. Daemon Start And Stop

### Start paper daemon

```bash
scripts/restart_daemon.sh config/daemon.toml
```

Expected evidence:

```bash
cat artifacts/daemon-heartbeat.json
cat artifacts/health.json
tail -n 100 artifacts/daemon.log
```

`restart_daemon.sh` uses systemd user units when available for
`config/daemon.toml`; otherwise it falls back to direct daemon launch. It checks
the runtime checkpoint, waits for heartbeat freshness, and restores wallet
positions from checkpoint.

### Systemd path

```bash
deploy/systemd/install-user-units.sh
systemctl --user restart crypto-trader.service
systemctl --user status --no-pager crypto-trader.service
journalctl --user -u crypto-trader.service -f
```

`crypto-trader-watchdog.timer` rechecks heartbeat freshness and stray PIDs. The
daemon itself also has `auto_restart_enabled = true`.

### Stop daemon

```bash
systemctl --user stop crypto-trader.service
```

If systemd is not installed for this checkout, stop the direct process shown in
`artifacts/daemon-heartbeat.json` and confirm it no longer updates.

```bash
cat artifacts/daemon-heartbeat.json
ps -fp "$(jq -r '.pid // empty' artifacts/daemon-heartbeat.json)"
```

Do not delete checkpoint or trade artifacts during a normal stop.

## 2. Wallet Enable/Disable Workflow

All wallet changes are made in `config/daemon.toml`, then applied with a daemon
restart. Do not modify live policy while doing paper wallet triage.

### Disable a wallet

1. Comment out the full `[[wallets]]` block.
2. Add a dated reason above the commented block: sample size, WR, expectancy,
   total drag, and recovery condition.
3. Update or append the operator note in `docs/wallet_changes.md` when the
   change is part of a tuning decision.
4. Restart paper:

```bash
scripts/restart_daemon.sh config/daemon.toml
python scripts/leaderboard.py --config config/daemon.toml
```

### Enable a wallet

1. Require forward evidence or a documented admission result.
2. Keep `paper_trading = true` globally.
3. Use small capital for admission wallets, normally 500K KRW with explicit
   `max_position_pct`.
4. Restart paper and watch the first ticks:

```bash
scripts/restart_daemon.sh config/daemon.toml
tail -f artifacts/daemon.log
```

### Current W11 posture

- Active: 17 wallets.
- New admission: `ct_sol_vol_target_momentum_wallet`,
  `ct_sol_momentum_wallet`, `ct_sol_breakout_wallet`,
  `ct_eth_breakout_wallet`.
- W11 disabled: `vpin_ondo_wallet`, `vpin_sol_wallet`,
  `vpin_pundix_wallet`.
- Previously disabled and still sidelined: `vpin_mana_wallet`,
  `vpin_bat_wallet`, `vpin_orbs_wallet`, `stealth_3gate_wallet_1`,
  `vpin_eth_wallet`, `vpin_doge_wallet`, `accumulation_tree_wallet`.

## 3. Performance Monitoring

Primary performance artifact:

```bash
cat artifacts/daily-performance.json | python -m json.tool
```

Use it for the current paper portfolio snapshot: PnL, return, drawdown, win
rate, trade count, and wallet summaries. Compare it with the W11 baseline in
[2026-05-11-w11-summary.md](2026-05-11-w11-summary.md) after at least another
24-48h of closed trades.

Supporting views:

```bash
python scripts/leaderboard.py --config config/daemon.toml
cat artifacts/positions.json | python -m json.tool
tail -n 50 artifacts/paper-trades.jsonl
cat artifacts/regime-report.json | python -m json.tool
cat artifacts/drift-report.json | python -m json.tool
```

Key W11 checks:

- No new entries during UTC 23:00-02:59 after the global blackout.
- Symbol circuit state exists and cooldowns persist:

```bash
jq '.symbols' artifacts/symbol-circuit.json
tail -F artifacts/circuit-breaker-events.jsonl
```

- Winners remain sized higher (`vwm_btc_wallet`, `pdh_pdl_btc_wallet` at
  `risk_per_trade_pct=0.015`) and sentinels remain halved
  (`vpin_xrp_wallet`, `vpin_avax_wallet`, `volspike_btc_wallet` at `0.005`).

## 4. Alert Response

Alerts may arrive through Telegram/Slack and through fire-monitor collection of
artifact events.

### Circuit breaker alert

Evidence:

```bash
tail -n 20 artifacts/circuit-breaker-events.jsonl
jq '.symbols | to_entries | map(select(.value.disabled_until != ""))' \
  artifacts/symbol-circuit.json
```

Response:

1. Leave the symbol disabled unless the event is clearly corrupt.
2. Check which wallets trade the symbol in `config/daemon.toml`.
3. Review the closed trades that triggered the loss burst.
4. Let the 24h cooldown expire, or stop the daemon and manually clear the
   symbol only with an audit note.

### Kill switch or live auto-revert alert

Paper:

```bash
cat artifacts/health.json | python -m json.tool
tail -n 200 artifacts/daemon.log
```

Live or accidental live:

1. Stop the daemon.
2. Run `scripts/toggle_live.sh paper config/daemon.toml` if the config was
   flipped.
3. Remove `LIVE_TRADING_ENABLED` from the service environment.
4. Preserve `artifacts/live-auto-revert.flag` for audit.
5. Follow [2026-05-11-ct-live-migration.md](2026-05-11-ct-live-migration.md)
   rollback steps.

### Daemon health alert

```bash
systemctl --user status --no-pager crypto-trader.service
journalctl --user -u crypto-trader.service -n 200 --no-pager
cat artifacts/health.json | python -m json.tool
cat artifacts/daemon-heartbeat.json | python -m json.tool
```

If the heartbeat is stale, restart paper through `scripts/restart_daemon.sh`.

## 5. Live Mode Boundary

Live mode is not a routine operation. Before any live rehearsal:

```bash
export LIVE_TRADING_ENABLED=true
export CT_LIVE_DRY_RUN=true
PYTHONPATH=src python3 scripts/preflight_live_check.py --config config/daemon.toml
```

For capital at risk, use only
[2026-05-11-ct-live-migration.md](2026-05-11-ct-live-migration.md). Keep
`go_live_wallets` explicit; an empty list promotes every wallet when
`paper_trading = false`.
