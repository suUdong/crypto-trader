# Wallet Configuration Rationale

**Date**: 2026-03-29
**Commit**: f46e61f (P0 parameter optimization — re-enable 3-wallet diversified portfolio)
**Source**: `scripts/optimize_p0.py` — 384 backtests, 90-day hourly Upbit candles

## Capital Allocation

| Wallet | Strategy | Symbol | Capital | Share | Sharpe | WR% | MDD% | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vpin_eth | vpin | KRW-ETH | ₩3,500,000 | 61.4% | 1.11 | 60.0 | 0.10 | 1.78 |
| momentum_sol | momentum | KRW-SOL | ₩1,200,000 | 21.1% | 1.55 | 50.0 | 0.46 | 2.95 |
| volspike_btc | volume_spike | KRW-BTC | ₩1,000,000 | 17.5% | 3.00 | 71.4 | 0.09 | 7.76 |
| **TOTAL** | | | **₩5,700,000** | **100%** | | | | |

Allocation weighted by Sharpe + downside protection. vpin_eth gets the largest share as the
only wallet that was profitable in both backtesting and paper trading prior to the P0 round.

## Global Parameters (applied to all wallets)

| Parameter | Value | Rationale |
| --- | ---: | --- |
| `atr_stop_multiplier` | 1.5 | Grid search showed near-zero impact on exits (strategies exit via RSI/momentum, not ATR stops). 1.5 kept as safety net; 2.5 and 3.0 performed identically. |
| `min_entry_confidence` | 0.45 | Outperformed 0.6–0.8 across all wallets. Lower threshold = more trades at same quality. |
| `stop_loss_pct` | 0.03 | Global default; per-wallet overrides where tighter risk needed. |

## Per-Wallet Parameter Details

### 1. vpin_eth_wallet (KRW-ETH, ₩3.5M)

**Why this wallet**: Only paper-profitable wallet before P0 optimization. Anchor allocation.

| Parameter | Before P0 | After P0 | Why |
| --- | ---: | ---: | --- |
| `vpin_high_threshold` | 0.70 | 0.65 | Tighter sell-pressure threshold catches reversals earlier |
| `vpin_low_threshold` | 0.40 | 0.35 | Requires cleaner buy-side order flow before entry |
| `vpin_momentum_threshold` | 0.0005 | 0.0003 | Captures smaller momentum signals in ETH's lower-vol regime |
| `max_holding_bars` | 18 | 24 | Allows more time for winners to develop; old value cut too early |
| `vpin_rsi_ceiling` | 70.0 | 65.0 | Avoids near-overbought entries — key win-rate improvement |
| `stop_loss_pct` | 0.015 | 0.012 | Tighter per-trade risk; smaller losses on wrong entries |
| `cooldown_bars` | 3 | 4 | More spacing between trades to avoid churn |
| `atr_stop_multiplier` | 3.0 | 1.5 | Minimal impact on exits; lower value as safety net only |
| `bucket_count` | 20 | 24 | More granular VPIN calculation for ETH's order flow |
| `ema_trend_period` | — | 20 | Trend filter to avoid counter-trend entries |

**90d backtest result**: Sharpe 1.11, WR 60%, MDD 0.10%, PF 1.78
**90d baseline (default params)**: Sharpe 0.38, WR 47.1% — optimization nearly tripled Sharpe.

### 2. momentum_sol_wallet (KRW-SOL, ₩1.2M)

**Why this wallet**: KRW-SOL showed the strongest momentum signal in the 90d baseline
(Sharpe 2.60, WR 63.6%, PF 6.92). Re-enabled after being disabled during the concentration
phase.

| Parameter | Value | Why |
| --- | ---: | --- |
| `momentum_lookback` | 20 | Longer window (vs default 12) smooths SOL's high volatility |
| `momentum_entry_threshold` | 0.005 | Higher bar than default 0.001; stronger trend confirmation |
| `rsi_overbought` | 75.0 | Slightly looser than default 72 to avoid cutting SOL rallies short |
| `max_holding_bars` | 48 | SOL trends persist longer; 36-bar default exits too early |
| `adx_threshold` | 12.0 | Lower than default 20; SOL trends start at lower ADX values |
| `stop_loss_pct` | 0.03 | Standard 3% stop for SOL's volatility |
| `take_profit_pct` | 0.08 | 8% TP from grid search; 6% left too much on the table |
| `risk_per_trade_pct` | 0.015 | Slightly above global 1% for higher-conviction entries |
| `volume_filter_mult` | 0.0 | Disabled — SOL volume patterns too noisy for filtering |
| `fear_greed_block_threshold` | 20 | Block entries in extreme fear (< 20) regimes |

**P0 grid search result**: Sharpe 1.55, WR 50%, MDD 0.46%, PF 2.95
**Grid**: 144 backtests (4 ATR × 3 confidence × 3 TP × 2 lookback × 2 RSI).

### 3. volspike_btc_wallet (KRW-BTC, ₩1.0M)

**Why this wallet**: Highest Sharpe (3.00) and win rate (71.4%) in P0 optimization.
BTC volume spikes are rare but highly predictive. Smallest allocation because trade count
is low — fewer opportunities but very high quality.

| Parameter | Value | Why |
| --- | ---: | --- |
| `spike_mult` | 3.0 | Requires 3× average volume; filters noise, keeps only true spikes |
| `volume_window` | 20 | 20-bar lookback for volume baseline |
| `min_body_ratio` | 0.2 | Low threshold catches both strong and moderate conviction candles |
| `rsi_overbought` | 72.0 | Standard threshold; BTC rarely hits extreme overbought |
| `max_holding_bars` | 36 | Standard hold period for BTC's slower price discovery |
| `adx_threshold` | 20.0 | Standard — only trade when trend present |
| `stop_loss_pct` | 0.03 | 3% stop matches BTC's volatility profile |
| `take_profit_pct` | 0.06 | 6% TP (grid preferred 6% over 8% for BTC — mean-reverts faster) |
| `atr_stop_multiplier` | 1.5 | Safety net only; exits driven by other signals |

**P0 grid search result**: Sharpe 3.00, WR 71.4%, MDD 0.09%, PF 7.76
**Grid**: 48 backtests (3 ATR × 2 confidence × 2 TP × 2 spike_mult × 2 body_ratio).
**Note**: Default-param baseline for volume_spike/KRW-BTC was Sharpe -0.98 — optimization
flipped it from a losing to a winning strategy.

## Disabled Wallets

| Wallet | Reason | Re-enable Condition |
| --- | --- | --- |
| momentum_eth | Paper 0W/2L (−₩6,353), 100% loss rate in extreme-fear regime | Fear & Greed > 30, regime neutral/bull |
| vpin_sol | Backtest overfitted (Sharpe 0.53 below 1.0 target); live showed counter-trend entries | Fundamental strategy redesign or new regime |
| vbreak_xrp | Live −0.119% | Strategy redesign needed |
| mean_reversion_weekend | Live −0.051%, too weak | Hibernate indefinitely |

## Key Optimization Findings

1. **ATR multiplier has near-zero impact**: All wallets exit via RSI/momentum signals, not
   ATR-based stops. The ATR stop is a safety net that rarely triggers. Values 1.5–3.0
   produced identical results. Set to 1.5 as cheapest safety net.

2. **Lower confidence (0.45) beats higher (0.6–0.8)**: More trades at the same quality.
   The confidence filter was over-restrictive at 0.7+, causing missed profitable entries.

3. **Symbol-specific tuning matters**: SOL needs longer lookback (20) and higher momentum
   threshold (0.005) due to volatility. ETH needs tighter VPIN thresholds (0.35/0.65).
   BTC volume spikes need high spike_mult (3.0) but low body_ratio (0.2).

4. **Win rate tuning (33% → 50%+ target)**: Achieved via tighter VPIN thresholds,
   lower RSI ceilings, shorter holding periods, and increased cooldown bars.

## Data Sources

- `scripts/optimize_p0.py`: 384-backtest grid search (commit f46e61f)
- `backtest_results/strategy-comparison-90d.md`: 90-day baseline across 13 strategies
- `backtest_results/strategy-comparison-report.md`: IS vs OOS validation analysis
- `config/optimized.toml`: Earlier auto_tune.py results (superseded by P0 optimization)

## Verification Checklist

- [x] All 3 active wallet params match P0 grid search best results
- [x] Global `min_entry_confidence=0.45` and `atr_stop_multiplier=1.5` applied
- [x] Capital sums to ₩5,700,000
- [x] Safety rails intact: `max_daily_loss_pct=0.03`, `max_consecutive_losses=3`
- [x] Disabled wallets documented with re-enable conditions
- [x] No param in daemon.toml contradicts P0 optimization results
