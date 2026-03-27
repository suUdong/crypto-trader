# Live Trading Log Analysis — 2026-03-27

## Executive Summary

- **Daemon**: paper mode, 10 wallets (new optimized config from fd0a4f1 + 3f05219)
- **Total signal evaluations**: 16,296 across 20 wallets (includes legacy wallets)
- **Market regime**: 97% sideways, 3% bear — worst possible conditions for momentum strategies
- **Realized trades**: 4 wallets traded, ALL lost money (total -18,914 KRW)
- **Portfolio equity**: 10,996,734 KRW (-0.03% from 11M starting)

## 1. Config Change Effect (3f05219 + fd0a4f1)

### What changed:
- **3f05219**: Stabilized risk controls, restored clean static-check baseline
- **fd0a4f1**: Cut underperformers (15→10 wallets), concentrated capital on Sharpe-ranked winners

### Measured effect:
- **Positive**: All 10 wallets evaluating correctly, no errors since restart
- **Positive**: Correlation guard working (dedup fix 88ffa7f confirmed)
- **Positive**: Kill switch, ATR stops, partial TP all active
- **Negative**: Near-zero signal generation in current bear/sideways market
- **Neutral**: Too early to measure alpha — need trending market to validate

## 2. Per-Wallet Signal Analysis (New Config)

| Wallet | Strategy | Evals | Buys | Sells | Top Hold Reason |
|--------|----------|-------|------|-------|-----------------|
| momentum_sol_wallet | momentum | 460 | 0 | 0 | entry_conditions_not_met (RSI 15, bear regime) |
| momentum_eth_wallet | momentum | 890 | 3 | 2 | entry_conditions_not_met (71%), volume_too_low (7%) |
| momentum_btc_wallet | momentum | 997 | 2 | 0 | entry_conditions_not_met (83%) |
| momentum_xrp_wallet | momentum | 267 | 0 | 0 | entry_conditions_not_met (76%), volume_too_low (24%) |
| vpin_sol_wallet | vpin | 992 | 1 | 0 | entry_conditions_not_met (64%), position_open (36%) |
| vpin_btc_wallet | vpin | 881 | 1 | 0 | entry_conditions_not_met (96%) |
| vpin_eth_wallet | vpin | 1,007 | 3 | 0 | entry_conditions_not_met (61%), position_open (38%) |
| vbreak_xrp_wallet | vbreak | 460 | 0 | 0 | below_ma_filter (91%) |
| volspike_btc_wallet | volspike | 629 | 0 | 0 | no_volume_spike (94%) |
| kimchi_premium_wallet | kimchi | 4,006 | 71 | 1 | position_open (78%), cooldown (16%) |

## 3. Key Findings

### Why most wallets are idle:
1. **All symbols deeply oversold**: RSI 15-23 across BTC/ETH/SOL/XRP
2. **Strong bear regime on SOL/ETH**: Momentum negative (-3%), below EMA50
3. **Below MA filter**: vbreak_xrp blocked 91% of the time
4. **No volume spikes**: Quiet sideways market, volume ratio 0.6-1.1x (need 2-3x)
5. **VPIN low**: 0.33-0.40, well below buy threshold (0.45+)

### kimchi_premium is overtrading:
- 71 buys vs 1 sell = positions accumulate without exit
- Realized loss: -1,715 KRW from 1 BTC trade (ATR stop at -1.96%)
- Still holding 2 positions (SOL + ETH) — underwater

### Legacy wallets (momentum_wallet):
- 126 buy/sell pairs, all losses (rsi_overbought exits)
- -10,367 KRW realized — this wallet is from OLD config, ignore for analysis

## 4. Recommendations

1. **Wait for trending market** — Momentum strategies are correctly sitting out sideways/bear
2. **Fix kimchi_premium exit logic** — Too many buys, not enough sells. Need tighter TP or time-based exit
3. **Consider bear-market strategy** — All current strategies are long-only, useless in downtrend
4. **Lower entry thresholds slightly** — momentum_entry_threshold 0.002-0.003 may be too tight in low-vol
5. **Re-run grid search** with broader param space to find params that work across regimes
