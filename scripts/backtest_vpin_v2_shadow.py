#!/usr/bin/env python3
"""Compare current VPIN wallets against VPIN v2 on the 240m pilot symbol set."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from crypto_trader.backtest.engine import BacktestEngine  # noqa: E402
from crypto_trader.backtest.walk_forward import WalkForwardValidator  # noqa: E402
from crypto_trader.config import BacktestConfig, RegimeConfig, load_config  # noqa: E402
from crypto_trader.models import Candle  # noqa: E402
from crypto_trader.risk.manager import RiskManager  # noqa: E402
from crypto_trader.wallet import (  # noqa: E402
    _risk_config_for_wallet,
    _strategy_config_for_wallet,
    create_strategy,
)

DEFAULT_SYMBOLS = ["KRW-SOL", "KRW-ONDO", "KRW-AVAX"]
DEFAULT_V2_OVERRIDES: dict[str, float | int] = {
    "entry_score_threshold": 3.0,
    "vpin_roc_lookback": 3,
    "vpin_roc_min": 0.0,
    "rsi_delta_lookback": 3,
    "rsi_delta_min": 0.0,
    "ema_slope_lookback": 3,
    "ema_slope_min": 0.0,
}


def _bars_per_day(interval: str) -> int:
    return {
        "minute240": 6,
        "minute60": 24,
        "minute30": 48,
        "minute15": 96,
        "minute5": 288,
        "day": 1,
    }.get(interval, 24)


def _cache_path(cache_dir: str | None, symbol: str, interval: str, days: int) -> Path | None:
    if not cache_dir:
        return None
    safe_symbol = symbol.replace("-", "_")
    return Path(cache_dir) / f"{safe_symbol}-{interval}-{days}d-shadow.json"


def _load_pyupbit() -> Any:
    try:
        return import_module("pyupbit")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "pyupbit is required to fetch live candle data; install the 'live' extra or reuse cache."
        ) from exc


def _load_cache(cache_dir: str | None, symbol: str, interval: str, days: int, expected_count: int) -> list[Candle] | None:
    path = _cache_path(cache_dir, symbol, interval, days)
    if path is None or not path.exists():
        return None
    age_hours = (
        datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    ).total_seconds() / 3600.0
    if age_hours > 6:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    candles = [
        Candle(
            timestamp=datetime.fromisoformat(item["timestamp"]),
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            volume=float(item["volume"]),
        )
        for item in payload
    ]
    return candles if len(candles) >= expected_count else None


def _save_cache(cache_dir: str | None, symbol: str, interval: str, days: int, candles: list[Candle]) -> None:
    path = _cache_path(cache_dir, symbol, interval, days)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "timestamp": candle.timestamp.isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        for candle in candles
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _fetch_candles(symbol: str, days: int, interval: str, cache_dir: str | None) -> list[Candle]:
    expected_count = days * _bars_per_day(interval)
    cached = _load_cache(cache_dir, symbol, interval, days, expected_count)
    if cached is not None:
        return cached

    pyupbit = _load_pyupbit()
    all_candles: list[Candle] = []
    to_dt: datetime | None = None
    while len(all_candles) < expected_count:
        batch_size = min(200, expected_count - len(all_candles))
        frame = pyupbit.get_ohlcv(symbol, interval=interval, count=batch_size, to=to_dt)
        if frame is None or frame.empty:
            break
        batch: list[Candle] = []
        for idx, row in frame.iterrows():
            ts = idx if isinstance(idx, datetime) else datetime.fromisoformat(str(idx))
            batch.append(
                Candle(
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        if not batch:
            break
        to_dt = batch[0].timestamp - timedelta(hours=9, seconds=1)
        all_candles = batch + all_candles
        if len(batch) < batch_size:
            break
        time.sleep(0.15)

    candles = sorted({candle.timestamp: candle for candle in all_candles}.values(), key=lambda c: c.timestamp)
    if len(candles) > expected_count:
        candles = candles[-expected_count:]
    if candles:
        _save_cache(cache_dir, symbol, interval, days, candles)
    return candles


def _wallet_map(config_path: str) -> tuple[Any, dict[str, Any]]:
    config = load_config(config_path, {})
    wallets = {
        wallet.symbols[0]: wallet
        for wallet in config.wallets
        if wallet.strategy == "vpin" and wallet.symbols
    }
    return config, wallets


def _run_backtest(strategy: Any, risk_manager: RiskManager, candles: list[Any], symbol: str) -> dict[str, Any]:
    engine = BacktestEngine(
        strategy=strategy,
        risk_manager=risk_manager,
        config=BacktestConfig(
            initial_capital=1_000_000.0,
            fee_rate=0.0005,
            slippage_pct=0.0005,
        ),
        symbol=symbol,
    )
    result = engine.run(candles)
    return {
        "return_pct": round(result.total_return_pct * 100, 3),
        "win_rate": round(result.win_rate * 100, 3),
        "trade_count": len(result.trade_log),
        "profit_factor": round(result.profit_factor, 3),
        "sharpe_ratio": round(result.sharpe_ratio, 3),
        "max_drawdown_pct": round(result.max_drawdown * 100, 3),
    }


def _run_walk_forward(strategy_factory: Any, risk_config: Any, candles: list[Any], symbol: str, name: str) -> dict[str, Any]:
    validator = WalkForwardValidator(
        backtest_config=BacktestConfig(
            initial_capital=1_000_000.0,
            fee_rate=0.0005,
            slippage_pct=0.0005,
        ),
        risk_config=risk_config,
        n_folds=3,
        train_pct=0.7,
    )
    report = validator.validate(
        strategy_factory=strategy_factory,
        candles=candles,
        symbol=symbol,
        strategy_name=name,
    )
    return report.summary()


def _strategy_factory(config: Any, wallet: Any, strategy_name: str, extra_params: dict[str, Any]) -> Any:
    strategy_config = _strategy_config_for_wallet(config.strategy, wallet)
    regime_config = RegimeConfig(
        short_lookback=config.regime.short_lookback,
        long_lookback=config.regime.long_lookback,
        bull_threshold_pct=config.regime.bull_threshold_pct,
        bear_threshold_pct=config.regime.bear_threshold_pct,
    )
    return create_strategy(
        strategy_name,
        strategy_config,
        regime_config,
        extra_params,
    )


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# VPIN vs VPIN v2 Shadow Report",
        "",
        f"- Config: `{payload['config_path']}`",
        f"- Days: `{payload['days']}`",
        f"- Interval: `{payload['interval']}`",
        "",
        "| Symbol | Wallet | Strategy | Return% | Sharpe | WinRate% | Trades | WF Sharpe | WF Return% | WF Pass |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["results"]:
        backtest = row["backtest"]
        wf = row["walk_forward"]
        lines.append(
            f"| {row['symbol']} | {row['wallet_name']} | {row['strategy']} "
            f"| {backtest['return_pct']:+.2f} "
            f"| {backtest['sharpe_ratio']:.2f} "
            f"| {backtest['win_rate']:.1f} "
            f"| {backtest['trade_count']} "
            f"| {wf['avg_oos_sharpe']:.2f} "
            f"| {wf['avg_test_return_pct']:+.2f} "
            f"| {'YES' if wf['passed'] else 'NO'} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/daemon.toml")
    parser.add_argument("--days", type=int, default=720)
    parser.add_argument("--interval", default="minute240")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument(
        "--v2-json",
        default="",
        help="Optional JSON object merged into vpin_v2 extra params.",
    )
    parser.add_argument(
        "--json-out",
        default="artifacts/vpin-v2-shadow/report.json",
    )
    parser.add_argument(
        "--md-out",
        default="artifacts/vpin-v2-shadow/report.md",
    )
    args = parser.parse_args()

    config, wallets = _wallet_map(args.config)
    symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()]
    v2_overrides = dict(DEFAULT_V2_OVERRIDES)
    if args.v2_json:
        v2_overrides.update(json.loads(args.v2_json))

    cache_dir = os.environ.get("CT_CANDLE_CACHE_DIR", "artifacts/candle-cache")

    results: list[dict[str, Any]] = []
    for symbol in symbols:
        wallet = wallets.get(symbol)
        if wallet is None:
            continue
        candles = _fetch_candles(
            symbol,
            args.days,
            args.interval,
            cache_dir,
        )
        if len(candles) < 100:
            continue

        risk_config = _risk_config_for_wallet(config, wallet)

        baseline_extra = dict(wallet.strategy_overrides)
        baseline_strategy = _strategy_factory(config, wallet, "vpin", baseline_extra)
        baseline_backtest = _run_backtest(
            baseline_strategy,
            RiskManager(risk_config),
            candles,
            symbol,
        )
        baseline_wf = _run_walk_forward(
            lambda: _strategy_factory(config, wallet, "vpin", baseline_extra),
            risk_config,
            candles,
            symbol,
            "vpin",
        )
        results.append(
            {
                "symbol": symbol,
                "wallet_name": wallet.name,
                "strategy": "vpin",
                "backtest": baseline_backtest,
                "walk_forward": baseline_wf,
                "params": baseline_extra,
            }
        )

        v2_extra = dict(wallet.strategy_overrides)
        v2_extra.update(v2_overrides)
        v2_strategy = _strategy_factory(config, wallet, "vpin_v2", v2_extra)
        v2_backtest = _run_backtest(
            v2_strategy,
            RiskManager(risk_config),
            candles,
            symbol,
        )
        v2_wf = _run_walk_forward(
            lambda: _strategy_factory(config, wallet, "vpin_v2", v2_extra),
            risk_config,
            candles,
            symbol,
            "vpin_v2",
        )
        results.append(
            {
                "symbol": symbol,
                "wallet_name": f"{wallet.name}_v2_shadow",
                "strategy": "vpin_v2",
                "backtest": v2_backtest,
                "walk_forward": v2_wf,
                "params": v2_extra,
            }
        )

    payload = {
        "config_path": args.config,
        "days": args.days,
        "interval": args.interval,
        "results": results,
    }
    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(Path(args.md_out), payload)

    print(f"Wrote {json_path}")
    print(f"Wrote {args.md_out}")


if __name__ == "__main__":
    main()
