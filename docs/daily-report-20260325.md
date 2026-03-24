# Daily Performance Report - 2026-03-25

## Daemon Status

- **Process**: PID 1258342 (running)
- **Uptime**: ~24h (started 2026-03-24)
- **Iterations**: 416 ticks completed
- **Config**: 6 wallets x 4 symbols = 24 evaluations per tick
- **Poll interval**: 60s
- **Mode**: Paper trading (daemon_mode)

## 24h Portfolio Performance

| Wallet | Strategy | Equity (KRW) | Return | Open Positions | Trades | Status |
|--------|----------|-------------|--------|----------------|--------|--------|
| mean_reversion_wallet | Mean Reversion | 1,005,231 | **+0.523%** | 4 | 0 | Best |
| kimchi_premium_wallet | Kimchi Premium | 1,003,615 | **+0.361%** | 4 | 0 | Active |
| obi_wallet | OBI | 1,000,746 | **+0.075%** | 2 | 0 | Active |
| composite_wallet | Composite | 1,000,000 | 0.000% | 0 | 0 | Idle |
| vpin_wallet | VPIN | 1,000,000 | 0.000% | 0 | 0 | Idle |
| momentum_wallet | Momentum | 999,044 | **-0.096%** | 1 | 0 | Underwater |
| **Portfolio Total** | | **6,008,636** | **+0.144%** | **11** | **0** | |

- Starting capital: 6,000,000 KRW (1M per wallet)
- Unrealized P&L: +8,636 KRW
- No realized trades yet (all positions still open)

## 6-Strategy x 4-Symbol Comparison

### Live Daemon (24h Mark-to-Market)

| Rank | Strategy | Return | Positions | Notes |
|------|----------|--------|-----------|-------|
| 1 | Mean Reversion | +0.523% | 4/4 symbols | Entered XRP, SOL early; all 4 positions in profit |
| 2 | Kimchi Premium | +0.361% | 4/4 symbols | Contrarian buy on all symbols (first tick) |
| 3 | OBI | +0.075% | 2/4 symbols | Selective entry, thin edge |
| 4 | Composite | 0.000% | 0/4 symbols | No entry signals triggered (very conservative) |
| 5 | VPIN | 0.000% | 0/4 symbols | No entry signals triggered |
| 6 | Momentum | -0.096% | 1/4 symbols | Single position, slightly underwater |

### 30-Day Backtest Reference (from 2026-03-24)

| Strategy | KRW-BTC | KRW-ETH | KRW-XRP | KRW-SOL | Avg Return | Trades |
|----------|---------|---------|---------|---------|------------|--------|
| Momentum | +4.76% | +8.11% | +6.16% | +2.93% | +5.49% | 99 |
| VPIN | +1.64% | +3.82% | +0.51% | +2.47% | +2.11% | 34 |
| OBI | -0.28% | +1.17% | +1.60% | +1.60% | +1.02% | 182 |
| Mean Rev | -0.42% | +0.19% | +1.00% | +0.22% | +0.25% | 47 |
| Composite | +0.24% | +0.19% | 0.00% | 0.00% | +0.11% | 2 |
| Kimchi | N/A | N/A | N/A | N/A | N/A | N/A |

### Win Rate & Profit Factor (Backtest)

| Strategy | Avg Win Rate | Avg Profit Factor |
|----------|-------------|-------------------|
| VPIN | 70.8% | 1.86 |
| Mean Rev | 59.6% | 1.06 |
| Momentum | 52.4% | 2.07 |
| OBI | 43.0% | 1.13 |

## Strategy-Report CLI Output

```
Per-Wallet Summary (live snapshot at report time):
- All 6 wallets at 1,000,000 KRW starting equity
- 0 realized trades across all wallets
- Strategy-report reads fresh wallet state (no position carryover)
- Actual mark-to-market state tracked in runtime-checkpoint.json
```

## Operator-Report CLI Output

- **Market regime**: Sideways
  - Short return: -0.95% (mixed)
  - Long return: +0.71% (mixed)
- **Drift status**: on_track (paper behavior aligned with backtest)
- **Promotion gate**: do_not_promote
  - Reason: no realized PnL yet, backtest return not positive (single-symbol baseline)
  - Paper runs observed: 12
- **Calibration**: sideways regime, 10 samples

## Signal Analysis (strategy-runs.jsonl)

- **Total logged runs**: 12 (from legacy single-wallet mode, pre-daemon)
- **Time range**: 2026-03-23 18:58 ~ 2026-03-24 02:00 UTC
- **All signals**: HOLD (entry_conditions_not_met)
- **Symbol**: KRW-BTC only (legacy mode)
- **Errors**: 0
- **Note**: Multi-wallet daemon writes to runtime-checkpoint.json, not strategy-runs.jsonl

## Key Observations

1. **Mean Reversion is the surprise leader** (+0.523%) in live daemon, despite being 4th in backtest rankings. It entered all 4 symbols aggressively.

2. **Kimchi Premium is performing well** (+0.361%) with 4 open positions. This is the first live evaluation since it cannot be backtested (needs Binance/FX APIs).

3. **Momentum underperforms live** (-0.096%) despite being the #1 backtest performer (+5.49% avg). Only 1 position open. The sideways market regime may be suppressing its trend-following signals.

4. **VPIN and Composite remain idle** - no entry signals triggered in 24h. VPIN's selectivity (70.8% backtest win rate) means fewer entries, but 24h of silence warrants monitoring.

5. **Zero realized trades** - all positions are unrealized. Need more time for exit signals to trigger and close positions.

6. **Sideways market regime** is confirmed by operator-report. This favors mean reversion strategies over momentum/trend-following.

## Backtest vs Live Divergence

| Strategy | Backtest Rank | Live Rank | Divergence |
|----------|--------------|-----------|------------|
| Momentum | 1 (+5.49%) | 6 (-0.096%) | Large - sideways regime hurts trend-following |
| VPIN | 2 (+2.11%) | 4-5 (0.000%) | Moderate - no signals yet |
| OBI | 3 (+1.02%) | 3 (+0.075%) | Aligned |
| Mean Rev | 4 (+0.25%) | 1 (+0.523%) | Inverted - sideways regime helps |
| Composite | 5 (+0.11%) | 4-5 (0.000%) | Aligned (both conservative) |
| Kimchi | N/A | 2 (+0.361%) | N/A (no backtest baseline) |

## Recommendations

1. **Continue monitoring** - 24h is too short for meaningful statistical conclusions. No realized trades yet.
2. **Watch Momentum** - if sideways regime persists, Momentum may continue to underperform. Consider regime-filtered position sizing.
3. **Kimchi Premium validation** - promising early results (+0.361%) but 4 open positions on contrarian buys carry risk if market trends.
4. **VPIN investigation** - 24h with zero signals is unusual given 34 trades in 30-day backtest. Verify signal generation logic in daemon mode.
5. **Wait for exits** - no strategy has closed a trade yet. First round of exits will provide win rate and profit factor data.
6. **Promotion gate**: premature. Minimum 5-7 days of data needed before considering any paper-to-live transition.

## Next Steps

- Continue daemon operation for 48-72h more
- Re-evaluate after first realized trades occur
- Run 90-day backtest for longer-term validation
- Investigate VPIN/Composite signal suppression in daemon mode
- Daily report generation for trend tracking
