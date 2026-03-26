# Session Handoff

Date: 2026-03-26 (FIRE Session #3)
Branch: `master`

## What Landed This Session

### Per-Strategy Realized PnL Tracking
- `TradeRecord` now has `wallet` field — every closed trade tracks which wallet generated it
- `PaperTradeJournal.append_many()` accepts `wallet_name` parameter
- `MultiSymbolRuntime._persist_journal()` passes wallet name to journal
- Fake test data purged from `paper-trades.jsonl` (archived to `paper-trades-fake-data-archived.jsonl`)

### Enhanced PnL Report
- **Per-wallet breakdown** replaces flat strategy list — each wallet row shows strategy, return%, equity, PnL, trades, win%, PF, Sharpe
- **Time-range filtering** via `--hours` CLI flag — e.g. `pnl-report --hours 72` for 3-day report
- **Flexible Sharpe calculation** — handles hour-based periods (`72h`, `24h`) for proper annualization
- JSON output includes `wallet` field per strategy entry

### Per-Symbol Momentum Wallets (Session #2)
- Split momentum into `momentum_btc_wallet` (Sharpe 2.51) and `momentum_eth_wallet` (Sharpe 4.86)
- BTC: lookback=20, threshold=0.005, SL=4%, TP=8%, risk=0.5%
- ETH: lookback=15, threshold=0.005, SL=2%, TP=4%, risk=1.5%, ATR=3.0
- Kimchi premium wallet with grid-search overrides (Sharpe 1.22)
- 5 negative-Sharpe strategies excluded

## Daemon 72-Hour Performance (2026-03-26)

| Wallet | Strategy | Equity | Realized PnL | Unrealized | Trades | Status |
|--------|----------|--------|-------------|------------|--------|--------|
| momentum_btc_wallet | momentum | 1,000,000 | 0 | 0 | 0 | Waiting for signal |
| momentum_eth_wallet | momentum | 1,000,000 | 0 | 0 | 0 | Waiting for signal |
| kimchi_premium_wallet | kimchi_premium | 999,590 | 0 | -410 | 0 closed | BTC position open |
| **Total** | | **2,999,590** | **0** | **-410** | **0** | |

- Daemon restarted at 14:29 KST with optimized 3-wallet config
- Kimchi bought BTC at ~105,721 KRW (safe_zone_rsi_entry), position open waiting
- Momentum wallets holding — sideways market, entry conditions not met (expected)
- No kill switch triggers, healthcheck green

## Architecture Updates

```
src/crypto_trader/
  models.py             # + TradeRecord.wallet field (default="")
  operator/
    paper_trading.py    # + PaperTradeJournal.append_many(wallet_name=) param
    pnl_report.py       # + StrategyPnLMetrics.wallet field
                        # + hours param for time-range filtering
                        # + Per-wallet markdown output
                        # + Hour-based Sharpe calculation
  multi_runtime.py      # + wallet name passed to journal on persist
  cli.py                # + --hours flag for pnl-report command
```

## Validation State

- `pytest tests/ -q` → 458 passed, 3 skipped
- PnL report generates correctly with `--hours 72`
- Daemon running with 3-wallet config, logs clean

## Current Gaps / Risks

1. Kimchi premium backtest uses simulated premium — live may diverge
2. Sideways market → momentum signals rare (expected, backtest agrees)
3. No closed trades yet — need time for first full trade cycle
4. Telegram notifications not live-verified (no bot token)
5. Paper trading restarted — need 7 days for micro-live gate

## Recommended Next Moves

1. **Monitor paper trading** for 7 days → micro-live gate by Apr 2
2. **Add walk-forward for kimchi_premium** (currently grid-search only)
3. **Per-symbol momentum tuning** — BTC and ETH may benefit from different params
4. **Add composite strategy** with higher-confidence filter (Sharpe 1.16 but only 2 trades)
5. **Telegram bot setup** for daily PnL alerts
6. **Historical PnL aggregation** — accumulate daily snapshots for multi-day trending
