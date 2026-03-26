# Session Handoff

Date: 2026-03-26 (FIRE Session #2)
Branch: `master`

## What Landed This Session

### Per-Wallet Strategy & Risk Overrides
- `WalletConfig` now supports `strategy_overrides`, `risk_overrides`, and `symbols` fields
- Each wallet can override any `StrategyConfig` or `RiskConfig` parameter via TOML
- Extra params (kimchi's `min_trade_interval_bars`, `min_confidence`, `cooldown_hours`) passed to strategy constructors
- Per-wallet symbol filtering in `MultiSymbolRuntime` — wallets only process assigned symbols
- Full validation of override keys against known fields

### Optimized Daemon Config (daemon.toml)
- **Momentum wallet**: Walk-forward fold 2 params (Sharpe 1.91, WR 58%)
  - `momentum_lookback=15, entry_threshold=0.008, rsi_period=18, rsi_overbought=65, max_holding_bars=36`
  - Symbols: BTC+ETH only (XRP/SOL excluded — negative returns in 90d backtest)
  - Risk: SL 3%, TP 10%, risk 1%
- **Kimchi premium wallet**: Grid search optimal (Sharpe 1.22, WR 51%)
  - Overrides: `rsi_period=14, rsi_recovery_ceiling=50, rsi_overbought=75, max_holding_bars=24`
  - Extra: `cooldown=6h (was 24h), min_confidence=0.4, min_trade_interval=6 bars`
  - Risk overrides: SL 2%, TP 4%, ATR multiplier 3.0
  - Symbols: all 4 (BTC, ETH, XRP, SOL)
- **Confidence gate lowered**: 0.6 → 0.5 (more momentum entries)
- **5 negative-Sharpe strategies excluded**: mean_reversion, vpin, volatility_breakout, obi, composite

### Key Findings
- Momentum confidence formula `0.5 + abs(momentum_value)` means entry_threshold=0.008 → confidence=0.508, blocked by 0.6 gate
- mean_reversion signals buy but confidence ≈ 0.52, always below 0.6 gate (moot — negative Sharpe anyway)
- Momentum profitable on BTC (+1.37%) and ETH (+7.05%) but loses on XRP (-5.11%) and SOL (-5.44%)
- Kimchi premium backtest uses simulated premium; live uses real Binance/FX → expect divergence

## Architecture Updates

```
src/crypto_trader/
  config.py           # + WalletConfig.symbols, strategy_overrides, risk_overrides
                      # + _apply_strategy_overrides(), _apply_risk_overrides()
                      # + _STRATEGY_EXTRA_OVERRIDE_FIELDS for kimchi params
                      # + _validate_strategy_config(), _validate_risk_config() extracted
  wallet.py           # + allowed_symbols per wallet
                      # + create_strategy extra_params support
                      # + build_wallets uses per-wallet overrides
                      # + _strategy_config_for_wallet(), _risk_config_for_wallet()
  multi_runtime.py    # + per-wallet symbol filtering in _run_tick()
config/
  daemon.toml         # Walk-forward + grid-search optimized, 2 wallets, per-wallet overrides
```

## Validation State

- `pytest tests/ -q` → 461 tests passing
- Daemon running with new config, kimchi immediately executed ETH contrarian buy
- Per-wallet symbol filtering verified in logs

## Current Gaps / Risks

1. Kimchi premium backtest uses simulated premium — live may diverge
2. Sideways market → momentum signals rare (expected, backtest agrees)
3. Telegram notifications not live-verified (no bot token)
4. Paper trading restarted — need 7 days for micro-live gate

## Recommended Next Moves

1. **Monitor paper trading** for 7 days → micro-live gate by Apr 2
2. **Add walk-forward for kimchi_premium** (currently grid-search only)
3. **Per-symbol momentum tuning** — BTC and ETH may benefit from different params
4. **Add composite strategy** with higher-confidence filter (Sharpe 1.16 but only 2 trades)
5. **Telegram bot setup** for daily PnL alerts
