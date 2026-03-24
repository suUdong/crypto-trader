# Strategy Comparison Report — 6 Strategies x 4 Symbols

Generated: 2026-03-24

## 30-Day Backtest Results (Hourly Candles, Upbit OHLCV)

### Performance Matrix

| Strategy | KRW-BTC | KRW-ETH | KRW-XRP | KRW-SOL | Avg Return | Total Trades |
|----------|---------|---------|---------|---------|------------|-------------|
| Momentum | +4.76% | +8.11% | +6.16% | +2.93% | +5.49% | 99 |
| VPIN | +1.64% | +3.82% | +0.51% | +2.47% | +2.11% | 34 |
| OBI | -0.28% | +1.17% | +1.60% | +1.60% | +1.02% | 182 |
| Mean Rev | -0.42% | +0.19% | +1.00% | +0.22% | +0.25% | 47 |
| Composite | +0.24% | +0.19% | 0.00% | 0.00% | +0.11% | 2 |
| Kimchi | N/A | N/A | N/A | N/A | N/A | N/A |

### Win Rate Comparison

| Strategy | KRW-BTC | KRW-ETH | KRW-XRP | KRW-SOL | Avg |
|----------|---------|---------|---------|---------|-----|
| Momentum | 50.0% | 60.0% | 57.7% | 41.7% | 52.4% |
| VPIN | 83.3% | 72.7% | 57.1% | 70.0% | 70.8% |
| OBI | 35.4% | 46.3% | 50.0% | 40.4% | 43.0% |
| Mean Rev | 58.3% | 58.3% | 58.3% | 63.6% | 59.6% |

### Profit Factor Comparison

| Strategy | KRW-BTC | KRW-ETH | KRW-XRP | KRW-SOL | Avg |
|----------|---------|---------|---------|---------|-----|
| Momentum | 2.35 | 2.43 | 2.05 | 1.43 | 2.07 |
| VPIN | 2.28 | 2.16 | 1.19 | 1.79 | 1.86 |
| OBI | 0.97 | 1.15 | 1.22 | 1.16 | 1.13 |
| Mean Rev | 0.91 | 1.03 | 1.25 | 1.04 | 1.06 |

## Strategy Rankings

### By Average Return
1. **Momentum** (+5.49%) -- Best absolute returns, profitable on all symbols
2. **VPIN** (+2.11%) -- Second best, profitable on all symbols
3. **OBI** (+1.02%) -- Profitable on 3/4 symbols, high frequency
4. **Mean Reversion** (+0.25%) -- Low returns, profitable on 3/4
5. **Composite** (+0.11%) -- Very conservative, few trades
6. **Kimchi Premium** (N/A) -- Requires live market data

### By Risk-Adjusted Performance (Profit Factor)
1. **Momentum** (avg PF 2.07) -- Consistently above 1.4
2. **VPIN** (avg PF 1.86) -- Highest win rate, selective entries
3. **OBI** (avg PF 1.13) -- Many trades but thin edge
4. **Mean Reversion** (avg PF 1.06) -- Near breakeven

### By Win Rate
1. **VPIN** (70.8%) -- Best risk discipline
2. **Mean Reversion** (59.6%) -- Good entry accuracy
3. **Momentum** (52.4%) -- Moderate but high PF compensates
4. **OBI** (43.0%) -- Low win rate, relies on larger winners

## Recommendations

1. **Momentum** remains the top performer. Keep as primary strategy.
2. **VPIN** is recommended as second core strategy — excellent risk-adjusted returns with very high win rates.
3. **OBI** provides diversification through high-frequency uncorrelated signals. Consider reducing position sizes.
4. **Mean Reversion** shows marginal alpha. Monitor for improvement with regime filtering.
5. **Composite** is too conservative for standalone use. May work as a confirming filter.
6. **Kimchi Premium** is live-only. First daemon tick showed active entries (contrarian buys). Monitor P&L over coming days.

## Daemon Status

6-wallet x 4-symbol daemon started at 2026-03-24T14:33:41Z.
- 24 evaluations per tick, 60s poll interval
- Kimchi Premium: entered positions on all 4 symbols (contrarian buy)
- Mean Reversion: entered XRP and SOL (Bollinger reversion)
- All other strategies: HOLD on first tick
