# crypto-trader

Upbit-first multi-strategy crypto auto-trading system with backtesting, paper trading, and live execution.
Part of the FIRE workspace -- see `~/workspace/WORKSPACE.md` for cross-project dependency graph.

## Architecture

```
src/crypto_trader/
  config.py          # AppConfig dataclass, TOML loader, HARD safety constants
  pipeline.py        # Single-symbol trading pipeline (signal -> risk -> order)
  runtime.py         # Single-wallet runtime loop
  multi_runtime.py   # Multi-wallet daemon supervisor
  models.py          # Signal, Order, PipelineResult dataclasses
  wallet.py          # Wallet state tracking
  capital_allocator.py
  strategy/          # Strategy implementations (momentum, vpin, volume_spike, etc.)
    composite.py     # CompositeStrategy -- multi-strategy consensus
    evaluator.py     # Strategy evaluation framework
  risk/
    manager.py       # RiskManager -- position sizing, stop-loss, take-profit
    kill_switch.py   # Tiered kill switch (warn -> reduce -> halt)
  backtest/          # Backtesting engine, grid search, walk-forward
  data/              # Market data clients (Upbit, candle cache)
  execution/         # Paper broker, live broker
  macro/             # macro-intelligence integration
  monitoring/        # Health checks, PnL snapshots
  notifications/     # Telegram alerts
  operator/          # Operator reports, journals, memos
config/              # TOML configs (daemon.toml = production)
scripts/             # CLI tools: backtest, optimize, reports
dashboard/           # Streamlit dashboard
tests/               # pytest suite
```

## Tech Stack

- Python 3.12+, setuptools
- Upbit REST API via pyupbit
- pytest, mypy (strict on src/), ruff (E/F/I/B/UP)
- Streamlit dashboard
- macro-intelligence HTTP client for regime signals

## Safety Rules (NEVER BYPASS)

These hard limits in `config.py` are non-negotiable safety rails:
- `HARD_MAX_DAILY_LOSS_PCT = 0.05` -- 5% daily max loss ceiling, config cannot exceed this
- `SAFE_MAX_CONSECUTIVE_LOSSES = 3` -- auto-stop after 3 consecutive losses
- `SAFE_DEFAULT_MAX_POSITION_PCT = 0.10` -- no single position > 10% of portfolio

The kill switch in `risk/kill_switch.py` is tiered: warn (50%) -> reduce position (75%) -> halt (100%).
Any change to safety constants requires explicit user approval.

## Coding Rules

- Line length: 100 chars (ruff)
- Type hints required for all src/ code (mypy strict)
- Tests in `tests/`, named `test_*.py`, run with `pytest`
- Config via TOML dataclasses -- no env vars for trading params
- All strategies must implement the base strategy interface
- Backtest before deploying any parameter change to daemon.toml
- Never commit real API keys -- credentials fields stay empty in config

## Key Commands

```bash
pytest                              # run all tests
pytest tests/test_risk_hardening.py # safety-specific tests
mypy src/                           # type check
ruff check src/ tests/ scripts/     # lint
python -m crypto_trader.cli         # run daemon
```

## Config Hierarchy

1. `config/daemon.toml` -- production config (5 active wallets)
2. `config/live.toml` -- live trading overrides
3. `config/optimized.toml` -- latest optimization results
4. Per-wallet `strategy_overrides` / `risk_overrides` in `[[wallets]]` sections

## Wallet Strategy

Capital allocated by 90-day ROI + Sharpe ratio. Disabled wallets stay in config
as comments. See `daemon.toml` comments for allocation rationale.
