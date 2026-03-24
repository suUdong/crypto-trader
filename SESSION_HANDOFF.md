# Session Handoff

Date: 2026-03-24 (Night Session)
Branch: `master`

## What Landed This Session

### 19. Test coverage expansion (174 -> 202 tests)

Commit: `b43267f`

Added 28 new tests focused on operator/ module:
- **test_strategy_report.py** (NEW, 8 tests): StrategyComparisonReport generate/save with wallets, positions, rankings, multiple symbols
- **test_verdict_engine.py** (+3): daily loss cap fully consumed, current failure without consecutive, zero starting equity
- **test_drift_report.py** (+3): caution from partial gap, elevated error rate -> out_of_sync, signal rate tracking
- **test_promotion_gate.py** (+5): high drawdown blocks, out_of_sync drift, negative paper PnL, None latest_run, save artifact
- **test_runtime_state.py** (+2): load returns None, save overwrites
- **test_calibration.py** (+2): unknown regime, 100% error rate
- **test_regime_report.py** (+1): sideways regime stays near baseline
- **test_operator_memo.py** (+2): None latest_run, drift reasons included
- **test_operator_journal.py** (+2): empty file returns [], limit parameter respected

### 20. OBI & VPIN backtest verification

Commit: `88e414d`

Added `obi` and `vpin` to `scripts/backtest_all.py`. 30-day hourly backtest results:

| Strategy | KRW-BTC | KRW-ETH | KRW-XRP | KRW-SOL | Avg Return | Trades |
|----------|---------|---------|---------|---------|------------|--------|
| Momentum | +4.76% | +8.11% | +6.16% | +2.93% | +5.49% | 99 |
| VPIN | +1.64% | +3.82% | +0.51% | +2.47% | +2.11% | 34 |
| OBI | -0.28% | +1.17% | +1.60% | +1.60% | +1.02% | 182 |
| Mean Rev | -0.42% | +0.19% | +1.00% | +0.22% | +0.25% | 47 |
| Composite | +0.24% | +0.19% | 0.00% | 0.00% | +0.11% | 2 |

- VPIN profitable on ALL 4 symbols, highest win rate (70.8% avg), avg PF 1.86
- OBI high-frequency (182 trades) but thin edge (avg PF 1.13)
- Kimchi Premium cannot backtest (needs live Binance/FX APIs)

### 21. 6-strategy x 4-symbol daemon config

Commit: `adc34ec`

Added `kimchi_premium`, `obi`, `vpin` wallets to `config/daemon.toml`:
- 6 wallets x 4 symbols = 24 evaluations per tick
- Daemon started and verified: first tick showed Kimchi Premium entering all 4 symbols (contrarian buy), Mean Reversion entering XRP and SOL

### 22. Strategy comparison report

Commit: `4439038`

Full 6-strategy comparison report in `artifacts/strategy-report.md`:
- Rankings by return, win rate, profit factor
- Recommendations: Momentum primary, VPIN secondary, OBI diversification
- Daemon status documentation

## Previous Session Capabilities

Already landed before this session:

- Multi-symbol support (4 KRW pairs)
- Individual strategy implementations (Momentum, MeanReversion, Composite)
- Kimchi Premium, OBI, VPIN strategies (commit `7152eec`)
- Strategy wallet isolation (3 -> 6 wallets at 1M KRW each)
- Multi-symbol multi-wallet runtime (`run-multi`)
- Strategy comparison report
- Daemon mode with signal handling
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
- Mobile-first Streamlit dashboard
- Strategy parameter tuning (backtest-verified)
- BacktestEngine strategy-agnostic refactor
- Backtest-all script

## Real-Data Verification Completed

### Backtest verification (this + previous session)

Ran `scripts/backtest_all.py` against real Upbit OHLCV data:
- 30-day hourly candles for KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL
- All 5 backtestable strategies generate buy/sell signals on all 4 symbols
- 364 trades (30d) across 5 strategies x 4 symbols
- Momentum profitable on all symbols; VPIN profitable on all symbols
- OBI profitable on 3/4 symbols
- Kimchi Premium verified in live daemon mode (needs Binance/FX APIs)

### Multi-symbol daemon verification

Using real Upbit OHLCV data through `pyupbit`, verified `run-multi` with:
- 4 symbols: KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL
- 6 wallets: momentum, mean_reversion, composite, kimchi_premium, obi, vpin
- 24 strategy-symbol evaluations per tick (4 x 6)
- Daemon running with 60s poll interval, graceful shutdown on SIGINT
- Checkpoint artifact updating every tick with per-wallet state

## Validation State

Latest validation run passed:

- `python3 -m pytest tests/ -q` -- 202 tests passing
- All linting and type checks clean

The suite includes 202 tests.

## Commands Worth Knowing

From the repo root:

```bash
# Multi-symbol daemon mode (6 strategies, runs indefinitely)
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-multi --config config/daemon.toml

# Backtest a specific strategy
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli backtest --config config/example.toml --strategy momentum

# Backtest all strategies x symbols (30-day or 90-day)
PYTHONPATH=src .venv/bin/python3 scripts/backtest_all.py 30

# Strategy comparison report
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli strategy-report --config config/daemon.toml

# Operator commands
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli regime-report --config config/example.toml
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli operator-report --config config/example.toml
```

## Architecture

```
src/crypto_trader/
  strategy/
    momentum.py          # MomentumStrategy (momentum + RSI)
    mean_reversion.py    # MeanReversionStrategy (Bollinger bands)
    composite.py         # CompositeStrategy (momentum + Bollinger + RSI)
    kimchi_premium.py    # KimchiPremiumStrategy (Upbit vs Binance premium)
    obi.py               # OBIStrategy (order book imbalance)
    vpin.py              # VPINStrategy (volume-synchronized informed trading)
  backtest/
    engine.py            # BacktestEngine (strategy-agnostic via StrategyProtocol)
  wallet.py              # StrategyWallet, build_wallets(), create_strategy()
  multi_runtime.py       # MultiSymbolRuntime with daemon mode + signal handling
  operator/
    strategy_report.py   # StrategyComparisonReport (markdown dashboard)
    verdicts.py          # StrategyVerdictEngine (pause/reduce/promote)
    drift.py             # DriftReportGenerator (backtest vs paper divergence)
    promotion.py         # PromotionGate (paper -> live readiness)
    calibration.py       # DriftCalibrationToolkit
    paper_trading.py     # PaperTradingOperations (journal, snapshot, daily)
    runtime_state.py     # RuntimeCheckpointStore
    journal.py           # StrategyRunJournal
    memo.py              # OperatorDailyMemo
    report.py            # OperatorReportBuilder
    services.py          # generate_operator_artifacts()
  config.py              # WalletConfig, symbols list, daemon_mode
scripts/
  backtest_all.py        # Multi-strategy x multi-symbol backtest runner (5 strategies)
```

## Current Gaps / Risks

1. Kimchi Premium cannot be backtested — needs live Binance price + FX rate. Monitor daemon P&L.
2. OBI has thin edge (avg PF 1.13) — may need position sizing reduction or parameter tuning.
3. Composite strategy is very conservative — only 0-2 trades per 30-day window.
4. Runtime checkpointing is visibility-focused, not full broker-state restart recovery.
5. Operator-layer commands (drift-report, promotion-gate) still single-symbol.
6. Real Telegram send was not live-verified (no bot token/chat ID configured).

## Recommended Next Moves

1. **Per-strategy parameter profiles**: Let each wallet override strategy parameters.
2. **OBI parameter tuning**: Adjust buy/sell thresholds to improve profit factor.
3. **Volatility Breakout Strategy** (P0 from playbook): Larry Williams-style range breakout.
4. **Walk-Forward Analysis**: 6-month in-sample, 1-month out-of-sample rolling validation.
5. Extend operator commands to multi-symbol.
6. Wallet state persistence across daemon restarts.
7. **Kimchi Premium evaluation**: After 24-48h of daemon data, evaluate live performance.

## Most Recent Related Commits

- `4439038` Add 6-strategy comparison report with 30-day backtest analysis
- `adc34ec` Add kimchi_premium, obi, vpin wallets to daemon config
- `88e414d` Add OBI and VPIN to backtest suite, save 30-day results
- `b43267f` Expand operator test coverage from 174 to 202 tests
- `08ddebb` Reduce data client timeouts from 10s to 3s to bound trading loop latency
- `7152eec` Add Kimchi Premium, OBI, and VPIN strategies from playbook

## Notes For The Next Agent

- 6-strategy daemon is running in background. Check `artifacts/runtime-checkpoint.json` for latest state.
- Momentum + VPIN are the two best performers. OBI adds diversification but needs monitoring.
- Kimchi Premium is actively trading (contrarian buys on first tick). Watch for exits.
- `scripts/backtest_all.py` now covers 5 strategies (all except kimchi_premium).
- `artifacts/backtest-30d-2026-03-24.md` has detailed backtest analysis.
- `artifacts/strategy-report.md` has the full 6-strategy comparison.
- 202 tests all passing. Keep paper-first posture intact.
- `config/daemon.toml` is the production daemon config with all 6 wallets.
