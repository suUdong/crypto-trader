from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.momentum_pullback import MomentumPullbackStrategy


def _build_candles(closes: list[float], volumes: list[float] | None = None) -> list[Candle]:
    start = datetime(2025, 1, 1)
    use_volumes = volumes or [1000.0 + i * 10.0 for i in range(len(closes))]
    candles: list[Candle] = []
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i > 0 else close
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=i),
                open=prev,
                high=max(prev, close) * 1.01,
                low=min(prev, close) * 0.99,
                close=close,
                volume=use_volumes[i],
            )
        )
    return candles


def _flat_regime_config() -> RegimeConfig:
    return RegimeConfig(
        short_lookback=5,
        long_lookback=10,
        bull_threshold_pct=0.99,
        bear_threshold_pct=-0.99,
    )


def _strategy(**overrides: object) -> MomentumPullbackStrategy:
    defaults: dict[str, object] = {
        "momentum_lookback": 10,
        "momentum_entry_threshold": 0.015,
        "momentum_exit_threshold": -0.01,
        "bollinger_window": 10,
        "bollinger_stddev": 1.4,
        "rsi_period": 10,
        "rsi_oversold_floor": 25.0,
        "rsi_recovery_ceiling": 60.0,
        "rsi_overbought": 72.0,
        "adx_threshold": 5.0,
        "max_holding_bars": 24,
    }
    defaults.update(overrides)
    return MomentumPullbackStrategy(
        StrategyConfig(**defaults),  # type: ignore[arg-type]
        _flat_regime_config(),
    )


def _trend_then_pullback() -> list[float]:
    closes = [100.0 + i * 1.5 for i in range(45)]
    closes.extend([162.0, 160.0, 158.0, 156.0, 154.0, 156.0])
    return closes


class MomentumPullbackStrategyTests(unittest.TestCase):
    def test_insufficient_data_returns_hold(self) -> None:
        signal = _strategy().evaluate(_build_candles([100.0 + i for i in range(20)]))
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_buy_when_trend_and_pullback_align(self) -> None:
        signal = _strategy().evaluate(_build_candles(_trend_then_pullback()))
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "trend_pullback_entry")

    def test_hold_when_pullback_happens_without_uptrend(self) -> None:
        closes = [200.0 - i * 1.8 for i in range(45)]
        closes.extend([122.0, 120.0, 118.0, 116.0, 114.0, 115.0])
        signal = _strategy().evaluate(_build_candles(closes))
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "trend_not_established")

    def test_sell_on_trend_failure(self) -> None:
        closes = [100.0 + i * 1.4 for i in range(45)]
        closes.extend([158.0, 155.0, 150.0, 145.0, 140.0, 135.0])
        candles = _build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=155.0,
            entry_time=candles[-6].timestamp,
            entry_index=len(candles) - 6,
        )
        signal = _strategy().evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "trend_failure")

    def test_sell_on_recovery_target(self) -> None:
        closes = [100.0 + i * 1.0 for i in range(45)]
        closes.extend([150.0, 148.0, 146.0, 144.0, 151.0, 159.0])
        candles = _build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=145.0,
            entry_time=candles[-4].timestamp,
            entry_index=len(candles) - 4,
        )
        signal = _strategy().evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertIn(signal.reason, {"pullback_recovery_target", "pullback_overbought_exit"})

    def test_sell_on_max_holding_period(self) -> None:
        candles = _build_candles(_trend_then_pullback())
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=154.0,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = _strategy(max_holding_bars=2).evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")


if __name__ == "__main__":
    unittest.main()
