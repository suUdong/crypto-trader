#!/usr/bin/env bash
# crypto-trader Lightsail bootstrap (Ubuntu 22.04, native systemd, no Docker)
# Idempotent — safe to re-run. Run as root: `sudo bash lightsail_bootstrap.sh`
#
# Responsibilities (per docs/superpowers/plans/2026-04-07-lightsail-deployment.md §4):
#   1. Install Python 3.12 (deadsnakes) + system packages
#   2. Create `crypto` system user
#   3. Create /var/lib/crypto-trader, /etc/crypto-trader directory tree
#   4. Clone or fast-forward /opt/crypto-trader from GitHub
#   5. Build Python venv + `pip install -e .`
#   6. Seed /etc/crypto-trader/environment
#   7. Seed /etc/crypto-trader/secrets.env template (HALT if unfilled)
#   8. Install systemd units (daemon + nightly backup) + daemon-reload + enable
#
# Service is NOT auto-started; operator confirms after secrets are filled.

set -euo pipefail

# ---------- config ----------
REPO_URL="${REPO_URL:-https://github.com/suUdong/crypto-trader.git}"
REPO_BRANCH="${REPO_BRANCH:-master}"
APP_USER="crypto"
APP_GROUP="crypto"
APP_DIR="/opt/crypto-trader"
DATA_DIR="/var/lib/crypto-trader"
ETC_DIR="/etc/crypto-trader"
PY="python3.12"

log() { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[bootstrap]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "must run as root (sudo bash $0)"

# ---------- 1. packages ----------
log "apt update + base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    software-properties-common ca-certificates curl gnupg lsb-release

if ! command -v "$PY" >/dev/null 2>&1; then
    log "adding deadsnakes PPA for $PY"
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -y
fi

apt-get install -y --no-install-recommends \
    "$PY" "${PY}-venv" "${PY}-dev" \
    git build-essential pkg-config \
    sqlite3 jq tmux rsync logrotate

# ---------- 2. system user ----------
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    log "creating system user $APP_USER"
    useradd --system --create-home --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin "$APP_USER"
else
    log "user $APP_USER already exists"
fi

# ---------- 3. directories ----------
log "preparing directory tree"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$DATA_DIR"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$DATA_DIR/artifacts"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$DATA_DIR/backups"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$DATA_DIR/logs"
install -d -o root        -g "$APP_GROUP" -m 0750 "$ETC_DIR"

# ---------- 4. source ----------
if [[ ! -d "$APP_DIR/.git" ]]; then
    log "cloning $REPO_URL into $APP_DIR"
    # APP_DIR exists as the user's home; clone into a temp and move .git
    TMP_CLONE="$(mktemp -d /tmp/crypto-trader.XXXXXX)"
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$TMP_CLONE/repo"
    shopt -s dotglob
    mv "$TMP_CLONE/repo"/* "$APP_DIR"/
    shopt -u dotglob
    rm -rf "$TMP_CLONE"
    chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
else
    log "fast-forwarding existing checkout"
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --prune origin
    sudo -u "$APP_USER" git -C "$APP_DIR" checkout "$REPO_BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH"
fi

# ---------- 5. venv ----------
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    log "creating venv"
    sudo -u "$APP_USER" "$PY" -m venv "$APP_DIR/.venv"
fi
log "pip install -e ."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip setuptools wheel
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade -e "$APP_DIR"

# NOTE: daemon.toml uses relative `artifacts/*` paths. We solve this by
# setting systemd WorkingDirectory=$DATA_DIR (below) so the daemon's CWD
# is the persistent data dir. Avoids touching every path field in config.py
# and keeps the in-repo `artifacts/` (with tracked historical reports)
# untouched.

# ---------- 6. environment file ----------
ENV_FILE="$ETC_DIR/environment"
if [[ ! -f "$ENV_FILE" ]]; then
    log "writing $ENV_FILE"
    cat > "$ENV_FILE" <<'EOF'
TZ=Asia/Seoul
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
CT_ARTIFACTS_ROOT=/var/lib/crypto-trader/artifacts
EOF
    chown root:"$APP_GROUP" "$ENV_FILE"
    chmod 0644 "$ENV_FILE"
fi

# ---------- 7. secrets template ----------
SECRETS_FILE="$ETC_DIR/secrets.env"
SECRETS_FRESH=0
if [[ ! -f "$SECRETS_FILE" ]]; then
    log "seeding $SECRETS_FILE template (must be filled before start)"
    cat > "$SECRETS_FILE" <<'EOF'
# Fill in before starting crypto-trader.service
UPBIT_ACCESS_KEY=
UPBIT_SECRET_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
    SECRETS_FRESH=1
fi
chown root:"$APP_GROUP" "$SECRETS_FILE"
chmod 0640 "$SECRETS_FILE"

# ---------- 8. systemd units ----------
log "installing systemd units"
cat > /etc/systemd/system/crypto-trader.service <<EOF
[Unit]
Description=crypto-trader multi-wallet daemon
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$DATA_DIR
EnvironmentFile=$ETC_DIR/environment
EnvironmentFile=$ETC_DIR/secrets.env
ExecStart=$APP_DIR/.venv/bin/python -m crypto_trader.cli run-multi --config $APP_DIR/config/daemon.toml
Restart=always
RestartSec=15

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA_DIR
MemoryMax=1536M
CPUQuota=150%

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/crypto-trader-backup.service <<EOF
[Unit]
Description=nightly SQLite + JSONL backup
After=crypto-trader.service

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_GROUP
EnvironmentFile=$ETC_DIR/environment
ExecStart=$APP_DIR/scripts/backup.sh
EOF

cat > /etc/systemd/system/crypto-trader-backup.timer <<'EOF'
[Unit]
Description=nightly crypto-trader backup

[Timer]
OnCalendar=*-*-* 19:00:00 UTC
Persistent=true
Unit=crypto-trader-backup.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable crypto-trader.service >/dev/null
systemctl enable crypto-trader-backup.timer >/dev/null

log "bootstrap complete."
echo
if [[ $SECRETS_FRESH -eq 1 ]]; then
    warn "secrets template was just created — fill it in before starting the service:"
    warn "    sudo -e $SECRETS_FILE"
    warn "then:"
    warn "    sudo systemctl start crypto-trader && journalctl -u crypto-trader -f"
    exit 0
fi

cat <<EOF
Next steps:
  sudo -e $SECRETS_FILE                 # confirm secrets are populated
  sudo systemctl start crypto-trader
  sudo systemctl status crypto-trader
  journalctl -u crypto-trader -f
EOF
