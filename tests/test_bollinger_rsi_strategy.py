from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.bollinger_rsi import BollingerRsiStrategy


def _build_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=1_000.0,
        )
        for i, close in enumerate(closes)
    ]


def _config(**overrides: object) -> StrategyConfig:
    defaults: dict[str, object] = {
        "bollinger_window": 5,
        "bollinger_stddev": 1.5,
        "rsi_period": 5,
        "rsi_oversold_floor": 0.0,
        "rsi_recovery_ceiling": 100.0,
        "rsi_overbought": 65.0,
        "max_holding_bars": 10,
    }
    defaults.update(overrides)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


def _flat_regime() -> RegimeConfig:
    return RegimeConfig(
        short_lookback=3,
        long_lookback=5,
        bull_threshold_pct=0.99,
        bear_threshold_pct=-0.99,
    )


class BollingerRsiStrategyTests(unittest.TestCase):
    def test_insufficient_data_returns_hold(self) -> None:
        strategy = BollingerRsiStrategy(_config(), _flat_regime())
        signal = strategy.evaluate(_build_candles([100.0, 101.0, 102.0, 103.0]))
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_buy_near_lower_band_with_reset_rsi(self) -> None:
        strategy = BollingerRsiStrategy(_config(), _flat_regime())
        candles = _build_candles([100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 72.0])
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "bollinger_rsi_reversion")

    def test_hold_without_band_touch(self) -> None:
        strategy = BollingerRsiStrategy(_config(), _flat_regime())
        candles = _build_candles([98.0, 102.0, 98.0, 102.0, 98.0, 102.0, 100.0])
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "entry_conditions_not_met")

    def test_exit_on_middle_band_target(self) -> None:
        strategy = BollingerRsiStrategy(_config(), _flat_regime())
        candles = _build_candles([90.0, 92.0, 94.0, 96.0, 98.0, 100.0, 102.0])
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=90.0,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertIn(
            signal.reason,
            {"middle_band_target", "rsi_overbought", "bollinger_upper_touch"},
        )


if __name__ == "__main__":
    unittest.main()
