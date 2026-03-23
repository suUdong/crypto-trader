from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.operator.regime_report import RegimeReportGenerator


def build_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1, 0, 0, 0)
    return [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=1_000.0,
        )
        for index, close in enumerate(closes)
    ]


class RegimeReportGeneratorTests(unittest.TestCase):
    def test_generate_bull_report_contains_adjusted_parameters(self) -> None:
        report = RegimeReportGenerator(RegimeConfig(short_lookback=5, long_lookback=10)).generate(
            symbol="KRW-BTC",
            strategy=StrategyConfig(),
            candles=build_candles([100 + index * 2 for index in range(40)]),
        )
        self.assertEqual(report.market_regime, "bull")
        self.assertGreater(
            report.adjusted_parameters["rsi_recovery_ceiling"],
            report.base_parameters["rsi_recovery_ceiling"],
        )

    def test_generate_bear_report_contains_reasoning(self) -> None:
        report = RegimeReportGenerator(RegimeConfig(short_lookback=5, long_lookback=10)).generate(
            symbol="KRW-BTC",
            strategy=StrategyConfig(),
            candles=build_candles([180 - index * 2 for index in range(40)]),
        )
        self.assertEqual(report.market_regime, "bear")
        self.assertTrue(any("tighten entries" in reason for reason in report.reasons))

    def test_save_writes_report_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "regime.json"
            generator = RegimeReportGenerator(RegimeConfig(short_lookback=5, long_lookback=10))
            report = generator.generate(
                symbol="KRW-BTC",
                strategy=StrategyConfig(),
                candles=build_candles([100 + index * 2 for index in range(40)]),
            )
            generator.save(report, path)
            self.assertTrue(path.exists())
