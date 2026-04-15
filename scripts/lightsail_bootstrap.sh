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
    TMP_CLONE="$(mktemp -d /tmp/ct-bootstrap.XXXXXX)"
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$TMP_CLONE/repo"
    shopt -s dotglob
    mv "$TMP_CLONE/repo"/* "$APP_DIR"/
    shopt -u dotglob
    rm -rf "$TMP_CLONE"
    chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
    STEPS_DONE+=("git clone $REPO_URL → $APP_DIR")
else
    log "  existing checkout detected — pulling"
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --depth 1 origin "$REPO_BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard "origin/$REPO_BRANCH"
    STEPS_DONE+=("git reset --hard origin/$REPO_BRANCH $APP_DIR")
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
