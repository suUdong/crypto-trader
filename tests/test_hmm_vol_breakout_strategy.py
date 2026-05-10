from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.hmm_regime import HMMRegimeAnalysis, HMMRegimeDetector, HMMState
from crypto_trader.strategy.hmm_vol_breakout import HMMVolBreakoutStrategy


def build_candles(count: int, *, breakout: bool = False) -> list[Candle]:
    candles: list[Candle] = []
    start = datetime(2026, 1, 1)
    price = 100.0
    for index in range(count):
        open_price = price
        close = price * (1.002 if index % 3 else 0.999)
        if breakout and index == count - 1:
            close = price * 1.03
        high = max(open_price, close) * 1.002
        low = min(open_price, close) * 0.998
        candles.append(
            Candle(
                timestamp=start + timedelta(minutes=5 * index),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1_000.0 + index * 10.0,
            )
        )
        price = close
    return candles


class FakeTrendDetector:
    def train(self, candles: list[Candle]) -> bool:
        return True

    def predict(self, candles: list[Candle]) -> HMMRegimeAnalysis:
        return HMMRegimeAnalysis(HMMState.TREND, 0.82, 0.01)


class FakeNoiseDetector:
    def train(self, candles: list[Candle]) -> bool:
        return True

    def predict(self, candles: list[Candle]) -> HMMRegimeAnalysis:
        return HMMRegimeAnalysis(HMMState.NOISE, 0.91, 0.01)


class HMMRegimeDetectorTests(unittest.TestCase):
    def test_train_requires_enough_feature_rows(self) -> None:
        detector = HMMRegimeDetector()

        self.assertFalse(detector.train(build_candles(20)))

    def test_train_and_predict_returns_valid_state(self) -> None:
        detector = HMMRegimeDetector()
        candles = build_candles(120)

        self.assertTrue(detector.train(candles))
        analysis = detector.predict(candles)

        self.assertIn(analysis.state, (HMMState.NOISE, HMMState.TREND))
        self.assertGreaterEqual(analysis.confidence, 0.0)
        self.assertLessEqual(analysis.confidence, 1.0)
        self.assertGreaterEqual(analysis.volatility, 0.0)


class HMMVolBreakoutStrategyTests(unittest.TestCase):
    def _make_strategy(self, detector: object) -> HMMVolBreakoutStrategy:
        strategy = HMMVolBreakoutStrategy(
            StrategyConfig(k_base=0.2, max_holding_bars=4),
            RegimeConfig(),
            enabled=True,
        )
        strategy._detector = detector  # type: ignore[assignment]
        return strategy

    def test_insufficient_data_returns_hold(self) -> None:
        strategy = self._make_strategy(FakeTrendDetector())

        signal = strategy.evaluate(build_candles(50))

        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_registry_default_is_disabled(self) -> None:
        strategy = HMMVolBreakoutStrategy(
            StrategyConfig(k_base=0.2, max_holding_bars=4),
            RegimeConfig(),
            enabled=False,
        )

        signal = strategy.evaluate(build_candles(120, breakout=True))

        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "hmm_vol_breakout_disabled")

    def test_noise_regime_blocks_breakout_entry(self) -> None:
        strategy = self._make_strategy(FakeNoiseDetector())

        signal = strategy.evaluate(build_candles(120, breakout=True))

        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "noise_regime")

    def test_trend_breakout_generates_buy_signal(self) -> None:
        strategy = self._make_strategy(FakeTrendDetector())

        signal = strategy.evaluate(build_candles(120, breakout=True), symbol="KRW-SOL")

        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "hmm_trend_confirmed_breakout")
        self.assertEqual(signal.context["strategy"], "hmm_vol_breakout")

    def test_position_exits_on_max_holding_bars(self) -> None:
        strategy = self._make_strategy(FakeTrendDetector())
        candles = build_candles(120)
        position = Position(
            symbol="KRW-SOL",
            quantity=1.0,
            entry_price=candles[100].close,
            entry_time=candles[100].timestamp,
            entry_index=100,
        )

        signal = strategy.evaluate(candles, position, symbol="KRW-SOL")

        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding")


if __name__ == "__main__":
    unittest.main()
