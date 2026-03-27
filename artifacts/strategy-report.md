# Crypto-Trader Strategy Execution Report
Generated: 2026-03-27 09:52
Daemon PID: 730249 | Iteration: 5 | Wallets: 13
Total signal records: 5919

## Portfolio Summary

| Wallet | Equity | Cash | Realized PnL | Open Positions |
|--------|--------|------|-------------|----------------|
| consensus_btc_wallet | 1,000,000 | 1,000,000 | 0 | - |
| ema_cross_btc_wallet | 1,000,000 | 1,000,000 | 0 | - |
| kimchi_premium_wallet | 998,732 | 673,676 | 0 | KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL |
| mean_rev_eth_wallet | 1,000,000 | 1,000,000 | 0 | - |
| momentum_btc_wallet | 1,000,000 | 1,000,000 | 0 | - |
| momentum_eth_wallet | 1,000,000 | 1,000,000 | 0 | - |
| vbreak_btc_wallet | 1,000,000 | 1,000,000 | 0 | - |
| vbreak_eth_wallet | 1,000,000 | 1,000,000 | 0 | - |
| volspike_btc_wallet | 1,000,000 | 1,000,000 | 0 | - |
| volspike_eth_wallet | 1,000,000 | 1,000,000 | 0 | - |
| vpin_btc_wallet | 1,000,000 | 1,000,000 | 0 | - |
| vpin_eth_wallet | 1,000,000 | 1,000,000 | 0 | - |
| vpin_sol_wallet | 1,000,000 | 1,000,000 | 0 | - |
| **TOTAL** | **12,998,732** | | **0** | |

## Signal Distribution

| Wallet | Buy | Sell | Hold | Total | Avg Conf | Buy Rate |
|--------|-----|------|------|-------|----------|----------|
| composite_wallet | 0 | 0 | 398 | 398 | 0.20 | 0.0% |
| consensus_btc_wallet | 0 | 0 | 308 | 308 | 0.10 | 0.0% |
| ema_cross_btc_wallet | 0 | 0 | 157 | 157 | 0.20 | 0.0% |
| kimchi_premium_wallet | 53 | 0 | 1459 | 1512 | 0.14 | 3.5% |
| mean_rev_eth_wallet | 0 | 0 | 156 | 156 | 0.20 | 0.0% |
| mean_reversion_wallet | 0 | 0 | 398 | 398 | 0.20 | 0.0% |
| momentum_btc_wallet | 0 | 0 | 308 | 308 | 0.20 | 0.0% |
| momentum_eth_wallet | 1 | 0 | 316 | 317 | 0.20 | 0.3% |
| momentum_wallet | 140 | 70 | 144 | 354 | 0.53 | 39.5% |
| unknown | 5 | 0 | 343 | 348 | 0.15 | 1.4% |
| vbreak_btc_wallet | 1 | 1 | 312 | 314 | 0.20 | 0.3% |
| vbreak_eth_wallet | 2 | 0 | 309 | 311 | 0.20 | 0.6% |
| volspike_btc_wallet | 0 | 0 | 56 | 56 | 0.10 | 0.0% |
| volspike_eth_wallet | 0 | 0 | 56 | 56 | 0.10 | 0.0% |
| vpin_btc_wallet | 0 | 0 | 308 | 308 | 0.20 | 0.0% |
| vpin_eth_wallet | 1 | 0 | 316 | 317 | 0.20 | 0.3% |
| vpin_sol_wallet | 0 | 0 | 301 | 301 | 0.20 | 0.0% |

## Consensus Sub-Strategy Analysis

The consensus_btc_wallet uses momentum + vpin + volume_spike (min_agree=1).
Current BTC market conditions (1H candles):
- Momentum: -0.77% (negative, needs >= 0.1%)
- RSI: 40.67 (in valid range 20-70)
- ADX: 21.84 (above threshold 15.0)
- Volume ratio: 1.38x (needs 1.8x for volume_spike)
- Body ratio: -0.21 (bearish candle)

All sub-strategies correctly hold due to negative momentum and no volume spike.
Config overrides (entry_threshold=0.001, adx_threshold=15, spike_mult=1.8) are properly applied.

## Active Positions

- **kimchi_premium_wallet** / KRW-BTC: entry=104,233,090.5
- **kimchi_premium_wallet** / KRW-ETH: entry=3,121,560.0
- **kimchi_premium_wallet** / KRW-XRP: entry=2,060.0
- **kimchi_premium_wallet** / KRW-SOL: entry=130,865.4

## Hold Reason Breakdown (Top 10)

- entry_conditions_not_met: 2644 (44.7%)
- position_open_waiting: 952 (16.1%)
- cooldown_active: 723 (12.2%)
- below_ma_filter: 513 (8.7%)
- adx_too_weak: 308 (5.2%)
- consensus_insufficient:0/2: 275 (4.6%)
- momentum_rsi_alignment: 141 (2.4%)
- no_volume_spike: 112 (1.9%)
- rsi_overbought: 70 (1.2%)
- consensus_insufficient:0/1: 62 (1.0%)