# Operator Report — 2026-03-27 07:47 KST

## Daemon Status
- **PID**: 480576 | **Status**: active (running) since 07:47:44 KST
- **Restart**: clean restart after watchdog timeout (restart counter 5)
- **Config**: `config/daemon.toml` | paper_trading=true
- **Symbols**: KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL
- **Wallets**: 11 (momentum x2, kimchi_premium, vpin x3, vbreak x2, consensus, ema_cross, mean_rev)
- **Poll**: 60s | **Checkpoint restore**: 4 positions across 11 wallets

## Code Changes Applied (cdcdc8d)
- **Unified symbol kwarg**: all 9 strategy `evaluate()` signatures accept `symbol: str = ""`
- **Call sites fixed**: pipeline.py, wallet.py, backtest/engine.py (x2), correlation.py
- **StrategyProtocol updated**: wallet.py + backtest/engine.py now include `symbol` in Protocol
- **Removed**: isinstance check for KimchiPremiumStrategy in wallet.py (was the only special-case)

## Open Positions (kimchi_premium_wallet)
| Symbol  | Entry Price    | Quantity     | Market Price  |
|---------|---------------|-------------|---------------|
| KRW-BTC | 104,067,007.50 | 0.00240350 | 104,000,000   |
| KRW-ETH | 3,120,559.50   | 0.00841335 | 3,119,000     |
| KRW-XRP | 2,060.03       | 12.29814739 | 2,058         |
| KRW-SOL | 131,265.60     | 0.18624034 | 131,200       |

**Capital deployed**: ~326K of 1M (32.6%) | **Cash**: 673,676
**Market regime**: sideways | **Realized PnL**: 0

## Strategy Signal Summary (post-restart)
| Wallet | Symbols | Signal | Notes |
|--------|---------|--------|-------|
| kimchi_premium | BTC/ETH/XRP/SOL | hold (position_open_waiting) | 4 positions held |
| momentum_btc/eth | BTC/ETH | -- | Blocked by correlation guard |
| vpin_btc/eth/sol | BTC/ETH/SOL | -- | Blocked by correlation guard |
| vbreak_btc/eth | BTC/ETH | -- | Blocked by correlation guard |
| consensus_btc | BTC | -- | Blocked by correlation guard |
| ema_cross_btc | BTC | -- | Blocked by correlation guard |
| mean_rev_eth | ETH | -- | Blocked by correlation guard |

**Correlation guard**: actively preventing cluster over-exposure (normal behavior).

## Risk Controls Active
- **Tiered kill switch**: loaded (from deef3d7)
- **Max position cap**: enforced per-wallet
- **Slippage monitor**: active
- **Circuit breaker**: daily loss limit configured at 5%
- **Cooldown**: per-symbol, 4h for kimchi_premium

## Telegram Alerts
- **Status**: NOT configured (bot_token/chat_id empty in daemon.toml)
- **Impact**: none for paper trading -- alerts only needed for live trading

## Health
- No errors in logs since restart
- All wallets evaluating normally
- Structured logging + strategy run journal active
