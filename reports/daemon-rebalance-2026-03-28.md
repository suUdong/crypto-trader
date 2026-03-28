# Daemon Rebalance Review

- Date: `2026-03-28`
- Scope: latest-code 90-day backtest rerun and daemon wallet rebalance
- Inputs:
  - `artifacts/backtest-grid-90d/baseline.json`
  - `artifacts/current-wallet-backtest-90d.json`
  - `config/daemon.toml`

## 1. Full-Strategy 90d Baseline

- The refreshed baseline now covers `13` strategy variants across `4` symbols:
  - `momentum`
  - `momentum_pullback`
  - `bollinger_rsi`
  - `mean_reversion`
  - `composite`
  - `kimchi_premium`
  - `funding_rate`
  - `volume_spike`
  - `obi`
  - `vpin`
  - `volatility_breakout`
  - `ema_crossover`
  - `consensus`
- Total baseline trades: `820`

Highest raw baseline rows worth noting:

| Strategy | Symbol | Return | Trades | Note |
| --- | --- | ---: | ---: | --- |
| `vpin` | `KRW-SOL` | `+1.38%` | `32` | strongest deployable baseline row |
| `consensus` | `KRW-ETH` | `+0.87%` | `24` | positive but still untuned / research-only |
| `volatility_breakout` | `KRW-XRP` | `+0.80%` | `60` | strong daemon candidate |
| `funding_rate` | `KRW-SOL` | `+0.63%` | `32` | still research-only due wallet-level deployment gap |
| `momentum` | `KRW-SOL` | `+0.58%` | `33` | existing daemon winner retained |

## 2. Fresh Daemon-Wallet Benchmark

Latest 90-day cached-candle backtest on the wallet overrides in `config/daemon.toml` before the rebalance:

| Wallet | Return | Sharpe | Trades | Decision |
| --- | ---: | ---: | ---: | --- |
| `volspike_btc_wallet` | `+1.03%` | `3.40` | `7` | keep, but cap size due low sample |
| `vbreak_xrp_wallet` | `+1.79%` | `2.54` | `37` | scale up |
| `vpin_sol_wallet` | `+1.64%` | `1.97` | `37` | scale up |
| `momentum_sol_wallet` | `+0.78%` | `1.08` | `29` | keep |
| `momentum_eth_wallet` | `+0.24%` | `0.67` | `35` | keep |
| `vpin_eth_wallet` | `+0.23%` | `0.53` | `25` | keep |
| `mean_reversion_weekend_wallet` | `+0.10%` | `0.36` | `77` | keep small as defensive sleeve |
| `vpin_btc_wallet` | `-0.21%` | `-0.55` | `28` | remove |
| `momentum_xrp_wallet` | `-0.50%` | `-1.33` | `27` | remove |
| `momentum_btc_wallet` | `-0.29%` | `-1.42` | `10` | remove |

Weighted portfolio return on the old 10-wallet mix: `+0.6075%`

## 3. New Daemon Mix

The daemon now runs `7` wallets:

| Wallet | New Capital |
| --- | ---: |
| `vbreak_xrp_wallet` | `3,500,000` |
| `vpin_sol_wallet` | `2,750,000` |
| `momentum_sol_wallet` | `1,550,000` |
| `volspike_btc_wallet` | `1,000,000` |
| `momentum_eth_wallet` | `950,000` |
| `vpin_eth_wallet` | `750,000` |
| `mean_reversion_weekend_wallet` | `500,000` |

Reasons:

- Removed only the wallets that were both negative-return and negative-Sharpe on the refreshed 90-day wallet benchmark.
- Preserved the strongest live-ready overrides instead of promoting untuned baseline-only candidates.
- Capped `volspike_btc_wallet` despite top Sharpe because it still only produced `7` trades.
- Left `funding_rate`, `ema_crossover`, and `consensus` in research-only status until wallet-level tuning / deployment validation exists.

## 4. Result

Weighted portfolio return on the new 7-wallet mix: `+1.2225%`

This is roughly a `2.01x` lift versus the previous wallet mix on the same 90-day benchmark basis.
