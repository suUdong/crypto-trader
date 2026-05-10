# Symbol-Level Circuit Breaker — Operations Manual

**Status**: shipped 2026-05-11 (commits `116751d`, `68bc0c2`)
**Audit reference**: `docs/2026-05-11-ct-audit-followup.md` item 4
**Source**: `src/crypto_trader/risk/symbol_circuit_breaker.py`

## What it does

Auto-disables a symbol after a loss burst, then re-enables it after a
cooling-off window. Decisions are scoped per `KRW-<asset>` and apply to
every wallet that trades that symbol (the breaker is process-wide, not
per-wallet).

The gate is checked inside `StrategyWallet.run_once` immediately before
the regime/macro gates. A blocked BUY is downgraded to HOLD with reason
`symbol_circuit_breaker: <detail>` and no order is placed.

## Trigger logic

Two independent triggers. Either fires:

| Trigger | Default | Meaning |
|---|---|---|
| `loss_burst` | ≥ 3 losses in 48h | Counts only strictly-negative `pnl_pct` closes inside the rolling window. Wins don't count, zero pnl trades don't count. |
| `expectancy` | mean `pnl_pct` < -0.5% across ≥ 5 trades in 48h | Mean of *all* closes (wins + losses) inside the window once the trade count meets the minimum. |

Once tripped, the symbol enters a 24h cooldown. Cooldown is checked
lazily on every `is_disabled` call — the next decision tick that
crosses the unlock timestamp re-enables the symbol; no scheduler or
background timer is needed.

After re-enable the trade window is cleared, so a single fresh loss
right after recovery does not instantly re-disable.

## State persistence

JSON at `artifacts/symbol-circuit.json` (path is overridable via
`runtime.symbol_circuit_path` / `CT_SYMBOL_CIRCUIT_PATH`). Schema:

```json
{
  "config": {
    "loss_threshold": 3,
    "window_hours": 48.0,
    "cooldown_hours": 24.0,
    "expectancy_threshold_pct": -0.005,
    "min_trades_for_expectancy": 5
  },
  "symbols": {
    "KRW-XRP": {
      "trades": [
        ["2026-05-11T03:00:00+00:00", -0.012],
        ["2026-05-11T05:30:00+00:00", -0.018],
        ["2026-05-11T07:45:00+00:00", -0.024]
      ],
      "disabled_until": "2026-05-12T07:45:00+00:00",
      "last_reason": "loss_burst: 3 losses in last 48h"
    }
  }
}
```

The file is rewritten atomically alongside every kill-switch save (once
per daemon tick). Cooldown clocks continue across daemon restarts —
disable timestamps are absolute UTC, not relative.

JSON was chosen over SQLite to match the existing `kill-switch.json` /
`runtime-checkpoint.json` pattern: state is small (≤ a few KB), append-
mostly, and easier to inspect or hand-edit during an incident.

## Inspect current state

```bash
jq '.symbols | to_entries | map(select(.value.disabled_until != "")) |
    map({symbol: .key, until: .value.disabled_until,
         reason: .value.last_reason})' \
   artifacts/symbol-circuit.json
```

## Manually clear a symbol (operator override)

Stop the daemon, edit `artifacts/symbol-circuit.json` to clear the
symbol's `disabled_until` field (set to `""`), then restart. Editing a
running daemon's state file is unsafe — the daemon overwrites the file
on the next tick.

To reset everything:

```bash
systemctl stop crypto-trader  # or kill the daemon PID
mv artifacts/symbol-circuit.json artifacts/symbol-circuit.json.bak
systemctl start crypto-trader
```

The file is recreated empty on first save.

## Observability

### Telegram alert (live + paper)

Every disable transition fires through `TradeAlertManager.alert_rejection`,
delivered to whichever notifiers are configured (Telegram, Slack). Format:

```
⚠️ REJECTED | circuit_breaker
BUY KRW-XRP — symbol disabled — loss_burst: 3 losses in last 48h
```

The 5-minute rejection cooldown applies; repeated retriggers for the
same symbol while still disabled are suppressed.

### fire-monitor P0 event line

Every state transition appends one JSONL line to
`artifacts/circuit-breaker-events.jsonl` (overridable via
`runtime.symbol_circuit_events_path`). Schema:

```json
{
  "category": "circuit_breaker",
  "system": "crypto-trader",
  "severity": "P0",
  "symbol": "KRW-XRP",
  "transition": "disabled",
  "reason": "loss_burst: 3 losses in last 48h",
  "detected_at": "2026-05-11T07:45:00+00:00"
}
```

`severity` is `"P0"` for `disabled` transitions and `"INFO"` for
`re_enabled` transitions. The file is plain JSONL — fire-monitor's
crypto collector reads any artifact under `crypto_artifacts_dir`, so
this surface is already inside its monitored area.

To tail live events:

```bash
tail -F artifacts/circuit-breaker-events.jsonl
```

## Tuning

All thresholds live on `SymbolCircuitConfig` (constructed with defaults
in `MultiSymbolRuntime.__init__`). If forward data argues for different
numbers, the path is to expose a `[symbol_circuit_breaker]` section in
`config/daemon.toml` and thread it through `RuntimeConfig`. Defaults
were picked from the audit recommendation (3 losses / 48h, 24h
cooldown) — *do not tune blind on backtest data* per the project's
over-optimization rule.

## How it interacts with other gates

The breaker check runs **before**:

1. `active_regimes` gate (regime mismatch downgrades BUY)
2. Macro adapter `should_block_entry`
3. BTC 30-bar momentum gate
4. UTC entry-time blackout
5. RiskManager `can_open` / cooldown / auto-pause
6. Position-sizing + execution-cost gate

So if multiple gates would each veto a trade, the breaker reason wins
in the log line. This is intentional: a symbol-disabled state is more
useful operationally than knowing macro happened to also veto.

## Smoke test after deploy

After a daemon restart:

```bash
# 1. State file exists or is created on first save
ls -l artifacts/symbol-circuit.json

# 2. No symbols disabled at startup (unless persisted from previous run)
jq '.symbols | to_entries | map(select(.value.disabled_until != "")) | length' \
   artifacts/symbol-circuit.json

# 3. New trades flow through and get recorded — should grow as paper trades close
jq '.symbols | to_entries | map({symbol: .key, trades: (.value.trades | length)})' \
   artifacts/symbol-circuit.json

# 4. Event log exists and is empty (or has prior events from earlier run)
ls -l artifacts/circuit-breaker-events.jsonl 2>/dev/null || echo "no events yet"
```

## Failure modes considered

| Failure | Mitigation |
|---|---|
| Daemon crashes between two losses | Trades are recorded synchronously and `save()` runs every tick; on restart `load()` re-hydrates the window. |
| Clock skew across restart | Disable timestamps are absolute UTC ISO strings — no relative arithmetic. |
| Naïve datetime from older code path | `record_trade` normalizes via `_ensure_utc`. |
| State file becomes corrupt | `load()` catches `OSError`/`JSONDecodeError`, logs a warning, and starts with an empty in-memory state. Worst case: one cooldown is lost. |
| Telegram down | Alert callback exceptions are caught inside the breaker — they cannot abort `record_trade` and therefore cannot affect the trading loop. |
| Wallet without breaker injected | `circuit_breaker is None` short-circuits every check — the wallet is uninstrumented but otherwise identical (back-compat for ad-hoc CLI commands). |
