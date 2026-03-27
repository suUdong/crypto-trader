"""Tests for Session #11 Wave 5: Calmar ratio, MACD mean reversion, ema_crossover grids."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine, _calmar_ratio
from crypto_trader.backtest.grid_wf import PARAM_GRIDS
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy


def _candles(closes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=t + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


# ---------- Calmar ratio ----------


class TestCalmarRatio(unittest.TestCase):
    def test_calmar_positive_for_uptrend(self) -> None:
        curve = [1000.0 + i * 10.0 for i in range(100)]
        calmar = _calmar_ratio(curve)
        self.assertGreater(calmar, 0)

    def test_calmar_negative_for_downtrend(self) -> None:
        curve = [1000.0 - i * 10.0 for i in range(50)]
        calmar = _calmar_ratio(curve)
        self.assertLess(calmar, 0)

    def test_calmar_zero_for_flat(self) -> None:
        curve = [1000.0] * 100
        calmar = _calmar_ratio(curve)
        self.assertEqual(calmar, 0.0)

    def test_calmar_inf_for_no_drawdown(self) -> None:
        curve = [1000.0 + i * 10.0 for i in range(50)]
        calmar = _calmar_ratio(curve)
        self.assertEqual(calmar, float("inf"))

    def test_calmar_on_short_curve(self) -> None:
        self.assertEqual(_calmar_ratio([100.0, 101.0]), 0.0)

    def test_backtest_result_has_calmar(self) -> None:
        candles = _candles([100.0] * 30)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5)
        )
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertIsInstance(result.calmar_ratio, float)


# ---------- MACD in MeanReversionStrategy ----------


class TestMeanReversionMACD(unittest.TestCase):
    def test_macd_histogram_in_indicators(self) -> None:
        closes = [100.0] * 40
        candles = _candles(closes)
        strategy = MeanReversionStrategy(
            StrategyConfig(bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("macd_histogram", signal.indicators)

    def test_macd_absent_with_few_candles(self) -> None:
        closes = [100.0] * 25
        candles = _candles(closes)
        strategy = MeanReversionStrategy(
            StrategyConfig(bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        # macd_histogram should be 0.0 (default) since not enough data
        self.assertEqual(signal.indicators.get("macd_histogram", 0), 0.0)


# ---------- EMA crossover param grids ----------


class TestEMACrossoverParamGrids(unittest.TestCase):
    def test_ema_crossover_in_param_grids(self) -> None:
        self.assertIn("ema_crossover", PARAM_GRIDS)

    def test_ema_crossover_has_params(self) -> None:
        grid = PARAM_GRIDS["ema_crossover"]
        self.assertIn("rsi_period", grid)
        self.assertIn("max_holding_bars", grid)

    def test_all_strategies_have_grids(self) -> None:
        """All supported strategy types should have param grids."""
        expected = {
            "momentum",
            "momentum_pullback",
            "mean_reversion",
            "bollinger_rsi",
            "vpin",
            "volatility_breakout",
            "composite",
            "kimchi_premium",
            "funding_rate",
            "obi",
            "ema_crossover",
            "consensus",
        }
        self.assertEqual(set(PARAM_GRIDS.keys()), expected)


if __name__ == "__main__":
    unittest.main()
