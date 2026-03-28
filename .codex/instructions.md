# crypto-trader -- Codex Instructions

Upbit multi-strategy crypto auto-trading system. See `~/workspace/WORKSPACE.md` for workspace context.

## Project Structure

- `src/crypto_trader/` -- main package (strategies, risk, backtest, data, execution)
- `config/` -- TOML configs (`daemon.toml` = production, 5 active wallets)
- `scripts/` -- CLI tools for backtest, optimization, reports
- `dashboard/` -- Streamlit UI
- `tests/` -- pytest suite

## Safety Constants (NEVER BYPASS)

In `src/crypto_trader/config.py`:
- `HARD_MAX_DAILY_LOSS_PCT = 0.05` -- 5% daily ceiling, config cannot exceed
- `SAFE_MAX_CONSECUTIVE_LOSSES = 3` -- auto-stop after 3 consecutive losses
- `SAFE_DEFAULT_MAX_POSITION_PCT = 0.10` -- max 10% per position

Kill switch (`risk/kill_switch.py`): tiered warn -> reduce -> halt.

## Code Standards

- Python 3.12+, line length 100 (ruff: E/F/I/B/UP)
- mypy strict on `src/` -- all functions need type hints
- Tests: `pytest`, files named `test_*.py`
- Config via TOML dataclasses, no env vars for trading params
- Never commit real API keys

## Commands

```bash
pytest                          # tests
mypy src/                       # type check
ruff check src/ tests/ scripts/ # lint
```

## Rules

- Backtest before changing daemon.toml parameters
- All strategies implement the base strategy interface
- Capital allocation by 90-day ROI + Sharpe ratio
- Any safety constant change requires explicit user approval
