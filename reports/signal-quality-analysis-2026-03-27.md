# Signal Quality Analysis

Date: 2026-03-27
Window analyzed: 2026-03-26T19:24:43+00:00 to 2026-03-27T13:24:43+00:00

## Summary
- The live-style `momentum_*` wallets did not show a clear 24-hour false-positive cluster.
- The noisy deployment path was `kimchi_premium_wallet`.
- Recent `kimchi_premium` entries used shallow positive premium (`+0.23%` to `+0.26%`) and mid-range RSI (`43` to `45`) but still reached confidence around `0.637`.
- The two recent closed kimchi trades both stopped out:
  - `KRW-BTC`: entry `2026-03-27T08:00:00+00:00`, exit `2026-03-27T11:00:00+00:00`, `-1.96%`, `atr_stop_loss`
  - `KRW-ETH`: entry `2026-03-27T09:00:00+00:00`, exit `2026-03-27T12:00:00+00:00`, `-2.60%`, `atr_stop_loss`
- No strong false-negative cluster was found on the momentum deployment wallets in this same window.

## False positives
Matched loss-making kimchi entries to their nearest signal runs:

1. `KRW-BTC`
   - signal time: `2026-03-27T08:15:02+00:00`
   - reason: `kimchi_premium_safe_zone_rsi_entry`
   - confidence: `0.6387`
   - indicators: `kimchi_premium=0.0023`, `rsi=44.85`

2. `KRW-ETH`
   - signal time: `2026-03-27T09:12:12+00:00`
   - reason: `kimchi_premium_safe_zone_rsi_entry`
   - confidence: `0.6368`
   - indicators: `kimchi_premium=0.0026`, `rsi=43.70`

Interpretation: the old safe-zone rule opened trades too early on mild premium edges without a deeper RSI reset.

## False negatives
- No material false-negative pattern appeared on `momentum_btc_wallet`, `momentum_eth_wallet`, `momentum_xrp_wallet`, or `momentum_sol_wallet` in the latest 24-hour window.
- Given the absence of a momentum false-negative cluster, the patch focused on reducing kimchi noise rather than loosening live momentum gates.

## Changes made
- Added a kimchi premium outlier guard to suppress obviously suspect feed values.
- Tightened safe-zone entries to require both:
  - premium no wider than `+0.30%`
  - RSI reset no higher than `40`
- Reworked kimchi safe-zone confidence so deeper discount and deeper RSI reset score higher, while shallow setups no longer cluster near the execution threshold.
- Preserved true `entry_confidence` from BUY signal through position storage, checkpoint persistence, and closed-trade journaling.

## Verification
- Passed:
  - `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kimchi_premium.py tests/test_paper_trading_operations.py tests/test_wallet.py`
  - `PYTHONPATH=src timeout 120 .venv/bin/python -m pytest tests/test_multi_symbol.py tests/test_grid_search.py tests/test_walk_forward_cli.py`
- Repo-wide pre-existing failures remain outside this change:
  - `tests/test_dashboard.py::TestDataLoaders::test_live_filters_drop_out_of_session_and_future_rows`
  - `tests/test_auto_tune.py::TestAutoTuneOutputs::test_default_strategies_cover_all_supported_strategies`
  - `ruff` existing issues in `tests/test_daemon_heartbeat.py` and `tests/test_telegram_pnl.py`
