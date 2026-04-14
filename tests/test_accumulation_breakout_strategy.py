from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.experimental.accumulation_hunter import (
    AccumulationBreakoutStrategy,
)


def _build_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for i, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=i),
                open=close + 0.1,
                high=close + 0.3,
                low=close - 0.3,
                close=close,
                volume=100.0 + i,
            )
        )
    return candles


def _make_strategy() -> AccumulationBreakoutStrategy:
    return AccumulationBreakoutStrategy(
        StrategyConfig(rsi_period=5, max_holding_bars=48),
        vpin_threshold=1.0,
        cvd_slope_threshold=10.0,
        volatility_ceiling=1.0,
        stealth_lookback=4,
        stealth_rs_low=0.5,
        stealth_rs_high=1.0,
    )


def test_accumulation_strategy_prefers_market_scan_rs_when_available(tmp_path: Path) -> None:
    strategy = AccumulationBreakoutStrategy(
        StrategyConfig(rsi_period=5, max_holding_bars=48),
        vpin_threshold=1.0,
        cvd_slope_threshold=10.0,
        volatility_ceiling=1.0,
        use_scan_rs=True,
        stealth_lookback=4,
        stealth_rs_low=0.5,
        stealth_rs_high=1.0,
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "alpha-watchlist.json").write_text(
        json.dumps(
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "accumulation_candidates": [
                    {"symbol": "KRW-TEST", "rs": 0.7, "acc": 1.2, "alpha": 1.4},
                ],
            }
        ),
        encoding="utf-8",
    )
    candles = _build_candles([100.0 - i * 0.2 for i in range(60)])
    previous_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        with (
            patch.object(strategy._vpin_strategy, "_calculate_vpin", return_value=0.2),
            patch.object(strategy, "_calculate_cvd_slope", return_value=20.0),
        ):
            signal = strategy.evaluate(candles, symbol="KRW-TEST")
    finally:
        os.chdir(previous_cwd)

    assert signal.action is SignalAction.BUY
    assert signal.indicators["rs_score"] == 0.7
    assert signal.indicators["scan_alpha"] == 1.4


def test_accumulation_strategy_ignores_stale_market_scan_rs(tmp_path: Path) -> None:
    strategy = AccumulationBreakoutStrategy(
        StrategyConfig(rsi_period=5, max_holding_bars=48),
        vpin_threshold=1.0,
        cvd_slope_threshold=10.0,
        volatility_ceiling=1.0,
        use_scan_rs=True,
        stealth_lookback=4,
        stealth_rs_low=0.5,
        stealth_rs_high=1.0,
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "alpha-watchlist.json").write_text(
        json.dumps(
            {
                "updated_at": (datetime.now(UTC) - timedelta(hours=12)).isoformat(),
                "accumulation_candidates": [
                    {"symbol": "KRW-TEST", "rs": 0.7, "acc": 1.2, "alpha": 1.4},
                ],
            }
        ),
        encoding="utf-8",
    )
    candles = _build_candles([100.0 - i * 0.2 for i in range(60)])
    previous_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        with (
            patch.object(strategy._vpin_strategy, "_calculate_vpin", return_value=0.2),
            patch.object(strategy, "_calculate_cvd_slope", return_value=20.0),
        ):
            signal = strategy.evaluate(candles, symbol="KRW-TEST")
    finally:
        os.chdir(previous_cwd)

    assert signal.action is SignalAction.HOLD
    assert signal.reason.startswith("rs_out_of_range_")
