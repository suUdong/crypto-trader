#!/usr/bin/env python3
"""Analyze volspike_btc spike_mult: trigger frequency + backtest comparison.

Usage: PYTHONPATH=src python scripts/spike_mult_analysis.py [days]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

from crypto_trader.backtest.candle_cache import fetch_upbit_candles
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.volume_spike import VolumeSpikeStrategy

SYMBOL = "KRW-BTC"
INTERVAL = "minute60"
SPIKE_MULTS = [1.5, 2.0, 2.5, 3.0]
VOLUME_WINDOW = 20


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90

    print(f"Fetching {days}d of {SYMBOL} hourly candles...")
    candles = fetch_upbit_candles(
        SYMBOL, days, interval=INTERVAL,
        cache_dir=os.environ.get("CT_CANDLE_CACHE_DIR"),
    )
    print(f"Got {len(candles)} candles ({candles[0].timestamp} → {candles[-1].timestamp})\n")

    # --- Part 1: Volume spike frequency analysis ---
    print("=" * 70)
    print("PART 1: Volume Spike Trigger Frequency")
    print("=" * 70)

    volumes = [c.volume for c in candles]
    spike_counts: dict[float, int] = {m: 0 for m in SPIKE_MULTS}

    for i in range(VOLUME_WINDOW, len(candles)):
        window_vols = volumes[i - VOLUME_WINDOW : i]
        avg_vol = sum(window_vols) / len(window_vols)
        if avg_vol <= 0:
            continue
        ratio = volumes[i] / avg_vol
        for mult in SPIKE_MULTS:
            if ratio >= mult:
                spike_counts[mult] += 1

    total_bars = len(candles) - VOLUME_WINDOW
    print(f"\nTotal bars analyzed: {total_bars} ({days}d hourly)")
    print(f"{'spike_mult':>12} {'triggers':>10} {'freq':>10} {'avg days/trigger':>18}")
    print("-" * 55)
    for mult in SPIKE_MULTS:
        count = spike_counts[mult]
        freq_pct = count / total_bars * 100 if total_bars > 0 else 0
        days_per = (total_bars / 24) / count if count > 0 else float("inf")
        print(f"{mult:>12.1f} {count:>10} {freq_pct:>9.2f}% {days_per:>17.1f}d")

    # --- Part 2: Backtest comparison ---
    print(f"\n{'=' * 70}")
    print("PART 2: Backtest Comparison (KRW-BTC, volume_spike strategy)")
    print("=" * 70)

    # Use daemon.toml params as base
    base_config = StrategyConfig(
        momentum_lookback=12,
        rsi_period=14,
        rsi_overbought=72.0,
        max_holding_bars=24,
    )
    risk_config = RiskConfig(
        stop_loss_pct=0.02,
        take_profit_pct=0.06,
        risk_per_trade_pct=0.02,
        atr_stop_multiplier=1.5,
        min_entry_confidence=0.45,
    )
    backtest_config = BacktestConfig(
        initial_capital=1_000_000.0,
        fee_rate=0.0005,
        slippage_pct=0.0005,
    )

    print(f"\n{'spike_mult':>12} {'trades':>8} {'WR%':>8} {'return%':>10} "
          f"{'Sharpe':>8} {'MDD%':>8} {'PF':>8}")
    print("-" * 70)

    for mult in SPIKE_MULTS:
        strategy = VolumeSpikeStrategy(
            base_config,
            RegimeConfig(),
            spike_mult=mult,
            volume_window=VOLUME_WINDOW,
            min_body_ratio=0.2,
        )
        risk_manager = RiskManager(risk_config)
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk_manager,
            config=backtest_config,
            symbol=SYMBOL,
        )
        result = engine.run(candles)

        # Approx Sharpe
        eq = result.equity_curve
        if len(eq) >= 3:
            rets = [(eq[i] - eq[i-1]) / max(1.0, eq[i-1]) for i in range(1, len(eq))]
            mean_r = sum(rets) / len(rets)
            var_r = sum((r - mean_r)**2 for r in rets) / len(rets)
            std_r = var_r**0.5
            sharpe = (mean_r / std_r) * (8760**0.5) if std_r > 0 else 0.0
        else:
            sharpe = 0.0

        marker = ""
        if mult == 3.0:
            marker = " ← current"
        elif mult == 2.0:
            marker = " ← candidate"

        print(
            f"{mult:>12.1f} {len(result.trade_log):>8} "
            f"{result.win_rate * 100:>7.1f} {result.total_return_pct * 100:>9.3f} "
            f"{sharpe:>8.2f} {result.max_drawdown * 100:>7.3f} "
            f"{result.profit_factor:>7.2f}{marker}"
        )

    print("\n" + "=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)
    print("If spike_mult=3.0 shows 0 trades, it confirms the go-live report concern.")
    print("Look for the spike_mult that balances trade frequency with Sharpe/WR.")


if __name__ == "__main__":
    main()
