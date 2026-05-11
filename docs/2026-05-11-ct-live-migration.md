# CT Paper → Live Migration Plan (2026-05-11)

Operator runbook for promoting `crypto-trader` from `paper_trading = true`
to `paper_trading = false` on Lightsail (`ct-prod-01`).

This document is the canonical checklist. Anything not on it is **out of
scope** for a live cutover. Pause and ask if reality diverges from these
steps — do **not** improvise.

---

## 0. Hard preconditions (none of these are optional)

| Gate | Where enforced | How to verify |
|---|---|---|
| Paper performance proves edge | `scripts/micro_live_check.py` | exit code 0, `artifacts/micro-live-check.json::ready=true` |
| Upbit API key pair exists with **trade-only** permissions, IP-whitelisted to the prod box | Operator | Upbit dashboard |
| Telegram bot wired and reaching the operator | `preflight_check` (live mode) | test alert delivered before cutover |
| Symbol circuit breaker armed and persisted | `runtime.symbol_circuit_path` | file exists, contains state |
| Kill switch hard caps unchanged (`HARD_MAX_DAILY_LOSS_PCT=0.05`, `HARD_MAX_RISK_PER_TRADE_PCT=0.05`, `SAFE_LIVE_MAX_POSITION_PCT=0.10`) | `src/crypto_trader/config.py` | `git diff` shows no edits |
| Bootstrap → backup → teardown rehearsal passed on `ct-prod-01` | `scripts/lightsail_bootstrap.sh` + `scripts/backup.sh` | session handoff log |

Stop here if **any** row is unchecked.

---

## 1. Live-mode safety gates (preflight)

`preflight_check()` in `src/crypto_trader/config.py` enforces these
additional gates whenever `paper_trading = false`. The daemon refuses to
start unless every one passes.

### 1a. Explicit env opt-in

```bash
export LIVE_TRADING_ENABLED=true       # also accepts: 1, yes, on
```

`CT_LIVE_TRADING_ENABLED` is an accepted alias.

### 1b. Operator confirmation marker

```bash
# Refresh once per ≤ 24 hours, or whenever the daemon is restarted.
mkdir -p artifacts
python3 - <<'PY'
import json, datetime as dt, pathlib
pathlib.Path("artifacts/live-confirmed.json").write_text(
    json.dumps({"confirmed_at": dt.datetime.now(dt.UTC).isoformat()})
)
PY
```

A missing file, malformed JSON, future-dated, or stale (> 24 h)
timestamp all hard-fail preflight.

### 1c. Auto-revert daily-loss cap

Set in `[trading]` of `config/daemon.toml` (or via
`CT_LIVE_AUTO_REVERT_LOSS_PCT`). Default: `0.02` (= 2 %).

```toml
[trading]
live_auto_revert_loss_pct = 0.02
```

If realised intraday loss reaches this fraction of session-starting
equity, the kill switch fires with reason
`live_auto_paper_revert: daily_loss=<pct> >= revert_cap=<pct>`,
liquidates all open positions, and writes
`artifacts/live-auto-revert.flag` so the supervisor / operator can
confirm before re-enabling.

### 1d. Credentials must be present **in env**

Never commit keys. Export before launching:

```bash
export CT_UPBIT_ACCESS_KEY='xxxxxxxx'
export CT_UPBIT_SECRET_KEY='xxxxxxxx'
```

Empty values fall back to `PaperBroker` (see `wallet.build_wallets`).

### 1e. `go_live_wallets` allowlist

Stage rollouts via `[trading].go_live_wallets`. An empty list promotes
**every** wallet — make this explicit:

```toml
[trading]
go_live_wallets = ["sol_momentum_wallet"]
```

Wallets not listed continue on `PaperBroker`. Names must match
`[[wallets]].name` exactly (case-sensitive).

---

## 2. Cutover sequence

> Operator executes locally first via SSH to `ct-prod-01`, then on the
> server. Tag each step in the session handoff log as you complete it.

1. **Snapshot.** `scripts/backup.sh` — produces a fresh SQLite + JSONL
   archive. Verify file size and `sha256` recorded in
   `artifacts/backups/latest.json`.
2. **Stop the daemon** (paper):
   ```bash
   sudo systemctl stop crypto-trader
   ```
3. **Verify preflight (dry-run):**
   ```bash
   PYTHONPATH=src python3 -c "from crypto_trader.config import load_config, preflight_check; \
     c = load_config('config/daemon.toml'); \
     print('\n'.join(f'{l}: {m}' for l, m in preflight_check(c)) or 'OK')"
   ```
   Expected output: `OK`. Any `ERROR:` line aborts the cutover.
4. **Export env in the systemd drop-in** (NOT in TOML or git):
   ```bash
   sudo systemctl edit crypto-trader
   ```
   ```ini
   [Service]
   Environment="LIVE_TRADING_ENABLED=true"
   Environment="CT_UPBIT_ACCESS_KEY=..."
   Environment="CT_UPBIT_SECRET_KEY=..."
   ```
5. **Refresh the live-confirmation marker** (step 1b).
6. **Flip the flag** (one of):
   - `scripts/toggle_live.sh live config/daemon.toml`, OR
   - manual edit: `paper_trading = false` in `config/daemon.toml`.
7. **Start the daemon and tail logs:**
   ```bash
   sudo systemctl start crypto-trader
   sudo journalctl -fu crypto-trader
   ```
   First 60 seconds you should see:
   - `Live trading requires …` lines all **absent** (every gate passed)
   - `LiveBroker` instantiated for each enabled wallet
   - `reconcile_with_exchange` reports `ok=true`
8. **Smoke check.** Send one tiny manual buy via the daemon's normal
   pipeline (lowest-capital wallet, smallest signal) and confirm the
   fill via Upbit web UI. Abort if anything is unexpected.
9. **Telegram heartbeat.** Confirm the daily-summary alert lands.

---

## 3. Monitoring (first 72 h)

| Source | What to watch | Threshold to act |
|---|---|---|
| Telegram alerts | Any `KILL SWITCH TRIGGERED` | immediate rollback |
| `artifacts/live-auto-revert.flag` | File exists | immediate rollback |
| `artifacts/runtime-checkpoint.json::wallet_health` | `degraded` count | > 1 → investigate |
| Upbit dashboard | Open positions vs. internal | mismatch → reconcile + rollback if drift > 1 % |
| `scripts/leaderboard.py` | Per-wallet PnL | any wallet WR < 30 % across 10+ trades → disable |

---

## 4. Rollback procedure

Rollback is the **default response** to any unexpected behaviour. There
is no penalty for reverting; the penalty is for hesitating.

```bash
# 1. Stop the daemon
sudo systemctl stop crypto-trader

# 2. Flip back to paper
scripts/toggle_live.sh paper config/daemon.toml
# (or: edit paper_trading = true)

# 3. Remove the env opt-in
sudo systemctl edit crypto-trader   # remove the LIVE_TRADING_ENABLED line

# 4. Move the auto-revert flag aside for audit
mv artifacts/live-auto-revert.flag \
   artifacts/live-auto-revert-$(date +%Y%m%dT%H%M%SZ).flag

# 5. Reconcile balances vs. exchange
PYTHONPATH=src python3 - <<'PY'
from crypto_trader.config import load_config
from crypto_trader.execution.live import LiveBroker
c = load_config('config/daemon.toml')
b = LiveBroker(c.credentials.upbit_access_key, c.credentials.upbit_secret_key, 0)
print(b.reconcile_with_exchange())
PY

# 6. Restart in paper
sudo systemctl start crypto-trader
sudo journalctl -fu crypto-trader
```

Then update `SESSION_HANDOFF.md` with what tripped, the flag file
contents, and the reconcile report.

---

## 5. Abort criteria (no judgment needed — just rollback)

- `artifacts/live-auto-revert.flag` created (-2 % cap fired).
- Any `KILL SWITCH TRIGGERED` in journalctl.
- `reconcile_with_exchange` reports `ok=false` or `PHANTOM/DRIFT`.
- Two consecutive wallets disabled by `auto_pause` in the same UTC day.
- Total realised PnL across all live wallets ≤ -1 % in any rolling 4 h
  window during the first 72 h.

---

## 6. Re-enabling after auto-revert

1. Inspect `artifacts/live-auto-revert-*.flag` and `journalctl` for the
   trigger reason. Document in `SESSION_HANDOFF.md`.
2. Run `scripts/micro_live_check.py` again — the kill must clear before
   any retry.
3. Manually `touch` the kill-switch reset file:
   `touch ${runtime.kill_switch_path%.json}.reset`
4. Repeat the full cutover sequence from § 2.

---

## 7. Out-of-scope

- Touching `HARD_*` constants in `config.py`. Hard caps are policy, not
  parameters.
- Bumping `live_auto_revert_loss_pct` above `0.02` mid-run "because the
  market is volatile today." Stop and rebuild the case in paper first.
- Skipping the confirmation marker by editing `live_confirmation_max_age_hours`
  to a year. If the marker is stale, refresh it; don't redefine "stale."
- Running live without Telegram. The preflight blocks it; do not work
  around the block.
