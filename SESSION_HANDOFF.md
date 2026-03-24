# Session Handoff

Date: 2026-03-24
Branch: `master`

## What Landed This Session

### 16. Strategy parameter tuning + backtest verification

Commit: `f7edb45`

**Problem**: All strategies emitted only HOLD — entry conditions were contradictory.

**Root cause**:
- Composite required momentum >= 2% (price rising) AND lower Bollinger band (price falling) simultaneously
- Momentum required momentum >= 2% AND RSI 25-45, but strong momentum pushes RSI above 45
- Mean reversion required 2-sigma lower band (only ~5% of candles reach it)

**Parameter changes**:

| Parameter | Before | After | Rationale |
|-----------|--------|-------|-----------|
| `momentum_entry_threshold` | 0.02 | 0.005 | 2% was too strict for hourly candles |
| `rsi_recovery_ceiling` | 45.0 | 60.0 | Allow entries when RSI isn't deeply oversold |
| `rsi_oversold_floor` | 25.0 | 20.0 | Catch deeper oversold conditions |
| `bollinger_stddev` | 2.0 | 1.8 | Lower band reachable in ~10% of candles vs ~5% |
| `max_holding_bars` | 24 | 48 | Give trades 2 days instead of 1 |
| `stop_loss_pct` | 0.02 | 0.03 | Wider stop to avoid premature exits |
| `take_profit_pct` | 0.04 | 0.06 | Wider target for better R:R |

**Regime adjuster changes**:
- Bull: momentum reduction from -0.01 to -0.003, RSI ceiling cap raised from 60 to 75
- Bear: momentum increase from +0.02 to +0.01 (proportional to lower base)

**Backtest results (30-day hourly, real Upbit data)**:

| Strategy | Symbol | Return | Win Rate | PF | Trades |
|----------|--------|--------|----------|----|--------|
| Momentum | ETH | +9.22% | 63.0% | 2.62 | 27 |
| Momentum | XRP | +4.56% | 55.6% | 1.66 | 27 |
| Momentum | BTC | +3.68% | 54.2% | 1.75 | 24 |
| Mean Rev | SOL | +2.41% | 69.2% | 1.44 | 13 |
| Mean Rev | ETH | +1.48% | 64.3% | 1.23 | 14 |
| Composite | BTC | +0.24% | 100% | inf | 1 |

**90-day results**: 247 total trades. Momentum on ETH: +5.17% (PF 1.32). All 3 strategies generated signals across all 4 symbols.

### 17. BacktestEngine strategy-agnostic refactor

Commit: `f7edb45`

- `BacktestEngine` now accepts `StrategyProtocol` instead of `CompositeStrategy`
- CLI `backtest` command gains `--strategy` flag: `momentum`, `mean_reversion`, `composite`
- No test changes needed (existing tests use CompositeStrategy which satisfies the protocol)

### 18. Backtest-all script

Commit: `f7edb45`

- `scripts/backtest_all.py` — runs all strategy x symbol combinations on real Upbit data
- Supports configurable lookback period: `python scripts/backtest_all.py 30` (default 90 days)
- Paginated candle fetching for > 200 candles (pyupbit limit)
- Prints formatted table with return%, MDD, win rate, trade count, profit factor

## Previous Session Capabilities

Already landed before this session:

- Multi-symbol support (4 KRW pairs)
- Individual strategy implementations (Momentum, MeanReversion, Composite)
- Strategy wallet isolation (3 wallets at 1M KRW each)
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

## Real-Data Verification Completed

### Backtest verification (this session)

Ran `scripts/backtest_all.py` against real Upbit OHLCV data:
- 30-day and 90-day hourly candles for KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL
- All 3 strategies generate buy/sell signals on all 4 symbols
- 157 trades (30d) / 247 trades (90d) across all combinations
- Momentum strategy is profitable on all symbols in 30-day window
- Mean reversion profitable on 3 of 4 symbols in 30-day window

### Multi-symbol daemon verification

Using real Upbit OHLCV data through `pyupbit`, verified `run-multi` with:
- 4 symbols: KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL
- 3 wallets: momentum, mean_reversion, composite
- 12 strategy-symbol evaluations per tick (4 x 3)
- Daemon running with 60s poll interval, graceful shutdown on SIGINT
- Checkpoint artifact updating every tick with per-wallet state

## Validation State

Latest validation run passed:

- `ruff check src/ tests/`
- `mypy src`
- `python3 -m unittest discover -s tests -t . -v`

The suite includes 99 tests.

## Commands Worth Knowing

From the repo root:

```bash
# Multi-symbol daemon mode (default, runs indefinitely)
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli run-multi --config config/daemon.toml

# Backtest a specific strategy
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli backtest --config config/example.toml --strategy momentum

# Backtest all strategies x symbols (30-day or 90-day)
PYTHONPATH=src .venv/bin/python3 scripts/backtest_all.py 30

# Strategy comparison report
PYTHONPATH=src .venv/bin/python -m crypto_trader.cli strategy-report --config config/example.toml

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
  backtest/
    engine.py            # BacktestEngine (strategy-agnostic via StrategyProtocol)
  wallet.py              # StrategyWallet, build_wallets(), create_strategy()
  multi_runtime.py       # MultiSymbolRuntime with daemon mode + signal handling
  operator/
    strategy_report.py   # StrategyComparisonReport (markdown dashboard)
  config.py              # WalletConfig, symbols list, daemon_mode
scripts/
  backtest_all.py        # Multi-strategy x multi-symbol backtest runner
```

## Current Gaps / Risks

1. Real Telegram send was not live-verified (no bot token/chat ID configured).
2. Composite strategy is very conservative — only 0-2 trades per symbol in 30-day window. May need separate parameter profiles per strategy type.
3. Mean reversion loses money on 90-day data despite winning on 30-day — needs longer-term regime filter.
4. Runtime checkpointing is visibility-focused, not full broker-state restart recovery.
5. Operator-layer commands (drift-report, promotion-gate) still single-symbol.

## Recommended Next Moves

1. **Per-strategy parameter profiles**: Let each wallet override strategy parameters (different thresholds for momentum vs mean_reversion).
2. **Volatility Breakout Strategy** (P0 from playbook): Larry Williams-style range breakout, 40-80% CAGR backtested.
3. **Kimchi Premium Filter** (P0 from playbook): KRW premium filter reduces MDD from -25% to -12%.
4. **Walk-Forward Analysis**: 6-month in-sample, 1-month out-of-sample rolling validation (WFE > 85%).
5. Extend operator commands to multi-symbol.
6. Wallet state persistence across daemon restarts.

## Most Recent Related Commits

- `f7edb45` Tune strategy parameters so entries actually fire on real Upbit data
- `68c07d0` Add mobile-first Streamlit dashboard with token auth and 6-tab layout
- `c2ae9d4` Add strategy playbook synthesized from 211 research notes
- `0f87daf` Refresh the handoff with the multi-symbol wallet architecture
- `7b7cb00` Let each strategy prove itself across multiple coins with its own wallet

## Notes For The Next Agent

- The repo is in a good state. Strategies now generate real buy/sell signals.
- Momentum strategy is the best performer — profitable on all symbols in recent 30 days.
- `scripts/backtest_all.py` is the quickest way to validate parameter changes.
- `docs/strategy-playbook.md` has the full research-backed roadmap for new strategies.
- Keep paper-first posture intact.
- `run-multi` is the recommended command; `run-loop` is the legacy single-symbol path.
- `config/daemon.toml` is the production daemon config; `config/example.toml` is the reference config.
