#!/usr/bin/env python3
"""Risk parameter optimization: stop_loss, take_profit, trailing_stop per strategy.

Uses best strategy params from grid search, then optimizes risk params.
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from crypto_trader.backtest.engine import BacktestEngine  # noqa: E402
from crypto_trader.config import (  # noqa: E402
    BacktestConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
)
from crypto_trader.models import Candle  # noqa: E402
from crypto_trader.risk.manager import RiskManager  # noqa: E402
from crypto_trader.wallet import create_strategy  # noqa: E402
from scripts.grid_search import (  # noqa: E402
    SYMBOLS,
    _approx_sharpe,
    fetch_candles,
)

# Best strategy params from grid search (per-symbol best)
BEST_STRATEGY_PARAMS = {
    "momentum": {
        "KRW-BTC": {
            "momentum_lookback": 12,
            "momentum_entry_threshold": 0.001,
            "rsi_period": 14,
            "rsi_overbought": 72.0,
            "max_holding_bars": 36,
            "adx_threshold": 20.0,
        },
        "KRW-ETH": {
            "momentum_lookback": 15,
            "momentum_entry_threshold": 0.003,
            "rsi_period": 14,
            "rsi_overbought": 70.0,
            "max_holding_bars": 36,
            "adx_threshold": 15.0,
        },
        "KRW-SOL": {
            "momentum_lookback": 15,
            "momentum_entry_threshold": 0.002,
            "rsi_period": 14,
            "rsi_overbought": 72.0,
            "max_holding_bars": 36,
            "adx_threshold": 20.0,
        },
    },
    "vpin": {
        "KRW-BTC": {"rsi_period": 14, "momentum_lookback": 12, "max_holding_bars": 48},
        "KRW-ETH": {"rsi_period": 14, "momentum_lookback": 10, "max_holding_bars": 36},
        "KRW-SOL": {"rsi_period": 14, "momentum_lookback": 10, "max_holding_bars": 36},
    },
    "volatility_breakout": {
        "KRW-BTC": {
            "k_base": 0.50,
            "noise_lookback": 15,
            "ma_filter_period": 10,
            "max_holding_bars": 36,
        },
        "KRW-ETH": {
            "k_base": 0.50,
            "noise_lookback": 15,
            "ma_filter_period": 5,
            "max_holding_bars": 36,
        },
        "KRW-XRP": {
            "k_base": 0.40,
            "noise_lookback": 15,
            "ma_filter_period": 5,
            "max_holding_bars": 36,
        },
    },
    "volume_spike": {
        "KRW-BTC": {
            "momentum_lookback": 12,
            "rsi_period": 14,
            "rsi_overbought": 72.0,
            "max_holding_bars": 36,
            "adx_threshold": 20.0,
        },
        "KRW-ETH": {
            "momentum_lookback": 12,
            "rsi_period": 14,
            "rsi_overbought": 72.0,
            "max_holding_bars": 36,
            "adx_threshold": 15.0,
        },
    },
}

# Extra constructor params per strategy+symbol
EXTRA_PARAMS = {
    "vpin": {
        "KRW-BTC": {
            "vpin_low_threshold": 0.45,
            "vpin_high_threshold": 0.75,
            "vpin_momentum_threshold": 0.001,
            "bucket_count": 20,
        },
        "KRW-ETH": {
            "vpin_low_threshold": 0.45,
            "vpin_high_threshold": 0.75,
            "vpin_momentum_threshold": 0.0005,
            "bucket_count": 20,
        },
        "KRW-SOL": {
            "vpin_low_threshold": 0.45,
            "vpin_high_threshold": 0.75,
            "vpin_momentum_threshold": 0.0005,
            "bucket_count": 20,
        },
    },
    "volatility_breakout": {
        "KRW-BTC": {"k_base": 0.50, "noise_lookback": 15, "ma_filter_period": 10},
        "KRW-ETH": {"k_base": 0.50, "noise_lookback": 15, "ma_filter_period": 5},
        "KRW-XRP": {"k_base": 0.40, "noise_lookback": 15, "ma_filter_period": 5},
    },
    "volume_spike": {
        "KRW-BTC": {"spike_mult": 3.0, "volume_window": 20, "min_body_ratio": 0.3},
        "KRW-ETH": {"spike_mult": 3.0, "volume_window": 20, "min_body_ratio": 0.3},
    },
}

# Risk parameter grid
RISK_GRID = {
    "stop_loss_pct": [0.02, 0.03, 0.04, 0.05],
    "take_profit_pct": [0.04, 0.06, 0.08, 0.10],
    "trailing_stop_pct": [0.0, 0.02, 0.04],
}
# 4×4×3 = 48 combos per strategy+symbol


def main() -> None:
    days = 90
    t0 = time.time()

    print(f"\n{'#' * 80}")
    print(f"  RISK PARAMETER OPTIMIZATION — {days}-day data")
    print(f"{'#' * 80}")

    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in SYMBOLS:
        print(f"Fetching {symbol} ({days}d)...", end=" ", flush=True)
        candles = fetch_candles(symbol, days)
        print(f"{len(candles)} candles")
        if len(candles) >= 50:
            candles_by_symbol[symbol] = candles

    risk_names = list(RISK_GRID.keys())
    risk_values = list(RISK_GRID.values())
    risk_combos = list(itertools.product(*risk_values))

    output: dict[str, dict] = {}

    for strategy_type, symbol_params in BEST_STRATEGY_PARAMS.items():
        print(f"\n{'=' * 80}")
        print(
            f"  {strategy_type.upper()} — risk optimization ({len(risk_combos)} combos per symbol)"
        )

        best_per_symbol: dict[str, dict] = {}

        for symbol, strat_params in symbol_params.items():
            if symbol not in candles_by_symbol:
                continue
            candles = candles_by_symbol[symbol]

            config_fields = {f for f in StrategyConfig.__dataclass_fields__}
            config_kwargs = {k: v for k, v in strat_params.items() if k in config_fields}
            strategy_config = StrategyConfig(**config_kwargs)
            regime_config = RegimeConfig()
            backtest_config = BacktestConfig(
                initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005
            )

            extra = EXTRA_PARAMS.get(strategy_type, {}).get(symbol, {})

            best_score = -999
            best_risk = {}
            best_result = {}

            for combo in risk_combos:
                risk_params = dict(zip(risk_names, combo, strict=True))

                # Skip invalid: take_profit must be > stop_loss
                if risk_params["take_profit_pct"] <= risk_params["stop_loss_pct"]:
                    continue

                risk_config = RiskConfig(
                    stop_loss_pct=risk_params["stop_loss_pct"],
                    take_profit_pct=risk_params["take_profit_pct"],
                    trailing_stop_pct=risk_params["trailing_stop_pct"],
                )

                strategy = create_strategy(strategy_type, strategy_config, regime_config, extra)
                risk_manager = RiskManager(risk_config)
                engine = BacktestEngine(
                    strategy=strategy,
                    risk_manager=risk_manager,
                    config=backtest_config,
                    symbol=symbol,
                )
                result = engine.run(candles)
                sharpe = _approx_sharpe(result.equity_curve)
                score = sharpe * (1.0 - result.max_drawdown)

                if score > best_score:
                    best_score = score
                    best_risk = risk_params
                    best_result = {
                        "sharpe": sharpe,
                        "return_pct": result.total_return_pct * 100,
                        "win_rate": result.win_rate * 100,
                        "mdd": result.max_drawdown * 100,
                        "pf": result.profit_factor,
                        "trades": len(result.trade_log),
                    }

            if best_risk:
                best_per_symbol[symbol] = {"risk_params": best_risk, **best_result}
                print(
                    f"  {symbol}: stop={best_risk['stop_loss_pct']:.0%} "
                    f"tp={best_risk['take_profit_pct']:.0%} "
                    f"trail={best_risk['trailing_stop_pct']:.0%} | "
                    f"sharpe={best_result['sharpe']:.2f} "
                    f"ret={best_result['return_pct']:+.2f}% wr={best_result['win_rate']:.1f}%"
                )

        output[strategy_type] = best_per_symbol

    elapsed = time.time() - t0
    print(f"\n{'#' * 80}")
    print(f"  RISK OPTIMIZATION COMPLETE ({elapsed:.0f}s)")
    print(f"{'#' * 80}")

    for strat, syms in output.items():
        print(f"\n  {strat.upper()}:")
        for sym, data in syms.items():
            rp = data["risk_params"]
            print(
                f"    {sym}: stop={rp['stop_loss_pct']} tp={rp['take_profit_pct']} "
                f"trail={rp['trailing_stop_pct']} "
                f"| sharpe={data['sharpe']:.2f} ret={data['return_pct']:+.2f}%"
            )

    out_path = "artifacts/risk-optimization-results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to {out_path}")


if __name__ == "__main__":
    main()
