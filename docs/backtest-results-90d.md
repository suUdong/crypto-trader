# 90-Day Backtest Results

Date: 2026-03-27
Last revalidated: 2026-03-27T22:55:00+09:00
Scope: 9 strategies x 4 symbols (`KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`) on 90 days of `minute60` candles from Upbit

## Commands

```bash
PYTHONPATH=src .venv/bin/python scripts/backtest_all.py 90 --cache-dir artifacts/candle-cache --json-out artifacts/backtest-results-90d.json
PYTHONPATH=src .venv/bin/python scripts/strategy_correlation_analysis.py 90 --cache-dir artifacts/candle-cache
PYTHONPATH=src .venv/bin/python scripts/portfolio_optimizer.py 90 --correlation artifacts/strategy-correlation-90d.json
```

Focused re-optimization for the changed strategies was written to:

- `artifacts/backtest-grid-90d/focused-strategies.json`
- `artifacts/backtest-grid-90d/combined.json`
- `config/optimized.toml`

## Executive Summary

- All 36 strategy/symbol runs completed successfully with `2160` candles per symbol.
- Total trades across the full matrix: `591`
- All 9 strategies generated at least one trade.
- By average return, `momentum` ranked first at `+0.23%` with `119` trades and `1.16` average PF.
- `composite` stayed near-flat at `+0.05%`, but only produced `4` trades and still has a thin sample problem.
- `vpin` moved near flat at `+0.01%` and remained the strongest broad trade generator after `momentum`.
- Default-parameter `mean_reversion` was still weak at `-1.30%`, but the focused retune lifted it to `+0.45%` average return with `0.36` Sharpe in the tuning artifact.
- New `bollinger_rsi` baseline finished at `-0.93%`, while the focused sweep improved it to `-0.10%` with `0.03` Sharpe. It remains research-only.

## Strategy Summary

| Strategy | Avg Return | Avg MDD | Avg Win Rate | Avg PF | Total Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| momentum | +0.23% | 1.16% | 45.3% | 1.16 | 119 |
| composite | +0.05% | 0.17% | 50.0% | inf | 4 |
| vpin | +0.01% | 1.90% | 48.2% | 1.02 | 87 |
| kimchi_premium | -0.08% | 1.75% | 50.7% | 0.97 | 59 |
| obi | -0.25% | 1.31% | 49.0% | 0.83 | 68 |
| volatility_breakout | -0.34% | 1.31% | 37.2% | 0.55 | 102 |
| momentum_pullback | -0.67% | 1.50% | 42.2% | 0.55 | 46 |
| bollinger_rsi | -0.93% | 2.14% | 61.2% | 0.65 | 64 |
| mean_reversion | -1.30% | 1.85% | 33.4% | 0.37 | 42 |

## Focused Re-optimization

| Strategy | Avg Sharpe | Avg Return | Avg MDD | Total Trades | Best Params |
| --- | ---: | ---: | ---: | ---: | --- |
| mean_reversion | +0.36 | +0.45% | 1.53% | 80 | `bollinger_window=16`, `bollinger_stddev=1.5`, `rsi_period=8`, `rsi_oversold_floor=20`, `rsi_recovery_ceiling=28`, `noise_lookback=10`, `adx_threshold=28`, `max_holding_bars=18` |
| bollinger_rsi | +0.03 | -0.10% | 1.72% | 74 | `bollinger_window=14`, `bollinger_stddev=1.5`, `rsi_period=8`, `rsi_oversold_floor=15`, `rsi_recovery_ceiling=30`, `rsi_overbought=65`, `max_holding_bars=18` |

## Best and Worst Runs

Best return combinations:

| Rank | Strategy | Symbol | Return | MDD | Win Rate | Trades | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | vpin | KRW-SOL | +1.38% | 1.70% | 56.2% | 32 | 1.57 |
| 2 | kimchi_premium | KRW-BTC | +0.64% | 1.27% | 52.9% | 17 | 1.39 |
| 3 | volatility_breakout | KRW-XRP | +0.63% | 2.41% | 45.9% | 61 | 1.14 |
| 4 | momentum | KRW-ETH | +0.58% | 0.75% | 42.4% | 33 | 1.38 |
| 5 | obi | KRW-SOL | +0.49% | 1.14% | 50.0% | 22 | 1.35 |

Worst return combinations:

| Rank | Strategy | Symbol | Return | MDD | Win Rate | Trades | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | obi | KRW-XRP | -0.98% | 2.03% | 50.0% | 10 | 0.48 |
| 2 | momentum_pullback | KRW-BTC | -1.06% | 1.19% | 40.0% | 10 | 0.26 |
| 3 | bollinger_rsi | KRW-XRP | -1.16% | 1.99% | 50.0% | 10 | 0.48 |
| 4 | mean_reversion | KRW-ETH | -1.85% | 2.11% | 10.0% | 10 | 0.13 |
| 5 | mean_reversion | KRW-SOL | -1.95% | 2.27% | 27.3% | 11 | 0.10 |

## Portfolio Diversification Notes

- Correlation analysis artifact: `artifacts/strategy-correlation-90d.md`
- Highest overlap among materially active strategies was `momentum <-> vpin` (`0.499`) and `bollinger_rsi <-> mean_reversion` (`0.540`).
- Best diversified high-quality cluster was `composite + momentum`, followed by `composite + kimchi_premium + momentum`.
- Correlation-adjusted portfolio weights favored `kimchi_premium` (`31.2%`), `composite` (`30.0%`), `momentum` (`29.6%`), and a smaller `mean_reversion` sleeve (`8.5%`).
- `bollinger_rsi` received only a token allocation (`0.7%`) because diversification was acceptable but tuned edge was still near zero.

## Takeaways

- `momentum` remains the most reliable default baseline strategy.
- `mean_reversion` no longer looks unrecoverable: the focused sweep moved it from clear negative territory into a modest positive in-sample research candidate.
- `bollinger_rsi` is now implemented and measurable, but it did not yet prove enough edge to earn meaningful portfolio weight.
- The strongest diversified research mix is not the old single-strategy winner model; it is a balanced `kimchi_premium + composite + momentum` core with a smaller `mean_reversion` diversifier.
