# Funding Rate Deployment Review

- Date: `2026-03-28`
- Scope: funding-rate strategy production admission check for `config/daemon.toml`
- Decision: `NO_DEPLOY`

## Evidence

### 1. Fresh CLI snapshot (`artifacts/backtest-all-2026-03-28.json`)

- Horizon: `config/daemon.toml` default `candle_count=200` hourly bars
- Funding-rate result:
  - Return: `-0.55%`
  - Sharpe: `-9.88`
  - Max drawdown: `1.60%`
  - Trades: `10`
  - Rank: `8 / 10`

This was only a short-horizon sanity check, not the deployment decision by itself.

### 2. Current daemon wallet benchmark (`artifacts/current-wallet-backtest-90d.json`)

Fresh 90-day cached-candle backtests on the actual wallet overrides in `config/daemon.toml`:

| Wallet | Strategy | Return | Sharpe | MDD |
| --- | --- | ---: | ---: | ---: |
| `volspike_btc_wallet` | `volume_spike` | `+0.73%` | `2.60` | `0.19%` |
| `vbreak_xrp_wallet` | `volatility_breakout` | `+1.82%` | `2.58` | `1.20%` |
| `vpin_sol_wallet` | `vpin` | `+1.68%` | `2.02` | `1.24%` |
| `momentum_sol_wallet` | `momentum` | `+1.22%` | `1.62` | `1.37%` |
| `momentum_eth_wallet` | `momentum` | `+0.24%` | `0.67` | `0.60%` |
| `vpin_eth_wallet` | `vpin` | `+0.25%` | `0.58` | `0.86%` |
| `vpin_btc_wallet` | `vpin` | `-0.01%` | `-0.03` | `0.68%` |
| `kimchi_premium_wallet` | `kimchi_premium` | `-0.27%` | `-0.65` | `1.16%` |
| `momentum_xrp_wallet` | `momentum` | `-0.59%` | `-1.78` | `0.79%` |
| `momentum_btc_wallet` | `momentum` | `-0.48%` | `-2.61` | `0.56%` |

### 3. Funding-rate deployment candidate (`artifacts/funding-rate-long-only-review-90d.json`)

Deployment evaluation used the live-representative constraint set:

- `spot long-only`
- `build_proxy_funding_history()` on the 90-day candle cache
- Short entries disabled via:
  - `high_funding_threshold = 999.0`
  - `extreme_funding_threshold = 999.0`

Best candidate found:

- Strategy params:
  - `negative_funding_threshold = -0.0001`
  - `deep_negative_threshold = -0.0003`
  - `rsi_oversold = 35.0`
  - `momentum_lookback = 10`
  - `min_confidence = 0.45`
  - `max_holding_bars = 36`
  - `cooldown_bars = 6`
- Risk params:
  - `stop_loss_pct = 0.02`
  - `take_profit_pct = 0.04`
  - `risk_per_trade_pct = 0.01`

Candidate performance:

- Avg return: `-0.2467%`
- Avg Sharpe: `-0.8366`
- Max drawdown: `1.4670%`
- Trades: `61`

Per-symbol split:

| Symbol | Return | Sharpe | MDD |
| --- | ---: | ---: | ---: |
| `KRW-BTC` | `-0.90%` | `-1.75` | `1.17%` |
| `KRW-ETH` | `-1.28%` | `-2.69` | `1.47%` |
| `KRW-XRP` | `-0.83%` | `-1.37` | `1.47%` |
| `KRW-SOL` | `+2.03%` | `2.46` | `1.41%` |

## Why It Was Rejected

- The best live-representative funding candidate still had:
  - negative average return
  - negative Sharpe
  - worse Sharpe than `8 / 10` existing daemon wallets
  - higher MDD than several already-profitable wallets
- The strategy is especially weak on `KRW-BTC`, `KRW-ETH`, and `KRW-XRP`; only `KRW-SOL` carries the basket.
- The original funding-rate backtest implementation supports short entries, but the live Upbit spot wallet path does not open new shorts. Promotion must therefore use long-only evidence, not short-enabled backtest results.

## Operational Outcome

- `config/daemon.toml`: unchanged
- Initial capital allocation: not assigned
- Daemon restart: skipped intentionally
- Health check: skipped intentionally

Skipping restart was the correct action because no config was promoted and a no-op restart would add operational risk without changing behavior.
