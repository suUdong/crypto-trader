# Lightsail Deploy Setup

## GitHub Secrets (required)

Go to repo Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `LIGHTSAIL_SSH_KEY` | Contents of `~/.ssh/lightsail_crypto_trader.pem` |
| `LIGHTSAIL_HOST` | `52.78.228.194` |
| `LIGHTSAIL_USER` | `crypto` |

## Server prerequisites

1. `crypto` user exists with sudo access for `systemctl restart crypto-trader`
2. `crypto-trader.service` systemd unit installed
3. Python 3.12 venv active for `crypto` user
4. rsync installed (`sudo apt install rsync`)

## Activating deployment

Remove `if: false` from `.github/workflows/deploy.yml` deploy job when ready.
