# Momentum Pullback Strategy Research

Date: 2026-03-27

## Existing Strategy Snapshot

Current built-in strategy set before this change:

- `momentum`
- `mean_reversion`
- `composite`
- `kimchi_premium`
- `obi`
- `vpin`
- `volatility_breakout`
- `ema_crossover`
- `consensus`
- `volume_spike`

This change adds `momentum_pullback` as a separate research strategy.

## Market Analysis

External market read:

- Coinbase Research published `Monthly Outlook: Blowin' in the Wind` on **March 3, 2026** and said BTC spent most of February inside the `$60k-$70k` range while the team downgraded the quarter outlook to `neutral` because early-year momentum had faded.
- CoinGecko's Bitcoin dominance page, crawled in March 2026, shows BTC dominance still above `56%`, which suggests beta is concentrated in BTC rather than spreading cleanly across the full alt complex.
- CoinGecko's February 2026 gainers note says Bitcoin and Ethereum both faced headwinds while gains rotated into a narrower set of narrative tokens instead of broad-based upside.

Internal project evidence:

- `docs/daily-report-20260325.md` and `docs/live-performance-report-20260327.md` both classify the daemon market regime as `sideways` or weak-trend.
- The same reports show live `momentum` filtering too much or underperforming, while `mean_reversion` performed better live in short windows.
- The 90-day baseline summary in `docs/backtest-grid-results.md` still ranks `momentum` ahead of `mean_reversion` on average.

Inference:

- Pure breakout chasing is too blunt for the current tape.
- Pure dip-buying is still weak across the full 90-day basket.
- A selective "buy the pullback only when the higher-timeframe trend is intact" strategy is a reasonable middle ground.

## Strategy Design

`momentum_pullback` enters only when:

- higher-timeframe trend is intact (`EMA20 > EMA50`, price above `EMA50`)
- medium-term trend momentum remains positive
- price has pulled back from a recent high
- price is in a pullback zone relative to Bollinger mid/lower bands and VWAP
- RSI has reset enough to avoid chasing exhaustion

It exits on:

- max holding period
- trend failure
- recovery into upper-band / overbought conditions

## Validation

Artifacts:

- `artifacts/momentum-pullback-research-2026-03-27.json`
- `artifacts/momentum-pullback-30d-validation.json`

90-day, 4-symbol quick candidate comparison:

- Best tested candidate: `momentum_lookback=15`, `momentum_entry_threshold=0.003`, `bollinger_window=20`, `bollinger_stddev=1.8`, `rsi_period=14`, `rsi_recovery_ceiling=65`, `adx_threshold=15`, `max_holding_bars=36`
- Best candidate average return: `-0.491%`
- Best candidate average Sharpe: `-1.110`
- Best candidate total trades: `58`

Benchmarks on the same quick pass:

- `momentum`: average return `+0.278%`, average Sharpe `0.196`, total trades `125`
- `mean_reversion`: average return `-1.426%`, average Sharpe `-2.752`, total trades `61`

30-day per-symbol validation for the lighter-entry candidate:

- `KRW-BTC`: `-0.031%`, Sharpe `-0.114`, `13` trades
- `KRW-ETH`: `-0.351%`, Sharpe `-2.459`, `10` trades
- `KRW-XRP`: `-1.586%`, Sharpe `-7.733`, `10` trades
- `KRW-SOL`: `+0.342%`, Sharpe `1.117`, `19` trades

## Verdict

`momentum_pullback` is worth keeping as a research strategy because it materially improves on the current `mean_reversion` profile and captures the intended "trend + pullback" behavior. It is not yet strong enough to replace `momentum` as a default deployment candidate, so it remains implemented but not activated in `config/daemon.toml`.
