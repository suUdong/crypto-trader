# Session Handoff

Date: 2026-03-26 (FIRE Session #7)
Branch: `master`

## What Landed This Session (#7) — 4 User Stories

### Wave 1: Profitability & Signal Quality (US-023 to US-026)
- **US-023**: Adaptive RSI ceiling — strong momentum widens RSI ceiling from 60 toward 80, fixing the RSI conflict that blocked valid entries
- **US-024**: Partial take-profit (scale-out) — sells 50% of position at half the TP target, lets remainder ride to full TP or trailing stop
- **US-025**: Widened mean reversion Bollinger (1.8→1.5 stddev default) + RSI confirmation filter (oversold_floor+10) to avoid false bottoms
- **US-026**: ADX trend strength filter — blocks momentum & volatility breakout entries when ADX < 20 (choppy/trendless market)

## Previous Session Deliverables (Still Active)

### Session #6: Risk & Backtest Tooling (13 stories)
- Drawdown sizing, regime-aware grid search, equity curve export
- Adaptive confidence, profit factor scoring, consecutive loss kill switch
- Grid-WF JSON export, snapshot CLI, signal correlation, apply-params CLI

### Session #5: Grid-WF + Consensus + Daemon Expansion
- `grid-wf` CLI, `ConsensusStrategy`, 3 new daemon wallets (9 total)

### Session #4: Walk-Forward CLI + PnL History
- `walk-forward` CLI, `pnl-history`, `PnLSnapshotStore`

### Session #3: Per-Strategy PnL Tracking
- Per-wallet PnL breakdown, `--hours` time-range filtering

### Session #2: Per-Symbol Wallets
- BTC (2.51) + ETH (4.86) momentum, Kimchi (1.22), VPIN: BTC (3.40), ETH (2.05), SOL (2.55)

## Architecture Updates

```
src/crypto_trader/
  config.py             # + adx_period, adx_threshold in StrategyConfig
                        # + partial_tp_pct in RiskConfig
                        # bollinger_stddev default 1.8→1.5
  strategy/
    momentum.py         # + adaptive RSI ceiling, + ADX trend filter
    volatility_breakout.py  # + ADX trend filter
    mean_reversion.py   # + RSI confirmation filter (oversold_floor+10)
    indicators.py       # + average_directional_index() ADX indicator
  risk/
    manager.py          # + partial_take_profit exit reason
  wallet.py             # + partial TP sell logic (50% of position)
  models.py             # + partial_tp_taken field on Position

tests/
  test_adaptive_rsi_ceiling.py    # 4 tests
  test_partial_take_profit.py     # 5 tests
  test_adx_indicator.py           # 8 tests
  test_mean_reversion_rsi_filter.py # 4 tests
```

## Validation State

- `pytest tests/ -q` → **560 passed, 3 skipped, 0 failures**
- +21 new tests this session

## Daemon 72-Hour Performance (2026-03-26)

| Wallet | Strategy | Equity | Realized PnL | Unrealized | Trades | Status |
|--------|----------|--------|-------------|------------|--------|--------|
| momentum_btc_wallet | momentum | 1,000,000 | 0 | 0 | 0 | Waiting for signal |
| momentum_eth_wallet | momentum | 1,000,000 | 0 | 0 | 0 | Waiting for signal |
| kimchi_premium_wallet | kimchi_premium | 999,590 | 0 | -410 | 0 closed | BTC position open |
| vpin_btc_wallet | vpin | 1,000,000 | 0 | 0 | 0 | Needs daemon restart |
| vpin_eth_wallet | vpin | 1,000,000 | 0 | 0 | 0 | Needs daemon restart |
| vpin_sol_wallet | vpin | 1,000,000 | 0 | 0 | 0 | Needs daemon restart |
| vbreak_btc_wallet | volatility_breakout | — | — | — | — | Not yet deployed |
| vbreak_eth_wallet | volatility_breakout | — | — | — | — | Not yet deployed |
| consensus_btc_wallet | consensus | — | — | — | — | Not yet deployed |

## Current Gaps / Risks

1. **3 new wallets not deployed** — daemon restart needed
2. **No closed trades yet** — strategies waiting for entry signals in sideways market
3. ~~Momentum RSI conflict~~ **FIXED** — adaptive RSI ceiling now widens for strong momentum
4. Kimchi premium uses simulated premium — live may diverge
5. Telegram not live-verified (no bot token)
6. **ADX filter may reduce signal frequency** — monitor after deployment, tune adx_threshold if needed

## Recommended Next Moves

1. **Restart daemon** — deploy all 9 wallets with updated config (includes new filters)
2. **Run regime-aware grid-wf** — `crypto-trader grid-wf --strategy momentum --days 90 --regime sideways`
3. **Apply optimized params** — `crypto-trader apply-params --strategy momentum`
4. **Check correlation** — `crypto-trader correlation` to verify diversification
5. **Run consensus grid-wf** — `crypto-trader grid-wf --strategy consensus --days 90`
6. **Automate snapshots** — cron `crypto-trader snapshot` every 6h
7. **Monitor paper trading** 7 days → micro-live gate by Apr 2
8. **Telegram bot setup** for daily PnL alerts
9. **Tune ADX threshold** — if too few signals, lower from 20 to 15
10. **Tune partial TP ratio** — experiment with 0.3-0.7 range via grid-wf
