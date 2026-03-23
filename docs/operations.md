# Operations

## Runtime Modes

- `backtest`: fetches recent candles and prints backtest performance
- `run-once`: executes one market-data -> signal -> paper-order cycle
- `run-loop`: runs the same cycle repeatedly using `runtime.poll_interval_seconds`

## Configuration Layers

1. TOML file, default `config/example.toml`
2. Environment variables prefixed with `CT_`

Important variables:

- `CT_PAPER_TRADING`
- `CT_UPBIT_ACCESS_KEY`
- `CT_UPBIT_SECRET_KEY`
- `CT_TELEGRAM_BOT_TOKEN`
- `CT_TELEGRAM_CHAT_ID`
- `CT_HEALTHCHECK_PATH`
- `CT_POLL_INTERVAL_SECONDS`

## Health Snapshot

Each runtime iteration writes a JSON snapshot to `artifacts/health.json` by default. The snapshot includes:

- last update timestamp
- success flag
- last error
- consecutive failure count
- cash balance
- open position count
- last signal and order status

## Deployment Notes

- Docker image installs the optional `live` extra so `pyupbit` is available in containers
- `docker-compose.yml` mounts `artifacts/` for health snapshots and logs
- GitHub Actions runs lint, typecheck, and unit tests on every push and pull request
