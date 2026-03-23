# Session Handoff

Date: 2026-03-24
Branch: `master`

## What Landed This Session

### 1. Regime-aware drift thresholds

Commit: `c40c065`

- Drift tolerance now depends on detected market regime
- Bull markets tolerate wider deviation before escalating
- Bear markets escalate faster on the same deviation
- Drift reports now consume regime metadata carried from runtime journal entries

### 2. Daily memo notification integration

Commit: `14a61de`

- The shared operator service can now send the generated daily memo through a `Notifier`
- CLI `daily-memo` stays file-first, but the service layer now supports Telegram delivery
- Memo generation remains channel-agnostic

### 3. Backtest baseline persistence

Commit: `ca6f3bf`

- Operator flows now reuse a persisted backtest baseline artifact
- Baselines are keyed by a config fingerprint
- Drift and promotion logic no longer need to recompute a fresh backtest every time

### 4. Config validation hardening

Commit: `b8b4009`

- Invalid ranges and inconsistent thresholds now fail fast with clear messages
- Runtime artifact paths are validated explicitly

### 5. Paper-trading operations layer

Commit: `51b5470`

- Closed paper trades can be persisted
- Open positions are tracked via a snapshot artifact
- Daily performance report is emitted during runtime sync

### 6. Regime report artifact

Commit: `8d75e5c`

- Added an explicit regime artifact showing detected regime, returns, and adjusted parameters

### 7. Drift calibration toolkit

Commit: `44ec56a`

- Added calibration artifact generation from recent run history
- Produces suggested regime-specific drift tolerances

### 8. Unified operator report

Commit: `f223945`

- Baseline, regime, drift, promotion, calibration, and memo are now merged into one report

### 9. Runtime checkpoint

Commit: `ce2b95e`

- Runtime now writes a checkpoint artifact with iteration, price, signal, verdict, and equity state

## Existing Operator / Strategy-Lab Capabilities

Already landed before this session:

- Strategy run journal
- Strategy verdict engine
- Drift report generation
- Promotion gate
- Daily operator memo
- Regime detection and parameter adjustment
- Backtest baseline persistence
- Regime report generation
- Drift calibration artifact
- Unified operator report
- Runtime checkpointing

## Real-Data Verification Completed

Using real Upbit OHLCV data through `pyupbit` in a local `.venv`, I verified:

1. `run-loop` creates real strategy-run journal entries
2. `promotion-gate` reads the journal and emits a gate artifact
3. `daily-memo` writes a markdown memo artifact
4. `operator-report` writes a unified markdown report artifact
5. `runtime-checkpoint` is updated during the live loop

Generated local artifacts:

- `artifacts/strategy-runs.jsonl`
- `artifacts/backtest-baseline.json`
- `artifacts/regime-report.json`
- `artifacts/drift-calibration.json`
- `artifacts/drift-report.json`
- `artifacts/promotion-gate.json`
- `artifacts/daily-memo.md`
- `artifacts/operator-report.md`
- `artifacts/runtime-checkpoint.json`
- `artifacts/positions.json`
- `artifacts/daily-performance.json`

These are intentionally not committed.

Observed real-data snapshot after sequential verification:

- `promotion_status=do_not_promote`
- `paper_runs=7`
- `drift_status=on_track`
- latest memo reflects `market_regime`, drift, and promotion output together
- 5-iteration real loop completed with live Upbit prices and `continue_paper` verdicts
- no actual fills occurred during this smoke run, so `paper-trades.jsonl` was not created yet

## Validation State

Latest validation run passed:

- `ruff check .`
- `mypy src`
- `python3 -m unittest discover -s tests -t . -v`

The suite now includes 65 tests.

## Commands Worth Knowing

From the repo root:

```bash
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-loop --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli regime-report --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli calibrate-drift --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli drift-report --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli promotion-gate --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli daily-memo --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli operator-report --config config/example.toml
```

## Current Gaps / Risks

1. Real Telegram send was not live-verified because no bot token/chat ID were configured.
2. The smoke run produced no fills, so the paper-trade journal path is still unverified against actual entry/exit traffic.
3. Regime classification and drift calibration remain heuristic and should be tuned against longer historical windows.
4. Runtime checkpointing is visibility-focused, not full broker-state restart recovery.

## Recommended Next Moves

1. Force or observe a real paper trade fill to verify `paper-trades.jsonl` and daily performance against an actual entry/exit.
2. Tune regime and drift thresholds against longer historical windows and more filled-trade samples.
3. Extend runtime checkpointing into fuller restart semantics for broker/session state.
4. Decide whether `operator-report` becomes the primary operator surface or just the base for a future UI.

## Most Recent Related Commits

- `ce2b95e` Leave a checkpoint behind so the operator knows where the loop last stood
- `f223945` Give the operator one report instead of five scattered artifacts
- `44ec56a` Teach the strategy lab to calibrate its own drift tolerances
- `8d75e5c` Explain the detected market regime instead of hiding it inside the strategy
- `51b5470` Make paper trading behave like an operating environment instead of a demo loop
- `ca6f3bf` Stop recomputing the backtest baseline every time an operator asks a question

## Notes For The Next Agent

- The repo is in a good state to keep iterating on the Strategy Lab layer without touching live trading.
- Keep paper-first posture intact.
- Prefer extending `src/crypto_trader/operator/services.py` rather than duplicating orchestration logic in CLI branches.
- If you need a real fill for end-to-end validation, lower entry strictness in a temporary config or run on a more volatile timeframe rather than weakening the committed default config.
