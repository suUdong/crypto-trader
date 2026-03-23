from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.regime import MarketRegime, RegimeDetector


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


class RegimeDetectorTests(unittest.TestCase):
    def test_detects_bull_regime(self) -> None:
        detector = RegimeDetector(RegimeConfig(short_lookback=5, long_lookback=10))
        regime = detector.detect(build_candles([100 + index * 2 for index in range(20)]))
        self.assertEqual(regime, MarketRegime.BULL)

    def test_detects_bear_regime(self) -> None:
        detector = RegimeDetector(RegimeConfig(short_lookback=5, long_lookback=10))
        regime = detector.detect(build_candles([140 - index * 2 for index in range(20)]))
        self.assertEqual(regime, MarketRegime.BEAR)

    def test_defaults_to_sideways_without_clear_trend(self) -> None:
        detector = RegimeDetector(RegimeConfig(short_lookback=5, long_lookback=10))
        regime = detector.detect(
            build_candles([100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101])
        )
        self.assertEqual(regime, MarketRegime.SIDEWAYS)

    def test_bear_adjustment_tightens_strategy_parameters(self) -> None:
        detector = RegimeDetector(RegimeConfig())
        base = StrategyConfig()
        adjusted = detector.adjust(base, MarketRegime.BEAR)
        self.assertGreater(adjusted.momentum_entry_threshold, base.momentum_entry_threshold)
        self.assertLess(adjusted.max_holding_bars, base.max_holding_bars)


class RegimeAwareStrategyTests(unittest.TestCase):
    def test_signal_context_includes_detected_regime(self) -> None:
        candles = build_candles([100 + index * 2 for index in range(40)])
        strategy = CompositeStrategy(
            StrategyConfig(),
            RegimeConfig(short_lookback=5, long_lookback=10),
        )
        signal = strategy.evaluate(candles)
        self.assertIn(signal.context["market_regime"], {"bull", "sideways", "bear"})

    def test_bear_regime_can_prevent_a_permissive_entry(self) -> None:
        candles = build_candles(
            [
                120,
                118,
                116,
                114,
                112,
                110,
                108,
                106,
                104,
                102,
                100,
                99,
                98,
                97,
                96,
                95,
                94,
                93,
                92,
                91,
                90,
                89,
            ]
        )
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                bollinger_window=20,
                bollinger_stddev=1.5,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
            ),
            RegimeConfig(short_lookback=5, long_lookback=10),
        )
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.context["market_regime"], "bear")
