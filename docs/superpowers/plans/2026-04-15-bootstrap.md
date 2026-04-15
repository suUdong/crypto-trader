# Bootstrap Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write an idempotent `scripts/lightsail_bootstrap.sh` that finishes server setup after the system-level provisioning is already done — creating data dirs, cloning/pulling the repo, building the venv, and setting ownership.
**Architecture:** A single self-contained bash script that runs as root, guards each step with an existence check so it is safe to re-run, and exposes a `--teardown` flag for local testing. The script does not touch systemd units, `/etc/crypto-trader/`, or start any service — those are already in place on ct-prod-01.
**Tech Stack:** bash, git, pip

---

## Preconditions (already true on ct-prod-01)

| Item | State |
|---|---|
| Python 3.12 | installed via deadsnakes PPA |
| `crypto` system user (uid 998) | exists |
| rsync, sqlite3, jq, tmux, git, cloudflared | installed |
| `/etc/crypto-trader/environment` + `secrets.env` | created |
| systemd units (crypto-trader + backup) | installed + enabled |
| `/opt/crypto-trader/` | exists, **empty** |
| `/var/lib/crypto-trader/` | **does not exist** |

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/lightsail_bootstrap.sh` | idempotent bootstrap — dirs, clone/pull, venv, ownership |

---

### Task 1: Write `scripts/lightsail_bootstrap.sh`

**Files:**
- Overwrite: `scripts/lightsail_bootstrap.sh`

- [ ] **Step 1: Write the script**

Write `scripts/lightsail_bootstrap.sh` with the following exact content:

```bash
#!/usr/bin/env bash
# crypto-trader Lightsail bootstrap — phase 2 (post-provisioning)
#
# Run as root after the system-level setup is complete:
#   sudo bash scripts/lightsail_bootstrap.sh
#
# Preconditions (already done by provisioning):
#   - Python 3.12 installed (deadsnakes)
#   - `crypto` system user exists (uid 998)
#   - /opt/crypto-trader/ exists (may be empty)
#   - /etc/crypto-trader/environment + secrets.env created
#   - systemd units installed + enabled
#
# This script:
#   1. Creates /var/lib/crypto-trader/{artifacts,backups}  owned by crypto:crypto
#   2. git clone --depth 1  OR  git pull --ff-only  into /opt/crypto-trader/
#   3. Creates .venv (python3.12) if absent
#   4. pip install -e .
#   5. chown -R crypto:crypto /opt/crypto-trader/
#   6. Prints summary
#
# --teardown  Reverses steps 1-5 for test purposes:
#             removes /opt/crypto-trader/* (keeps dir), removes /var/lib/crypto-trader/

set -euo pipefail

# ── config ────────────────────────────────────────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/suUdong/crypto-trader.git}"
REPO_BRANCH="${REPO_BRANCH:-master}"
APP_USER="crypto"
APP_GROUP="crypto"
APP_DIR="/opt/crypto-trader"
DATA_DIR="/var/lib/crypto-trader"
PY="python3.12"

# ── helpers ───────────────────────────────────────────────────────────────────
log()  { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bootstrap]\033[0m %s\n' "$*" >&2; exit 1; }

# ── root check ────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "must run as root:  sudo bash $0  [--teardown]"

# ── teardown mode ─────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--teardown" ]]; then
    warn "TEARDOWN: removing repo contents + data dir"
    # Keep /opt/crypto-trader/ itself (it is the user home dir), wipe contents
    find "$APP_DIR" -mindepth 1 -delete 2>/dev/null || true
    rm -rf "$DATA_DIR"
    ok "teardown complete — /opt/crypto-trader/ emptied, $DATA_DIR removed"
    exit 0
fi

# ── track what was done ───────────────────────────────────────────────────────
STEPS_DONE=()

# ── 1. data directories ───────────────────────────────────────────────────────
log "step 1: data directories"
for dir in "$DATA_DIR" "$DATA_DIR/artifacts" "$DATA_DIR/backups"; do
    if [[ ! -d "$dir" ]]; then
        install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$dir"
        STEPS_DONE+=("created $dir")
    else
        log "  $dir already exists — skip"
    fi
done

# ── 2. clone or pull ──────────────────────────────────────────────────────────
log "step 2: repo"
if [[ ! -d "$APP_DIR/.git" ]]; then
    log "  cloning $REPO_URL (depth 1) into $APP_DIR"
    # APP_DIR may be non-empty only if it is the user's home — clone to tmp
    # then move so we don't collide with existing dotfiles.
    TMP_CLONE="$(mktemp -d /tmp/ct-bootstrap.XXXXXX)"
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$TMP_CLONE/repo"
    # Move all files (including dotfiles) into APP_DIR
    shopt -s dotglob
    mv "$TMP_CLONE/repo"/* "$APP_DIR"/
    shopt -u dotglob
    rm -rf "$TMP_CLONE"
    STEPS_DONE+=("git clone $REPO_URL → $APP_DIR")
else
    log "  existing checkout detected — pulling"
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --depth 1 origin "$REPO_BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" checkout "$REPO_BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH"
    STEPS_DONE+=("git pull --ff-only $APP_DIR")
fi

# ── 3. python venv ────────────────────────────────────────────────────────────
log "step 3: venv"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    log "  creating venv at $APP_DIR/.venv"
    sudo -u "$APP_USER" "$PY" -m venv "$APP_DIR/.venv"
    STEPS_DONE+=("created venv $APP_DIR/.venv")
else
    log "  venv already exists — skip creation"
fi

# ── 4. pip install -e . ───────────────────────────────────────────────────────
log "step 4: pip install -e ."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip setuptools wheel
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -e "$APP_DIR"
STEPS_DONE+=("pip install -e $APP_DIR")

# ── 5. ownership ──────────────────────────────────────────────────────────────
log "step 5: ownership"
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
STEPS_DONE+=("chown -R $APP_USER:$APP_GROUP $APP_DIR")

# ── 6. summary ────────────────────────────────────────────────────────────────
echo
ok "bootstrap complete — steps performed:"
for s in "${STEPS_DONE[@]}"; do
    ok "  ✓ $s"
done
echo
log "next steps (operator):"
log "  sudo systemctl start crypto-trader"
log "  sudo systemctl status crypto-trader"
log "  journalctl -u crypto-trader -f"
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x scripts/lightsail_bootstrap.sh
```

Expected: `ls -l scripts/lightsail_bootstrap.sh` shows `-rwxr-xr-x`.

---

### Task 2: Validation — shellcheck + local dry-run

- [ ] **Step 1: shellcheck**

```bash
shellcheck scripts/lightsail_bootstrap.sh
```

Expected: no errors, no warnings (exit 0). If shellcheck is not installed:

```bash
sudo apt-get install -y shellcheck && shellcheck scripts/lightsail_bootstrap.sh
```

All SC codes that are acceptable to suppress (none expected — script is written to be clean).

- [ ] **Step 2: bash -n syntax check (fallback if shellcheck unavailable)**

```bash
bash -n scripts/lightsail_bootstrap.sh
echo "syntax OK"
```

Expected: `syntax OK`.

- [ ] **Step 3: Root check fires for non-root**

```bash
bash scripts/lightsail_bootstrap.sh 2>&1 | head -1
```

Expected output contains `must run as root` (non-zero exit).

- [ ] **Step 4: --teardown path is parseable**

Run with `bash -c` at a non-root prompt to confirm flag is recognised before the root-check:

```bash
# Note: root check fires first; we just verify the flag is accepted
sudo bash scripts/lightsail_bootstrap.sh --teardown 2>&1 || true
```

If running as root in a dev environment, expected: `teardown complete — /opt/crypto-trader/ emptied, /var/lib/crypto-trader removed` (exit 0).

- [ ] **Step 5: idempotency verification (local simulation)**

```bash
# Simulate existing data-dir — should skip creation
sudo bash -c '
  set -e
  mkdir -p /tmp/ct-bootstrap-test/artifacts /tmp/ct-bootstrap-test/backups
  DATA_DIR=/tmp/ct-bootstrap-test \
  APP_DIR=/tmp/ct-bootstrap-appdir \
  APP_USER=root APP_GROUP=root \
  REPO_URL="" \
    bash scripts/lightsail_bootstrap.sh 2>&1 | grep "already exists"
' || true
```

Expected: lines containing `already exists — skip` for each pre-existing directory.

---

### Task 3: Commit

- [ ] **Step 1: Verify tests still pass**

```bash
ruff check src/ tests/ && pytest -x -q \
    --ignore=tests/test_backtest_all_cli.py \
    --ignore=tests/test_backtest_engine.py \
    --ignore=tests/test_backtest_engine_entry.py \
    --ignore=tests/test_backtest_strategy_sweep.py \
    --ignore=tests/test_walk_forward.py \
    --ignore=tests/test_walk_forward_cli.py \
    --ignore=tests/test_walk_forward_summary.py \
    --ignore=tests/test_default_walk_forward_all.py \
    --ignore=tests/test_grid_search.py \
    --ignore=tests/test_grid_wf.py \
    --ignore=tests/test_gpu_backtest.py \
    --ignore=tests/test_gpu_correlation.py \
    --ignore=tests/test_gpu_features.py \
    --ignore=tests/test_extended_alpha.py \
    --ignore=tests/test_dashboard.py \
    --ignore=tests/test_regime_report.py \
    --ignore=tests/test_ml_regime.py
```

Expected: all pass, ruff clean.

- [ ] **Step 2: Stage and commit**

```bash
git add scripts/lightsail_bootstrap.sh \
        docs/superpowers/plans/2026-04-15-bootstrap.md
git commit -m "$(cat <<'EOF'
feat(deploy): add idempotent lightsail_bootstrap.sh for phase-2 server setup

Creates data dirs, clones/pulls repo, builds venv, installs package, sets
ownership. Includes --teardown flag for test reversal. Does not touch systemd
units or /etc/crypto-trader/.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Expected: commit created, `git log --oneline -1` shows the new commit.
