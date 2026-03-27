# Live Verification Report — 2026-03-27 09:24 KST

## Executive Summary

- **Daemon**: PID 652485, 13 wallets, 4 symbols (BTC/ETH/XRP/SOL)
- **Config fix applied**: `volume_spike` strategy + `consensus.weights` added to validator
- **Restart script fix**: Now uses venv python with PYTHONPATH
- **All 13 wallets active** — including previously blocked volspike + consensus

## 1. Daemon Restart

| Item | Status |
|------|--------|
| Config validator fix | `volume_spike` added to valid_strategies, override keys registered |
| Consensus `weights` override | Registered in `_STRATEGY_EXTRA_OVERRIDE_FIELDS` |
| Restart script | Fixed to use `.venv/bin/python` + `PYTHONPATH=src` |
| Position restore | 4 positions restored from checkpoint across 13 wallets |
| Candle fetch | Working (pyupbit via venv) |

## 2. Previously Blocked Wallets — Now Active

| Wallet | Status | First Signal |
|--------|--------|-------------|
| `volspike_btc_wallet` | ACTIVE | hold / no_volume_spike |
| `volspike_eth_wallet` | ACTIVE | hold / no_volume_spike |
| `consensus_btc_wallet` | ACTIVE | hold / consensus_insufficient:0/1 |

All three wallets that were blocked by the config validation error are now evaluating signals correctly.

## 3. Volume Spike Strategy Signal Check

- `volspike_btc_wallet` KRW-BTC: no volume spike detected (volume_ratio=0.46, spike_mult threshold=2.5)
- `volspike_eth_wallet` KRW-ETH: no volume spike detected (volume_ratio=0.46, spike_mult threshold=2.0)
- Market is sideways with low volume — no spike signal expected
- Strategy is correctly evaluating: checking volume_ratio, body_ratio, momentum, RSI, ADX

## 4. Wallet Performance Summary (All-Time)

| Wallet | Strategy | Signals | Buys | Sells | Open Pos | Realized PnL |
|--------|----------|---------|------|-------|----------|-------------|
| kimchi_premium_wallet | kimchi_premium | 1,300 | 53 | 0 | 4 | 0.00 |
| momentum_wallet (legacy) | momentum | 334 | 66 | 66 | 0 | -863.80 |
| vbreak_eth_wallet | volatility_breakout | 258 | 2 | 0 | 0 | 0.00 |
| vbreak_btc_wallet | volatility_breakout | 261 | 1 | 1 | 0 | 0.00 |
| momentum_eth_wallet | momentum | 264 | 1 | 0 | 0 | 0.00 |
| vpin_eth_wallet | vpin | 264 | 1 | 0 | 0 | 0.00 |
| consensus_btc_wallet | consensus | 255 | 0 | 0 | 0 | 0.00 |
| volspike_btc_wallet | volume_spike | 3 | 0 | 0 | 0 | 0.00 |
| volspike_eth_wallet | volume_spike | 3 | 0 | 0 | 0 | 0.00 |
| ema_cross_btc_wallet | ema_crossover | 104 | 0 | 0 | 0 | 0.00 |
| mean_rev_eth_wallet | mean_reversion | 103 | 0 | 0 | 0 | 0.00 |

## 5. Open Positions (kimchi_premium_wallet)

| Symbol | Entry Price | Current | Qty | Cost (KRW) | Value (KRW) | PnL | PnL% |
|--------|-----------|---------|-----|-----------|------------|-----|------|
| KRW-BTC | 104,233,091 | 103,936,000 | 0.0024 | 250,159 | 249,446 | -713 | -0.29% |
| KRW-ETH | 3,121,560 | 3,113,000 | 0.0084 | 26,255 | 26,183 | -72 | -0.27% |
| KRW-XRP | 2,060 | 2,055 | 12.30 | 25,335 | 25,273 | -62 | -0.24% |
| KRW-SOL | 130,865 | 130,500 | 0.187 | 24,447 | 24,379 | -68 | -0.28% |
| **Total** | | | | **326,196** | **325,281** | **-915** | **-0.28%** |

- Cash: 673,676 KRW
- Total equity: 998,957 KRW (from 1,000,000 starting)
- Portfolio drawdown: -0.10%

## 6. Today's Filled Orders

1. `04:34` **kimchi_premium_wallet** BUY KRW-BTC @ 103,537,743 qty=0.00220 (kimchi_premium_safe_zone_rsi_entry)
2. `06:21` **vbreak_eth_wallet** BUY KRW-ETH @ 3,133,566 qty=0.11973 (volatility_breakout)

## 7. Key Observations

1. **Correlation guard**: No correlation guard blocks observed — the dedup fix (88ffa7f) is working correctly
2. **Kimchi premium** is the most active strategy with 53 buy fills across all symbols
3. **Volatility breakout** has generated 3 total entries (2 ETH, 1 BTC) — 1 BTC round-trip completed
4. **Volume spike** just came online — needs market volume spike to trigger (sideways market currently)
5. **Consensus** evaluating but no agreement reached yet (0/1 threshold with weighted voting)
6. **Market regime**: Sideways across all symbols — low signal generation expected

## 8. Changes Made

1. `src/crypto_trader/config.py`: Added `volume_spike` to `valid_strategies` set
2. `src/crypto_trader/config.py`: Added `volume_spike` override keys to `_STRATEGY_EXTRA_OVERRIDE_FIELDS`
3. `src/crypto_trader/config.py`: Added `weights` to `consensus` override keys
4. `scripts/restart_daemon.sh`: Fixed to use venv python and set PYTHONPATH
