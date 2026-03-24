# Session Handoff

Date: 2026-03-24
Branch: `master`

## What Landed This Session

### 10. Multi-symbol support

Commit: `7b7cb00`

- `TradingConfig.symbols` accepts a list of KRW pairs (BTC, ETH, XRP, SOL)
- Backward compatible: if only `trading.symbol` (singular) is set, it wraps into a one-element list
- Config validation enforces all symbols start with `KRW-`
- `config/example.toml` updated with 4 default symbols

### 11. Individual strategy implementations

Commit: `7b7cb00`

- `MomentumStrategy` in `strategy/momentum.py` — momentum + RSI entry/exit signals
- `MeanReversionStrategy` in `strategy/mean_reversion.py` — Bollinger band mean reversion signals
- Both implement the same `evaluate(candles, position) -> Signal` interface
- `CompositeStrategy` unchanged (no regression)
- Factory function `create_strategy(type, config, regime_config)` in `wallet.py`

### 12. Strategy wallet isolation

Commit: `7b7cb00`

- `WalletConfig` dataclass: name, strategy type, initial capital
- `StrategyWallet` bundles strategy instance + PaperBroker + RiskManager
- Each wallet tracks independent cash, positions, realized PnL
- Configurable via `[[wallets]]` array in TOML
- Default: three wallets (momentum, mean_reversion, composite) at 1M KRW each

### 13. Multi-symbol multi-wallet runtime

Commit: `7b7cb00`

- `MultiSymbolRuntime` in `multi_runtime.py` iterates all symbols x all wallets per tick
- Candle caching: one fetch per symbol per tick, shared across wallets
- Per-wallet checkpoint state saved to `runtime-checkpoint.json`
- CLI command: `run-multi`

### 14. Strategy comparison report

Commit: `7b7cb00`

- `StrategyComparisonReport` in `operator/strategy_report.py`
- Markdown dashboard: per-wallet summary table, position details, performance rankings
- Rankings by return % and trade count
- CLI command: `strategy-report`

### 15. Daemon mode with signal handling

Commit: `7b7cb00`

- `RuntimeConfig.daemon_mode` (default `true`) — runs indefinitely ignoring `max_iterations`
- SIGINT and SIGTERM trigger graceful shutdown (finish current tick, then exit)
- Poll interval configurable via `runtime.poll_interval_seconds`

## Previous Session Capabilities

Already landed before this session:

- Regime-aware drift thresholds
- Daily memo notification integration
- Backtest baseline persistence
- Config validation hardening
- Paper-trading operations layer
- Regime report artifact
- Drift calibration toolkit
- Unified operator report
- Runtime checkpoint
- Strategy run journal
- Strategy verdict engine
- Drift report generation
- Promotion gate
- Regime detection and parameter adjustment

## Real-Data Verification Completed

### Multi-symbol daemon verification

Using real Upbit OHLCV data through `pyupbit`, verified `run-multi` with:

- 4 symbols: KRW-BTC (105M), KRW-ETH (3.1M), KRW-XRP (2,107), KRW-SOL (134,900)
- 3 wallets: momentum, mean_reversion, composite
- 12 strategy-symbol evaluations per tick (4 x 3)
- Daemon running with 60s poll interval, graceful shutdown on SIGINT
- Checkpoint artifact updating every tick with per-wallet state

### Previous single-symbol verification

- `run-loop` creates real strategy-run journal entries
- `promotion-gate` reads the journal and emits a gate artifact
- `daily-memo` writes a markdown memo artifact
- `operator-report` writes a unified markdown report artifact
- `runtime-checkpoint` is updated during the live loop

Generated local artifacts:

- `artifacts/runtime-checkpoint.json` (now includes per-wallet states)
- `artifacts/strategy-report.md` (new)
- `artifacts/strategy-runs.jsonl`
- `artifacts/backtest-baseline.json`
- `artifacts/regime-report.json`
- `artifacts/drift-calibration.json`
- `artifacts/drift-report.json`
- `artifacts/promotion-gate.json`
- `artifacts/daily-memo.md`
- `artifacts/operator-report.md`
- `artifacts/positions.json`
- `artifacts/daily-performance.json`

These are intentionally not committed.

## Validation State

Latest validation run passed:

- `ruff check .`
- `mypy src`
- `python3 -m unittest discover -s tests -t . -v`

The suite now includes 81 tests (66 existing + 15 new).

## Commands Worth Knowing

From the repo root:

```bash
# Multi-symbol daemon mode (default, runs indefinitely)
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-multi --config config/daemon.toml

# Multi-symbol daemon with example config
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-multi --config config/example.toml

# Strategy comparison report
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli strategy-report --config config/example.toml

# Legacy single-symbol loop
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-loop --config config/example.toml

# Operator commands (unchanged)
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli regime-report --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli calibrate-drift --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli drift-report --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli promotion-gate --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli daily-memo --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli operator-report --config config/example.toml
```

## Architecture: New Modules

```
src/crypto_trader/
  strategy/
    momentum.py          # MomentumStrategy (momentum + RSI)
    mean_reversion.py    # MeanReversionStrategy (Bollinger bands)
    composite.py         # CompositeStrategy (unchanged, all three factors)
  wallet.py              # StrategyWallet, build_wallets(), create_strategy()
  multi_runtime.py       # MultiSymbolRuntime with daemon mode + signal handling
  operator/
    strategy_report.py   # StrategyComparisonReport (markdown dashboard)
  config.py              # +WalletConfig, +symbols list, +daemon_mode
```

## Current Gaps / Risks

1. Real Telegram send was not live-verified because no bot token/chat ID were configured.
2. No fills have occurred yet in the multi-symbol daemon — all strategies are holding, waiting for entry conditions to align.
3. Regime classification and drift calibration remain heuristic and should be tuned against longer historical windows.
4. Runtime checkpointing is visibility-focused, not full broker-state restart recovery. Restarting the daemon resets all wallet state.
5. The operator-layer commands (drift-report, promotion-gate, etc.) still operate on a single symbol. They have not been extended to multi-symbol yet.

## Recommended Next Moves

1. Let the daemon run long enough to observe real paper fills across multiple symbols and strategies.
2. Extend operator-layer commands (drift, promotion, memo) to work across all configured symbols.
3. Implement wallet state persistence so daemon restarts don't lose position/PnL history.
4. Add per-symbol strategy parameter overrides (different thresholds per coin).
5. Build a web UI or richer terminal dashboard on top of `strategy-report.md`.

## Most Recent Related Commits

- `7b7cb00` Let each strategy prove itself across multiple coins with its own wallet
- `48c1432` Read older run journals without blowing up the live loop
- `b9108f4` Refresh the handoff with the fully runnable operator stack
- `ce2b95e` Leave a checkpoint behind so the operator knows where the loop last stood
- `f223945` Give the operator one report instead of five scattered artifacts
- `44ec56a` Teach the strategy lab to calibrate its own drift tolerances

## Notes For The Next Agent

- The repo is in a good state. Multi-symbol daemon is the primary runtime now.
- Keep paper-first posture intact.
- `run-multi` is the recommended command; `run-loop` is the legacy single-symbol path.
- Prefer extending `wallet.py` and `multi_runtime.py` for new multi-symbol features.
- Prefer extending `src/crypto_trader/operator/services.py` rather than duplicating orchestration logic in CLI branches.
- `config/daemon.toml` is the production daemon config; `config/example.toml` is the reference config.
- If you need a real fill for end-to-end validation, lower entry strictness in a temporary config or run on a more volatile timeframe rather than weakening the committed default config.
