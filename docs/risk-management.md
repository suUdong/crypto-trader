# Risk Management Framework

> Last updated: 2026-03-29 | 3-wallet diversified portfolio (₩5.7M)

## Overview

The crypto-trader risk management system operates in **6 layered defenses**, from hard-coded
safety constants down to per-trade adaptive sizing. Each layer is independent — if one fails,
the next catches the breach.

```
Layer 1: Hard Safety Constants (config.py)          ← cannot be overridden
Layer 2: Per-Wallet Risk Config (daemon.toml)       ← operator-tunable
Layer 3: Kill Switch (tiered: warn → reduce → halt) ← portfolio-wide circuit breaker
Layer 4: Correlation Guard                          ← cross-wallet exposure limiter
Layer 5: Wallet Health Monitor                      ← auto-disable persistent losers
Layer 6: RiskManager Adaptive Controls              ← per-trade dynamic sizing
```

## Layer 1: Hard Safety Constants

These are compile-time constants in `src/crypto_trader/config.py` that **cannot be exceeded
by any configuration**. Changing these requires explicit user approval.

| Constant | Value | Purpose |
|---|---|---|
| `HARD_MAX_DAILY_LOSS_PCT` | 5% | Absolute daily loss ceiling |
| `SAFE_MAX_CONSECUTIVE_LOSSES` | 3 | Auto-stop after 3 consecutive losses |
| `SAFE_DEFAULT_MAX_POSITION_PCT` | 10% | No single position > 10% of wallet capital |

## Layer 2: Per-Wallet Risk Configuration

Each wallet has independent risk parameters via `risk_overrides` in `daemon.toml`.

### Current Active Wallets (2026-03-29)

| Wallet | Capital | Weight | Stop Loss | Take Profit | Risk/Trade | Max Positions |
|---|---|---|---|---|---|---|
| vpin_eth | ₩3,500,000 | 61.4% | 1.2% | 4% | 1% | 3 |
| momentum_sol | ₩1,200,000 | 21.1% | 3% | 8% | 1.5% | 2 |
| volspike_btc | ₩1,000,000 | 17.5% | 3% | 6% | 1% | 3 |

### Key Risk Parameters

- **`risk_per_trade_pct`**: Capital risked per trade (Kelly sizing overrides when sufficient history)
- **`stop_loss_pct`**: Fixed stop loss distance (tightened 20% after 3+ consecutive losses)
- **`max_position_pct`**: Hard cap at 10% of wallet capital per position
- **`max_concurrent_positions`**: Per-wallet position limit
- **`atr_stop_multiplier`**: ATR-based dynamic stop (1.5× ATR for all wallets)
- **`cooldown_bars`**: Minimum bars between trades after a loss (3-4 bars)

## Layer 3: Kill Switch

Portfolio-wide circuit breaker with **tiered response** before full halt.

### Configuration

| Parameter | Value | Description |
|---|---|---|
| `max_portfolio_drawdown_pct` | 8% | Maximum peak-to-trough drawdown |
| `max_daily_loss_pct` | 3% | Maximum single-day loss |
| `max_consecutive_losses` | 3 | Consecutive losses before halt |
| `max_strategy_drawdown_pct` | 6% | Per-strategy drawdown limit |
| `cooldown_minutes` | 120 | Cooldown after trigger |

### Tiered Response

The kill switch does not simply flip on/off. It applies **graduated pressure**:

| Stage | Trigger | Action |
|---|---|---|
| **Normal** | drawdown < 50% of limit | Full position sizing |
| **Warning** | drawdown 50-75% of limit | Position size linearly reduced |
| **Reduce** | drawdown 75-100% of limit | Position size halved (50%) |
| **Halt** | drawdown >= limit | All new entries blocked, force-close triggered |

Example: With 8% MDD limit, warning starts at 4% drawdown, position reduction at 6%,
full halt at 8%.

## Layer 4: Correlation Guard

Prevents over-exposure to correlated assets across the multi-wallet portfolio.

### Configuration

| Parameter | Value | Description |
|---|---|---|
| `max_cluster_exposure` | **2** | Max wallets with open positions in same cluster |
| `max_correlation` | 0.85 | Pearson correlation threshold for blocking |
| `max_high_correlation_exposure` | 2 | Max wallets in highly-correlated assets |
| Lookback | 24 bars | Correlation calculation window |

### Crypto Cluster

All three traded assets (BTC, ETH, SOL) are in the `major_crypto` cluster.
With `max_cluster_exposure=2`, **at most 2 out of 3 wallets can hold positions
simultaneously**. This is the primary defense against correlated crash scenarios.

### Why max_cluster_exposure = 2

BTC/ETH/SOL correlations during market stress converge toward 1.0. If all 3 wallets
enter simultaneously and a 15% flash crash occurs:

| Scenario | Max Exposure | Portfolio Loss |
|---|---|---|
| 3 wallets, max positions (old limit=6) | ₩1,590,000 (28%) | **4.18%** (exceeds 3% daily limit) |
| 2 wallets, max positions (new limit=2) | ₩1,050,000 (18%) | **2.76%** (within 3% daily limit) |
| 1 wallet only | ₩350,000 (6%) | **0.92%** (comfortable) |

The limit of 2 keeps worst-case crash losses under the 3% daily kill switch threshold.

## Layer 5: Wallet Health Monitor

Automatically disables wallets with persistent losses.

| Parameter | Value |
|---|---|
| `negative_days_threshold` | 7 consecutive negative days |
| `check_interval_hours` | 24 hours |
| Auto re-enable | When returns turn positive |

## Layer 6: RiskManager Adaptive Controls

Per-trade dynamic risk adjustments within each wallet.

### Position Sizing

1. **Kelly Criterion**: Half-Kelly sizing when 10+ trades of history exist (capped at 25%)
2. **Drawdown Scaling**: Position size shrinks as equity approaches daily loss limit
3. **Streak Multiplier**: +4% per consecutive win (cap 1.2×), -15% per consecutive loss (floor 0.4×)
4. **Macro Multiplier**: External macro regime adjusts sizing (bull/sideways/bear)
5. **Edge Schedule**: Time-of-day edge multipliers

### Exit Controls

| Exit Type | Trigger |
|---|---|
| Stop Loss | Fixed % or ATR-based (tightened 20% on loss streak) |
| Take Profit | Fixed % or ATR-based (2:1 reward:risk) |
| Partial TP | 50% position closed at halfway to TP target |
| Trailing Stop | Activates after partial TP (2%) or 3%+ gain (1.5%) |
| Breakeven Stop | Locks entry price after 1.2%+ watermark gain |
| Time Decay | Forced exit at 60% of max bars if loss > 1.5%, 75% if any loss |
| Profit Lock | 1.5% trailing from watermark after 3%+ unrealized gain |

### Auto-Pause

- **Loss streak stop**: After 3 consecutive losses (matches kill switch)
- **Profit factor pause**: When PF < 0.7 over last 20 trades (resumes at PF > 0.8)
- **Decay detection**: Rolling win rate < 35% flags strategy as losing edge
- **Cooldown**: 3-4 bars of no-entry after each losing trade

## Maximum Exposure Analysis

### Single Round of Stops (All Wallets)

| Wallet | Position (10% cap) | Stop Loss | Max Loss |
|---|---|---|---|
| vpin_eth | ₩350,000 | 1.2% | ₩4,200 |
| momentum_sol | ₩120,000 | 3.0% | ₩3,600 |
| volspike_btc | ₩100,000 | 3.0% | ₩3,000 |
| **Total** | **₩570,000** | | **₩10,800 (0.19%)** |

### Worst Case: Max Concurrent Positions (with correlation guard limit=2)

With `max_cluster_exposure=2`, only 2 wallets can hold positions simultaneously:

- Max 2 wallets × up to 3 positions each = 6 positions
- Max exposure: ₩1,050,000 (18.4% of portfolio)
- 15% crash scenario: ₩157,500 loss (2.76% of portfolio)
- **Within 3% daily kill switch limit**

### Defense-in-Depth Cascade

```
Trade goes wrong:
  → Stop loss fires (1.2-3% per position)          ← Layer 2
  → Streak multiplier reduces next position size    ← Layer 6
  → Cooldown prevents immediate re-entry            ← Layer 6
  → After 3 losses: auto-stop                       ← Layer 1 + Layer 3
  → Daily loss approaching limit: position size halved ← Layer 3
  → Daily loss hits 3%: all entries blocked          ← Layer 3
  → Portfolio drawdown 8%: full halt                 ← Layer 3

Market crash (all assets):
  → Correlation guard: max 2 wallets exposed         ← Layer 4
  → Kill switch tiered response reduces exposure     ← Layer 3
  → Force-close at daily limit                       ← Layer 3
  → 7-day persistent loser: wallet auto-disabled     ← Layer 5
```

## Tail Risk: Gap-Down / Flash Crash

Stop-loss orders are **limit orders on Upbit**, not guaranteed fills. In a flash crash:

- Prices can gap past stop levels
- Actual loss may exceed configured stop_loss_pct
- **Mitigation**: The 10% max position cap limits worst-case single-position loss
- **Mitigation**: Correlation guard limits simultaneous exposure to 2 wallets
- **Mitigation**: Kill switch monitors actual equity, not just stop levels

## Configuration Change Protocol

1. Any change to hard safety constants requires explicit user approval
2. Risk parameter changes must be backtested before deploying to daemon.toml
3. Kill switch parameters should be reviewed when adding/removing wallets
4. Correlation guard limits should scale with wallet count (rule of thumb: N-1 for N wallets)
