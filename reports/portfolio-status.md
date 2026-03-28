# Portfolio Status Report — 2026-03-29 06:40 KST

## Daemon Health

| Metric | Value |
|---|---|
| Status | **healthy** |
| PID | 260972 |
| Wallets | 4 active (momentum_eth removed per be05907) |
| Open Positions | 3 |
| Poll Interval | 60s |
| Consecutive Failures | 0 |
| Restart Count | 0 |
| Supervisor | active, auto-restart enabled |
| Macro Regime | neutral (confidence 19%), market=sideways, weekend=true |
| Last Tick | 2026-03-28T21:40:24Z (2.17s duration) |

## Open Positions (mark-to-market as of 21:40 UTC)

| Wallet | Symbol | Side | Entry Price | Market Price | Unrealized PnL | PnL % | Value (KRW) |
|---|---|---|---|---|---|---|---|
| vpin_sol_wallet | KRW-SOL | long | 127,095 | 125,600 | -2,685 | -1.18% | 225,537 |
| vpin_eth_wallet | KRW-ETH | long | 3,073,303 | 3,059,000 | -273 | -0.47% | 58,418 |
| momentum_sol_wallet | KRW-SOL | long | 126,595 | 125,600 | -243 | -0.79% | 30,676 |

**Total Unrealized PnL: -3,201 KRW (-0.06% of equity)**

## Portfolio Summary

| Metric | Value |
|---|---|
| Total Equity | 5,265,388 KRW |
| Cash | 4,950,757 KRW (94.0%) |
| Open Position Value | 314,631 KRW (6.0%) |
| Starting Capital | 5,700,000 KRW |
| Total Return | -434,612 KRW (-7.63%) |

## Closed Trades Analysis (paper-trades.jsonl, 8 trades)

| # | Wallet | Symbol | PnL (KRW) | PnL % | Exit Reason | Date |
|---|---|---|---|---|---|---|
| 1 | vbreak_btc | BTC | -579 | -0.35% | close_below_prev_low | 03-27 |
| 2 | momentum_eth | ETH | -3,376 | -1.35% | momentum_reversal | 03-27 |
| 3 | momentum_eth | ETH | -2,977 | -1.19% | momentum_reversal | 03-27 |
| 4 | kimchi_premium | BTC | -1,715 | -1.96% | atr_stop_loss | 03-27 |
| 5 | kimchi_premium | ETH | -2,105 | -2.60% | atr_stop_loss | 03-27 |
| 6 | vbreak_xrp | XRP | -1,792 | -0.72% | close_below_prev_low | 03-27 |
| 7 | **vpin_eth** | ETH | **+3,524** | **+1.60%** | rsi_overbought | 03-28 |
| 8 | vpin_eth | ETH | -204 | -0.35% | rsi_overbought | 03-28 |

**Closed PnL: -9,224 KRW | Win Rate: 1/8 (12.5%)**

### Strategy Breakdown

| Strategy | Trades | Total PnL | Avg PnL % |
|---|---|---|---|
| momentum_eth | 2 | -6,353 | -1.27% |
| kimchi_premium | 2 | -3,820 | -2.28% |
| vbreak | 2 | -2,371 | -0.53% |
| **vpin_eth** | **2** | **+3,320** | **+0.63%** |

## Config Change Impact (be05907)

1. **momentum_eth disabled** -- Confirmed removed from wallet list at 06:26 restart. Previously generated 2 consecutive losses (-6,353 KRW). Good call.
2. **vpin_eth boosted** -- Only profitable strategy so far (+3,320 KRW net). Currently holding ETH long position. Wallet multiplier set to 0.6x.
3. **F&G filter** -- No explicit filter-block logs observed. Momentum suppression appears to work via `volume_too_low` and `entry_conditions_not_met` signals on momentum_sol_wallet, which is consistent with tighter entry conditions in sideways/weekend regime.
4. **VPIN dominance confirmed** -- 2 of 3 open positions are VPIN wallets. Post-config, only VPIN strategies have opened new positions.

## Daemon Stability

- Running continuously since 06:31:49 (latest restart after SIGTERM)
- 60-second poll cycle, all ticks completing in ~2s
- Zero errors, zero failed results
- All 4 wallets responding every tick
- Macro layer connecting but reporting "unavailable" -- using market_regime fallback (sideways)
- Weekend mode active: reduced wallet multipliers (momentum 0.3x, vpin 0.6x, volspike 0.5x)

## Observations & Recommendations

1. **VPIN is the edge** -- Only strategy with positive expectancy so far. Consider further capital allocation toward vpin wallets.
2. **Sideways market** -- All signals are hold. Weekend + sideways regime means low activity is expected and healthy.
3. **Macro layer unavailable** -- Falling back to market_regime only. Check macro-intelligence service if this persists post-weekend.
4. **Low position exposure (6%)** -- Conservative in sideways regime. Kill switch is far from activation thresholds.
5. **12h heartbeat** -- Daemon should be checked again around 18:40 KST to confirm uninterrupted operation through the weekend.
