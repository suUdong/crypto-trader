#!/usr/bin/env python3
"""c201: Regime-Adaptive Capital Reallocation Portfolio Simulation.

Compares two portfolio allocation modes across 2022-2026:
  A) STATIC: current daemon.toml fixed allocation (BULL wallets idle in BEAR)
  B) DYNAMIC: BEAR -> transfer idle capital to rsi_mr_bear + vpin_eth boost,
              BULL -> restore original allocation

Strategies simulated:
  - vpin_eth (all regimes) — c168 params
  - momentum_sol (BULL only) — c74 params
  - volspike_btc (BULL only) — daemon params
  - rsi_mr_bear_eth (BEAR only) — c187 params
  - rsi_mr_bear_btc (BEAR only) — c187 params

Capital allocation:
  STATIC:
    vpin_eth=2.0M, momentum_sol=1.2M, volspike_btc=1.0M,
    rsi_mr_bear_eth=0.5M, rsi_mr_bear_btc=0.5M
    Total: 5.2M (BULL wallets idle in BEAR = 2.2M wasted)

  DYNAMIC (BEAR mode):
    vpin_eth=2.0M+1.0M=3.0M (boost from volspike_btc)
    rsi_mr_bear_eth=0.5M+0.6M=1.1M (boost from momentum_sol)
    rsi_mr_bear_btc=0.5M+0.6M=1.1M (boost from momentum_sol)
    momentum_sol=0, volspike_btc=0 (idle, capital transferred)
    Total: 5.2M (all capital active)

  DYNAMIC (BULL mode): same as STATIC

Regime detection: BTC close vs SMA(200) on 240m candles.
Transition cost: 0.2% slippage on transferred capital amount.

Walk-forward: 3-fold expanding window.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical  # noqa: E402


def sma(series: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    out = np.full_like(series, np.nan)
    for i in range(period - 1, len(series)):
        out[i] = np.mean(series[i - period + 1 : i + 1])
    return out


def rsi_calc(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI calculation."""
    out = np.full_like(closes, np.nan, dtype=float)
    deltas = np.diff(closes)
    if len(deltas) < period:
        return out
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def atr_calc(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """ATR calculation."""
    out = np.full_like(closes, np.nan, dtype=float)
    tr = np.zeros(len(closes))
    for i in range(1, len(closes)):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    for i in range(period, len(closes)):
        out[i] = np.mean(tr[i - period + 1 : i + 1])
    return out


# ---------------------------------------------------------------------------
# Strategy simulators (simplified — next-bar open entry, slippage included)
# ---------------------------------------------------------------------------
SLIPPAGE = 0.002  # 0.2% round-trip (0.1% each way)
FEE_RATE = 0.0005


@dataclass
class Trade:
    entry_bar: int
    entry_price: float
    exit_bar: int = -1
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ""


@dataclass
class StrategyResult:
    name: str
    trades: list[Trade] = field(default_factory=list)
    equity_curve: np.ndarray = field(default_factory=lambda: np.array([]))


def sim_vpin_eth(df: pd.DataFrame, btc_df: pd.DataFrame) -> list[Trade]:
    """Simplified VPIN ETH strategy — uses c168 params.
    VPIN threshold=0.35, momentum_threshold=0.0005, hold<=36,
    ATR TP/SL, trailing stop.
    Simplified: RSI-momentum entry proxy + ATR-based exits.
    """
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values
    n = len(closes)
    rsi_vals = rsi_calc(closes, 14)
    atr_vals = atr_calc(highs, lows, closes, 14)

    # Momentum proxy: 8-bar return
    mom = np.full(n, np.nan)
    for i in range(8, n):
        mom[i] = (closes[i] - closes[i - 8]) / closes[i - 8]

    trades: list[Trade] = []
    pos = None
    cooldown = 0

    for i in range(201, n - 1):
        if np.isnan(rsi_vals[i]) or np.isnan(atr_vals[i]) or np.isnan(mom[i]):
            continue

        if pos is not None:
            # Exit logic
            holding = i - pos.entry_bar
            entry_p = pos.entry_price
            unrealised = (closes[i] - entry_p) / entry_p
            atr_tp = atr_vals[i] * 3.0 / entry_p
            atr_sl = atr_vals[i] * 0.5 / entry_p

            exit_reason = ""
            if unrealised <= -atr_sl:
                exit_reason = "atr_sl"
            elif unrealised >= atr_tp:
                exit_reason = "atr_tp"
            elif holding >= 36:
                exit_reason = "max_hold"
            elif rsi_vals[i] > 75:
                exit_reason = "rsi_overbought"

            if exit_reason:
                # Exit at next bar open
                exit_price = df["open"].values[i + 1] * (1 - SLIPPAGE / 2)
                pnl = (exit_price - entry_p) / entry_p - FEE_RATE * 2
                pos.exit_bar = i + 1
                pos.exit_price = exit_price
                pos.pnl_pct = pnl
                pos.reason = exit_reason
                trades.append(pos)
                pos = None
                cooldown = 4
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        # Entry: momentum > 0.0005, RSI < 65, RSI > 20
        if mom[i] > 0.0005 and 20 < rsi_vals[i] < 65:
            entry_price = df["open"].values[i + 1] * (1 + SLIPPAGE / 2)
            pos = Trade(entry_bar=i + 1, entry_price=entry_price)

    return trades


def sim_momentum_sol(df: pd.DataFrame, btc_df: pd.DataFrame) -> list[Trade]:
    """Simplified momentum SOL — c74 params. BULL only (BTC > SMA200)."""
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    btc_closes = btc_df["close"].values
    btc_sma200 = sma(btc_closes, 200)
    n = len(closes)
    rsi_vals = rsi_calc(closes, 14)

    # 12-bar momentum
    mom = np.full(n, np.nan)
    for i in range(12, n):
        mom[i] = (closes[i] - closes[i - 12]) / closes[i - 12]

    trades: list[Trade] = []
    pos = None
    cooldown = 0

    for i in range(201, n - 1):
        if np.isnan(rsi_vals[i]) or np.isnan(mom[i]):
            continue
        if i >= len(btc_closes) or np.isnan(btc_sma200[i]):
            continue

        # BULL regime gate
        is_bull = btc_closes[i] > btc_sma200[i]

        if pos is not None:
            holding = i - pos.entry_bar
            entry_p = pos.entry_price
            unrealised = (closes[i] - entry_p) / entry_p

            exit_reason = ""
            if unrealised <= -0.04:
                exit_reason = "sl"
            elif unrealised >= 0.12:
                exit_reason = "tp"
            elif holding >= 48:
                exit_reason = "max_hold"
            elif rsi_vals[i] > 75:
                exit_reason = "rsi_ob"

            if exit_reason:
                exit_price = df["open"].values[i + 1] * (1 - SLIPPAGE / 2)
                pnl = (exit_price - entry_p) / entry_p - FEE_RATE * 2
                pos.exit_bar = i + 1
                pos.exit_price = exit_price
                pos.pnl_pct = pnl
                pos.reason = exit_reason
                trades.append(pos)
                pos = None
                cooldown = 3
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        # Entry: BULL + momentum > 0.005 + RSI < 75
        if is_bull and mom[i] > 0.005 and rsi_vals[i] < 75:
            entry_price = df["open"].values[i + 1] * (1 + SLIPPAGE / 2)
            pos = Trade(entry_bar=i + 1, entry_price=entry_price)

    return trades


def sim_volspike_btc(df: pd.DataFrame, btc_df: pd.DataFrame) -> list[Trade]:
    """Simplified volume spike BTC. BULL only."""
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values
    btc_closes = btc_df["close"].values
    btc_sma200 = sma(btc_closes, 200)
    n = len(closes)
    rsi_vals = rsi_calc(closes, 14)

    # Volume SMA(20)
    vol_sma = sma(volumes.astype(float), 20)

    trades: list[Trade] = []
    pos = None
    cooldown = 0

    for i in range(201, n - 1):
        if np.isnan(rsi_vals[i]) or np.isnan(vol_sma[i]):
            continue
        if i >= len(btc_closes) or np.isnan(btc_sma200[i]):
            continue

        is_bull = btc_closes[i] > btc_sma200[i]

        if pos is not None:
            holding = i - pos.entry_bar
            entry_p = pos.entry_price
            unrealised = (closes[i] - entry_p) / entry_p

            exit_reason = ""
            if unrealised <= -0.02:
                exit_reason = "sl"
            elif unrealised >= 0.06:
                exit_reason = "tp"
            elif holding >= 36:
                exit_reason = "max_hold"

            if exit_reason:
                exit_price = df["open"].values[i + 1] * (1 - SLIPPAGE / 2)
                pnl = (exit_price - entry_p) / entry_p - FEE_RATE * 2
                pos.exit_bar = i + 1
                pos.exit_price = exit_price
                pos.pnl_pct = pnl
                pos.reason = exit_reason
                trades.append(pos)
                pos = None
                cooldown = 3
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        # Entry: BULL + volume > 2x SMA(20) + body ratio > 0.2
        body_ratio = abs(closes[i] - df["open"].values[i]) / max(highs[i] - lows[i], 1e-10)
        if is_bull and volumes[i] > 2.0 * vol_sma[i] and body_ratio > 0.2 and rsi_vals[i] < 72:
            entry_price = df["open"].values[i + 1] * (1 + SLIPPAGE / 2)
            pos = Trade(entry_bar=i + 1, entry_price=entry_price)

    return trades


def sim_rsi_mr_bear(df: pd.DataFrame, btc_df: pd.DataFrame,
                     rsi_entry: float = 25.0, rsi_exit: float = 50.0,
                     sl_pct: float = 0.02, max_hold: int = 24) -> list[Trade]:
    """RSI Mean-Reversion BEAR — c187 params. BEAR only (BTC < SMA200)."""
    closes = df["close"].values
    btc_closes = btc_df["close"].values
    btc_sma200 = sma(btc_closes, 200)
    n = len(closes)
    rsi_vals = rsi_calc(closes, 14)

    trades: list[Trade] = []
    pos = None
    cooldown = 0

    for i in range(201, n - 1):
        if np.isnan(rsi_vals[i]) or np.isnan(btc_sma200[i]):
            continue

        is_bear = btc_closes[i] < btc_sma200[i]

        if pos is not None:
            holding = i - pos.entry_bar
            entry_p = pos.entry_price
            unrealised = (closes[i] - entry_p) / entry_p

            exit_reason = ""
            if unrealised <= -sl_pct:
                exit_reason = "sl"
            elif rsi_vals[i] > rsi_exit:
                exit_reason = "rsi_reversion"
            elif holding >= max_hold:
                exit_reason = "max_hold"

            if exit_reason:
                exit_price = df["open"].values[i + 1] * (1 - SLIPPAGE / 2)
                pnl = (exit_price - entry_p) / entry_p - FEE_RATE * 2
                pos.exit_bar = i + 1
                pos.exit_price = exit_price
                pos.pnl_pct = pnl
                pos.reason = exit_reason
                trades.append(pos)
                pos = None
                cooldown = 4
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        # Entry: BEAR + RSI < rsi_entry
        if is_bear and rsi_vals[i] < rsi_entry:
            entry_price = df["open"].values[i + 1] * (1 + SLIPPAGE / 2)
            pos = Trade(entry_bar=i + 1, entry_price=entry_price)

    return trades


# ---------------------------------------------------------------------------
# Portfolio simulation
# ---------------------------------------------------------------------------
@dataclass
class PortfolioConfig:
    """Capital allocation for one mode."""
    vpin_eth: float
    momentum_sol: float
    volspike_btc: float
    rsi_mr_bear_eth: float
    rsi_mr_bear_btc: float


STATIC_BULL = PortfolioConfig(
    vpin_eth=2_000_000, momentum_sol=1_200_000, volspike_btc=1_000_000,
    rsi_mr_bear_eth=500_000, rsi_mr_bear_btc=500_000,
)
# In static mode, BEAR wallets still get their allocation but BULL wallets sit idle
STATIC_BEAR = STATIC_BULL  # same allocation, BULL wallets just don't trade

DYNAMIC_BULL = PortfolioConfig(
    vpin_eth=2_000_000, momentum_sol=1_200_000, volspike_btc=1_000_000,
    rsi_mr_bear_eth=500_000, rsi_mr_bear_btc=500_000,
)
DYNAMIC_BEAR = PortfolioConfig(
    vpin_eth=3_000_000,      # +1.0M from volspike_btc
    momentum_sol=0,           # idle, capital transferred
    volspike_btc=0,           # idle, capital transferred
    rsi_mr_bear_eth=1_100_000,  # +0.6M from momentum_sol
    rsi_mr_bear_btc=1_100_000,  # +0.6M from momentum_sol
)

TRANSITION_COST_PCT = 0.002  # 0.2% slippage on transferred capital


def build_equity_curve(
    trades: list[Trade],
    capital: float,
    n_bars: int,
    active_mask: np.ndarray,  # boolean: True when this strategy is active
) -> np.ndarray:
    """Build per-bar equity curve from trades + active mask."""
    equity = np.full(n_bars, capital)
    current_equity = capital

    for t in trades:
        if t.exit_bar < 0:
            continue
        # Only count trade if entry bar was in active period
        if not active_mask[t.entry_bar]:
            continue
        # PnL scaled by position (use full allocation for simplicity)
        trade_pnl = current_equity * t.pnl_pct
        for j in range(t.exit_bar, n_bars):
            equity[j] += trade_pnl
        current_equity += trade_pnl

    return equity


def portfolio_simulation(
    eth_df: pd.DataFrame,
    sol_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    fold_start: int,
    fold_end: int,
    mode: str,  # "static" or "dynamic"
) -> dict:
    """Run portfolio simulation for one fold."""
    n = fold_end - fold_start
    btc_closes = btc_df["close"].values
    btc_sma200 = sma(btc_closes, 200)

    # Regime mask for the fold
    is_bull = np.array([
        btc_closes[i] > btc_sma200[i] if not np.isnan(btc_sma200[i]) else True
        for i in range(fold_start, fold_end)
    ])
    is_bear = ~is_bull

    bull_pct = np.sum(is_bull) / len(is_bull) * 100
    bear_pct = np.sum(is_bear) / len(is_bear) * 100

    # Slice data for fold
    eth_fold = eth_df.iloc[fold_start:fold_end].reset_index(drop=True)
    sol_fold = sol_df.iloc[fold_start:fold_end].reset_index(drop=True)
    btc_fold = btc_df.iloc[fold_start:fold_end].reset_index(drop=True)

    # Run strategies on fold
    vpin_eth_trades = sim_vpin_eth(eth_fold, btc_fold)
    momentum_sol_trades = sim_momentum_sol(sol_fold, btc_fold)
    volspike_btc_trades = sim_volspike_btc(btc_fold, btc_fold)
    rsi_mr_eth_trades = sim_rsi_mr_bear(eth_fold, btc_fold)
    rsi_mr_btc_trades = sim_rsi_mr_bear(btc_fold, btc_fold)

    # Count regime transitions
    transitions = 0
    for i in range(1, len(is_bull)):
        if is_bull[i] != is_bull[i - 1]:
            transitions += 1

    total_capital = 5_200_000.0

    # Helper: filter trades by regime
    def _filter_regime(trades: list[Trade], mask: np.ndarray) -> list[Trade]:
        return [t for t in trades if 0 <= t.entry_bar < len(mask) and mask[t.entry_bar]]

    # Filter trades by regime applicability
    vpin_all = [t for t in vpin_eth_trades if t.exit_bar >= 0]
    mom_bull = _filter_regime(momentum_sol_trades, is_bull)
    vol_bull = _filter_regime(volspike_btc_trades, is_bull)
    mr_eth_bear = _filter_regime(rsi_mr_eth_trades, is_bear)
    mr_btc_bear = _filter_regime(rsi_mr_btc_trades, is_bear)

    # Capital allocation per trade (KRW PnL per trade)
    trade_pnls_krw: list[float] = []

    if mode == "static":
        cap_vpin = STATIC_BULL.vpin_eth  # 2.0M always
        cap_mom = STATIC_BULL.momentum_sol  # 1.2M (idle in BEAR)
        cap_vol = STATIC_BULL.volspike_btc  # 1.0M (idle in BEAR)
        cap_mr_eth = STATIC_BULL.rsi_mr_bear_eth  # 0.5M
        cap_mr_btc = STATIC_BULL.rsi_mr_bear_btc  # 0.5M
        transition_cost_krw = 0.0

        for t in vpin_all:
            trade_pnls_krw.append(cap_vpin * t.pnl_pct)
        for t in mom_bull:
            trade_pnls_krw.append(cap_mom * t.pnl_pct)
        for t in vol_bull:
            trade_pnls_krw.append(cap_vol * t.pnl_pct)
        for t in mr_eth_bear:
            trade_pnls_krw.append(cap_mr_eth * t.pnl_pct)
        for t in mr_btc_bear:
            trade_pnls_krw.append(cap_mr_btc * t.pnl_pct)

    else:  # dynamic
        # VPIN: capital depends on regime at entry
        for t in vpin_all:
            if 0 <= t.entry_bar < len(is_bull) and is_bull[t.entry_bar]:
                trade_pnls_krw.append(DYNAMIC_BULL.vpin_eth * t.pnl_pct)
            else:
                trade_pnls_krw.append(DYNAMIC_BEAR.vpin_eth * t.pnl_pct)

        # Momentum/Volspike: same capital as static (BULL only, no change)
        for t in mom_bull:
            trade_pnls_krw.append(DYNAMIC_BULL.momentum_sol * t.pnl_pct)
        for t in vol_bull:
            trade_pnls_krw.append(DYNAMIC_BULL.volspike_btc * t.pnl_pct)

        # RSI MR BEAR: boosted capital
        for t in mr_eth_bear:
            trade_pnls_krw.append(DYNAMIC_BEAR.rsi_mr_bear_eth * t.pnl_pct)
        for t in mr_btc_bear:
            trade_pnls_krw.append(DYNAMIC_BEAR.rsi_mr_bear_btc * t.pnl_pct)

        # Transition costs
        transferred_capital = 2_200_000.0
        transition_cost_krw = transitions * transferred_capital * TRANSITION_COST_PCT

    total_trades = len(vpin_all) + len(mom_bull) + len(vol_bull) + len(mr_eth_bear) + len(mr_btc_bear)

    portfolio_pnl_krw = sum(trade_pnls_krw) - transition_cost_krw
    portfolio_return_pct = portfolio_pnl_krw / total_capital * 100

    # Sharpe from capital-weighted trade PnLs (normalized by total capital)
    if len(trade_pnls_krw) > 1:
        pnl_arr = np.array(trade_pnls_krw) / total_capital  # normalize
        sharpe = np.mean(pnl_arr) / np.std(pnl_arr, ddof=1) * np.sqrt(len(pnl_arr))
    else:
        sharpe = 0.0

    # Win rate
    wins = sum(1 for p in trade_pnls_krw if p > 0)
    wr = wins / max(1, len(trade_pnls_krw)) * 100

    # MDD from cumulative KRW PnL
    cum_pnl = np.cumsum(trade_pnls_krw) if trade_pnls_krw else np.array([0.0])
    peak = np.maximum.accumulate(cum_pnl)
    dd = cum_pnl - peak
    mdd = np.min(dd) / total_capital * 100 if len(dd) > 0 else 0.0

    return {
        "mode": mode,
        "sharpe": round(sharpe, 3),
        "return_pct": round(portfolio_return_pct, 2),
        "total_trades": total_trades,
        "win_rate": round(wr, 1),
        "mdd_pct": round(mdd, 2),
        "bull_pct": round(bull_pct, 1),
        "bear_pct": round(bear_pct, 1),
        "transitions": transitions,
        "transition_cost_krw": round(transition_cost_krw, 0),
        "portfolio_pnl_krw": round(portfolio_pnl_krw, 0),
        "strategy_detail": {
            "vpin_eth": len(vpin_all),
            "momentum_sol": len(mom_bull),
            "volspike_btc": len(vol_bull),
            "rsi_mr_bear_eth": len(mr_eth_bear),
            "rsi_mr_bear_btc": len(mr_btc_bear),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 80)
    print("  c201: Regime-Adaptive Capital Reallocation Portfolio Simulation")
    print("  Period: 2022-01 ~ 2026-04 | Candle: 240m | 3-fold expanding WF")
    print("  Slippage: 0.2% | Fee: 0.05% | Transition cost: 0.2% per switch")
    print("=" * 80)

    # Load data
    print("\n[1/3] Loading data...")
    try:
        eth_df = load_historical("KRW-ETH", "240m", "2022-01-01", "2026-04-05")
        sol_df = load_historical("KRW-SOL", "240m", "2022-01-01", "2026-04-05")
        btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    # Reset index to integer, ensure standard column names
    for df_name, df in [("eth", eth_df), ("sol", sol_df), ("btc", btc_df)]:
        df.reset_index(inplace=True)
        if "index" in df.columns:
            df.rename(columns={"index": "timestamp"}, inplace=True)

    print(f"  ETH: {len(eth_df)} bars | SOL: {len(sol_df)} bars | BTC: {len(btc_df)} bars")

    # Align lengths
    min_len = min(len(eth_df), len(sol_df), len(btc_df))
    eth_df = eth_df.iloc[:min_len].reset_index(drop=True)
    sol_df = sol_df.iloc[:min_len].reset_index(drop=True)
    btc_df = btc_df.iloc[:min_len].reset_index(drop=True)
    print(f"  Aligned: {min_len} bars")

    # 3-fold expanding window
    # F1: train [0, 40%), test [40%, 60%)
    # F2: train [0, 60%), test [60%, 80%)
    # F3: train [0, 80%), test [80%, 100%)
    folds = [
        (int(min_len * 0.4), int(min_len * 0.6)),
        (int(min_len * 0.6), int(min_len * 0.8)),
        (int(min_len * 0.8), min_len),
    ]

    print(f"\n[2/3] Running 3-fold walk-forward simulation...")

    all_results = []
    for fi, (fold_start, fold_end) in enumerate(folds, 1):
        try:
            ts_start = eth_df["timestamp"].iloc[fold_start]
            ts_end = eth_df["timestamp"].iloc[fold_end - 1]
        except Exception:
            ts_start, ts_end = f"bar_{fold_start}", f"bar_{fold_end}"
        print(f"\n  --- Fold {fi}: bars [{fold_start}, {fold_end}) = {ts_start} ~ {ts_end} ---")

        for mode in ["static", "dynamic"]:
            result = portfolio_simulation(eth_df, sol_df, btc_df, fold_start, fold_end, mode)
            result["fold"] = fi
            all_results.append(result)
            sd = result["strategy_detail"]
            print(f"  [{mode.upper():>7}] Sharpe={result['sharpe']:+.3f}  "
                  f"Ret={result['return_pct']:+.2f}%  n={result['total_trades']}  "
                  f"WR={result['win_rate']:.1f}%  MDD={result['mdd_pct']:.2f}%  "
                  f"BULL={result['bull_pct']:.0f}% BEAR={result['bear_pct']:.0f}%  "
                  f"transitions={result['transitions']}  "
                  f"txn_cost=₩{result['transition_cost_krw']:,.0f}")
            print(f"           trades: vpin={sd['vpin_eth']} mom={sd['momentum_sol']} "
                  f"vol={sd['volspike_btc']} mr_eth={sd['rsi_mr_bear_eth']} "
                  f"mr_btc={sd['rsi_mr_bear_btc']}")

    # Summary
    print("\n" + "=" * 80)
    print("  === SUMMARY: STATIC vs DYNAMIC ===")
    print("=" * 80)

    for mode in ["static", "dynamic"]:
        mode_results = [r for r in all_results if r["mode"] == mode]
        avg_sharpe = np.mean([r["sharpe"] for r in mode_results])
        avg_ret = np.mean([r["return_pct"] for r in mode_results])
        total_n = sum(r["total_trades"] for r in mode_results)
        avg_wr = np.mean([r["win_rate"] for r in mode_results])
        avg_mdd = np.mean([r["mdd_pct"] for r in mode_results])
        total_txn = sum(r["transition_cost_krw"] for r in mode_results)

        print(f"\n  {mode.upper():>7}:")
        print(f"    avg Sharpe: {avg_sharpe:+.3f}")
        print(f"    avg Return: {avg_ret:+.2f}%")
        print(f"    total trades: {total_n}")
        print(f"    avg WR: {avg_wr:.1f}%")
        print(f"    avg MDD: {avg_mdd:.2f}%")
        if mode == "dynamic":
            print(f"    total transition cost: ₩{total_txn:,.0f}")

    # Delta
    static_sharpe = np.mean([r["sharpe"] for r in all_results if r["mode"] == "static"])
    dynamic_sharpe = np.mean([r["sharpe"] for r in all_results if r["mode"] == "dynamic"])
    static_ret = np.mean([r["return_pct"] for r in all_results if r["mode"] == "static"])
    dynamic_ret = np.mean([r["return_pct"] for r in all_results if r["mode"] == "dynamic"])

    print(f"\n  Delta Sharpe: {dynamic_sharpe - static_sharpe:+.3f} (dynamic - static)")
    print(f"  Delta Return: {dynamic_ret - static_ret:+.2f}%")

    verdict = "PASS" if dynamic_sharpe > static_sharpe and dynamic_ret > static_ret else "FAIL"
    print(f"\n  ★ Verdict: {verdict}")
    if verdict == "PASS":
        print("  → Regime-adaptive reallocation improves portfolio performance")
        print("  → Recommendation: implement dynamic capital transfer in multi_runtime.py")
    else:
        print("  → Regime-adaptive reallocation does NOT improve enough to justify complexity")
        print("  → Recommendation: keep static allocation, focus on new alpha sources")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
