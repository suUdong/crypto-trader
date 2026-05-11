# Troubleshooting

Keep the system in paper unless the live runbook explicitly says otherwise.

## Daemon Died

Check whether systemd is managing it:

```bash
systemctl --user status --no-pager crypto-trader.service
journalctl --user -u crypto-trader.service -n 200 --no-pager
```

Check local artifacts:

```bash
cat artifacts/daemon-heartbeat.json | python -m json.tool
cat artifacts/health.json | python -m json.tool
tail -n 200 artifacts/daemon.log
```

Recovery:

```bash
scripts/restart_daemon.sh config/daemon.toml
cat artifacts/daemon-heartbeat.json | python -m json.tool
```

If it dies again immediately, preserve `artifacts/daemon.log`,
`artifacts/health.json`, and `artifacts/runtime-checkpoint.json`; then inspect
the first traceback in the log. Do not delete checkpoint files to make the
daemon start.

## Preflight Failed

Run the operator helper:

```bash
PYTHONPATH=src python3 scripts/preflight_live_check.py --config config/daemon.toml
```

Common failures:

| Failure | Meaning | Action |
|---|---|---|
| `LIVE_TRADING_ENABLED` missing | Live opt-in not explicit | Stay paper, or export only during an approved live rehearsal |
| live confirmation missing/stale | `artifacts/live-confirmed.json` is absent or older than 24h | Refresh only as part of the runbook |
| Telegram missing | Live alert channel not wired | Configure `CT_TELEGRAM_BOT_TOKEN` and `CT_TELEGRAM_CHAT_ID` |
| Upbit credentials missing | Live broker cannot authenticate | Export env vars; never commit keys |
| hard cap exceeded | Config violates live safety constants | Revert config policy drift; do not raise hard caps |
| unknown `go_live_wallets` item | Allowlist references a non-existent wallet | Fix wallet name or stay paper |

Warnings are not blockers, but every `ERROR` row blocks live cutover.

## Accidentally Entered Live Mode

Immediate response:

```bash
systemctl --user stop crypto-trader.service
scripts/toggle_live.sh paper config/daemon.toml
```

Then remove live env from the service environment:

```bash
systemctl --user edit crypto-trader.service
systemctl --user daemon-reload
```

Remove these from the service drop-in if present:

```ini
Environment="LIVE_TRADING_ENABLED=true"
Environment="CT_LIVE_TRADING_ENABLED=true"
```

Preserve audit evidence:

```bash
ls -l artifacts/live-auto-revert.flag artifacts/live-confirmed.json 2>/dev/null
tail -n 300 artifacts/daemon.log
```

Restart only in paper:

```bash
scripts/restart_daemon.sh config/daemon.toml
```

## Symbol Circuit Breaker Disabled A Symbol

Inspect state and events:

```bash
jq '.symbols | to_entries | map(select(.value.disabled_until != ""))' \
  artifacts/symbol-circuit.json
tail -n 50 artifacts/circuit-breaker-events.jsonl
```

Normal response is to wait for the 24h cooldown. To clear manually, stop the
daemon first, edit `artifacts/symbol-circuit.json`, set the symbol's
`disabled_until` to `""`, then restart. Editing while the daemon is running is
unsafe because the daemon rewrites the file every tick.

## Daily Performance Looks Stale

Check daemon heartbeat first:

```bash
cat artifacts/daemon-heartbeat.json | python -m json.tool
stat artifacts/daily-performance.json
```

If heartbeat is fresh but performance is stale, check whether there were no new
ticks or no closed trades. Then refresh supporting views:

```bash
cat artifacts/positions.json | python -m json.tool
tail -n 20 artifacts/paper-trades.jsonl
python scripts/leaderboard.py --config config/daemon.toml
```

## Wallet Change Did Not Apply

Verify the active wallet list is what TOML says:

```bash
python scripts/leaderboard.py --config config/daemon.toml
```

Then restart through the normal path:

```bash
scripts/restart_daemon.sh config/daemon.toml
```

If the wallet remains active, check for another daemon instance:

```bash
ps -ef | rg 'crypto_trader|crypto-trader|daemon.toml'
cat artifacts/daemon-heartbeat.json | python -m json.tool
```

Stop the stray process only after confirming it belongs to this checkout.

## HMM Breakout Fires Unexpectedly

`0d5e4cd` keeps failed HMM breakout default-off. If HMM breakout emits entries,
look for an explicit config or strategy override that enabled it. Default
behavior should be HOLD with the disabled reason.
