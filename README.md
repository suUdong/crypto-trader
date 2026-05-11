# Crypto Trader

Upbit KRW 마켓용 다중 전략 자동매매 시스템입니다. 현재 운영 원칙은
**paper-first**입니다. `config/daemon.toml`의 기본값은
`paper_trading = true`이며, live 전환은 명시적 env opt-in, 최신 확인
마커, preflight, wallet allowlist를 모두 통과해야 합니다.

## Current Operating State

| 항목 | 현재값 |
|---|---|
| 기본 모드 | Paper trading (`paper_trading = true`) |
| 데몬 | `config/daemon.toml`, `daemon_mode = true`, `auto_restart_enabled = true` |
| 인터벌 | `minute60` |
| 활성 wallet 수 | 17 |
| 신규 admission wallet | 4개 SOL/ETH paper-only 후보 |
| 전역 entry blackout | UTC `[23, 0, 1, 2]` + pipeline KST night gate |
| macro sizing | `5b2476b` 이후 macro risk score/level/layer가 runtime context로 전달 |
| symbol circuit breaker | `116751d` + `68bc0c2`, 3 losses/48h 또는 negative expectancy로 symbol cooldown |
| live scaffold | `b24004b`~`d0f06af`, default paper 유지 + live preflight helper |
| HMM breakout | `0d5e4cd` 이후 default-off |

## Active Wallets

HEAD의 `config/daemon.toml` 기준 활성 wallet입니다. `paper_trading`이 wallet
별로 명시되지 않은 항목도 전역 `paper_trading = true` 때문에 paper로
실행됩니다.

| Wallet | Strategy | Symbols | Capital | Risk note |
|---|---|---|---:|---|
| `accumulation_dood_wallet` | `accumulation_breakout` | `KRW-NEW` | 1,000,000 | `risk_per_trade_pct=0.02` |
| `momentum_sol_wallet` | `momentum` | `KRW-RED` | 1,000,000 | `0.015`, `max_position_pct=0.10` |
| `volspike_btc_wallet` | `volume_spike` | `KRW-BTC` | 1,000,000 | Sentinel downsized to `0.005` |
| `vpin_xrp_wallet` | `vpin` | `KRW-XRP` | 1,000,000 | Paper, sentinel `0.005`, max position `0.05` |
| `vpin_avax_wallet` | `vpin` | `KRW-AVAX` | 1,000,000 | Paper, sentinel `0.005`, max position `0.05` |
| `bb_squeeze_eth_wallet` | `bb_squeeze_independent` | `KRW-ETH` | 1,000,000 | Surviving squeeze wallet |
| `bb_squeeze_doge_wallet` | `bb_squeeze_independent` | `KRW-DOGE` | 1,000,000 | Surviving squeeze wallet |
| `bb_squeeze_link_wallet` | `bb_squeeze_independent` | `KRW-LINK` | 1,000,000 | Paper |
| `bb_mr_doge_wallet` | `bollinger_mr` | `KRW-DOGE` | 1,000,000 | Paper |
| `bb_mr_xrp_wallet` | `bollinger_mr` | `KRW-XRP` | 1,000,000 | Paper |
| `bb_mr_avax_wallet` | `bollinger_mr` | `KRW-AVAX` | 1,000,000 | Paper |
| `pdh_pdl_btc_wallet` | `pdh_pdl_sweep_reclaim` | Major KRW basket | 1,000,000 | Winner upsized to `0.015` |
| `vwm_btc_wallet` | `volume_weighted_momentum` | Major KRW basket | 1,000,000 | Winner upsized to `0.015` |
| `ct_sol_vol_target_momentum_wallet` | `momentum` | `KRW-SOL` | 500,000 | New admission, max position `0.12` |
| `ct_sol_momentum_wallet` | `momentum` | `KRW-SOL` | 500,000 | New admission, max position `0.08` |
| `ct_sol_breakout_wallet` | `volatility_breakout` | `KRW-SOL` | 500,000 | New admission, max position `0.08` |
| `ct_eth_breakout_wallet` | `volatility_breakout` | `KRW-ETH` | 500,000 | New admission, max position `0.08` |

## Disabled Wallets

Recent W11 disables:

- `vpin_ondo_wallet`: worst active drain, disabled in `e98d7bb`.
- `vpin_sol_wallet`: 31 paper trades, WR 38.7%, expectancy -312 KRW/trade,
  disabled in `670ff95`.
- `vpin_pundix_wallet`: 22 paper trades, expectancy -229 KRW/trade, disabled in
  `670ff95`.

Previously disabled blocks remain commented for audit/recovery, including
`vpin_mana_wallet`, `vpin_bat_wallet`, `vpin_orbs_wallet`,
`stealth_3gate_wallet_1`, `vpin_eth_wallet`, `vpin_doge_wallet`,
`accumulation_tree_wallet`, and pre-staged `momentum_eth_wallet` /
`momentum_xrp_wallet`.

## Safety Features

### Macro Sizing Integration

`5b2476b` wires macro risk data from the macro adapter/client into the runtime
regime context. Strategies and sizing logic can now consume
`macro_risk_score`, `macro_risk_level`, and `macro_risk_layer` instead of
running blind to macro state.

### Symbol Circuit Breaker

`116751d` introduced a process-wide symbol circuit breaker and `68bc0c2` wired
it into the wallet trade pipeline. Defaults:

- Disable a symbol after 3 losing closes in 48 hours.
- Disable a symbol when expectancy is below -0.5% across at least 5 trades in
  48 hours.
- Cooldown: 24 hours.
- State: `artifacts/symbol-circuit.json`.
- Event stream: `artifacts/circuit-breaker-events.jsonl`, consumed by
  fire-monitor surfaces.

Detailed operator procedure: [docs/2026-05-11-ct-circuit-breaker.md](docs/2026-05-11-ct-circuit-breaker.md).

### Live Scaffold And Preflight

Live mode is scaffolded but not the default. The W11 live-safety chain
(`b24004b`, `d6c2fb8`, `abf91a9`, `cf7b431`, `d0f06af`) added:

- Explicit `LIVE_TRADING_ENABLED=true` or `CT_LIVE_TRADING_ENABLED=true`.
- Fresh `artifacts/live-confirmed.json` operator marker, max age 24h.
- `live_auto_revert_loss_pct = 0.02` early revert-to-paper cap.
- Optional `live_dry_run = true` for full live path without exchange orders.
- `go_live_wallets` allowlist for staged promotion.
- `scripts/preflight_live_check.py` for pre-cutover verification.

Canonical runbook: [docs/2026-05-11-ct-live-migration.md](docs/2026-05-11-ct-live-migration.md).

## Environment Variables

| Variable | Purpose |
|---|---|
| `CT_PAPER_TRADING` | Override paper/live flag. Keep true unless running the live runbook. |
| `LIVE_TRADING_ENABLED` / `CT_LIVE_TRADING_ENABLED` | Required explicit opt-in when `paper_trading = false`. |
| `CT_LIVE_DRY_RUN` | Use `LiveBroker` dry-run path without exchange orders. |
| `CT_GO_LIVE_WALLETS` | Comma/list override for staged live wallet allowlist. |
| `CT_UPBIT_ACCESS_KEY` / `CT_UPBIT_SECRET_KEY` | Upbit credentials. Never commit them. |
| `CT_TELEGRAM_BOT_TOKEN` / `CT_TELEGRAM_CHAT_ID` | Telegram alert channel. Required for live preflight. |
| `CT_SYMBOL_CIRCUIT_PATH` | Override symbol circuit state path. |
| `CT_SYMBOL_CIRCUIT_EVENTS_PATH` | Override circuit breaker event JSONL path. |
| `CT_POLL_INTERVAL_SECONDS` | Runtime polling interval. |
| `CT_HEALTHCHECK_PATH` | Health artifact path. |

## Activation Procedure

### Paper daemon

```bash
pip install -e ".[dev]"
scripts/restart_daemon.sh config/daemon.toml
cat artifacts/daemon-heartbeat.json
cat artifacts/daily-performance.json | python -m json.tool
```

### Live rehearsal only

Do not flip live from this README alone. Use the live migration runbook. The
minimum rehearsal shape is:

```bash
export LIVE_TRADING_ENABLED=true
export CT_LIVE_DRY_RUN=true
export CT_UPBIT_ACCESS_KEY='...'
export CT_UPBIT_SECRET_KEY='...'
PYTHONPATH=src python3 scripts/preflight_live_check.py --config config/daemon.toml
```

If preflight fails, remain in paper and follow
[docs/troubleshooting.md](docs/troubleshooting.md).

## Development

```bash
python3 -m unittest discover -s tests -t . -v
ruff check src/ tests/
mypy src
```

Operational documentation starts at:

- [docs/operations.md](docs/operations.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/2026-05-11-w11-summary.md](docs/2026-05-11-w11-summary.md)
