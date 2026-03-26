from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy


def build_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


def _small_config(**overrides: object) -> StrategyConfig:
    """StrategyConfig with small windows so tests need few candles."""
    defaults: dict[str, object] = dict(
        bollinger_window=5,
        bollinger_stddev=1.5,
        rsi_period=5,
        rsi_recovery_ceiling=100.0,
        rsi_overbought=70.0,
        max_holding_bars=48,
    )
    defaults.update(overrides)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


def _flat_regime_config() -> RegimeConfig:
    """Regime config that keeps the market classified as sideways (no adjustment)."""
    return RegimeConfig(
        short_lookback=3,
        long_lookback=5,
        bull_threshold_pct=0.99,
        bear_threshold_pct=-0.99,
    )


class TestMeanReversionStrategy(unittest.TestCase):
    # ------------------------------------------------------------------
    # 1. Insufficient data -> HOLD
    # ------------------------------------------------------------------
    def test_insufficient_data_returns_hold(self) -> None:
        strategy = MeanReversionStrategy(_small_config(), _flat_regime_config())
        # bollinger_window=5, rsi_period=5 → minimum = 6; give only 4
        candles = build_candles([100.0, 101.0, 102.0, 103.0])
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    # ------------------------------------------------------------------
    # 2. Price drops sharply to lower Bollinger band → BUY
    # ------------------------------------------------------------------
    def test_buy_near_lower_band(self) -> None:
        # Stable prices followed by a sharp drop forces latest_close near/below lower band.
        # rsi_recovery_ceiling=100 so any RSI qualifies.
        config = _small_config(bollinger_stddev=1.5, rsi_recovery_ceiling=100.0)
        strategy = MeanReversionStrategy(config, _flat_regime_config())

        # 5 stable candles then a sharp drop to push close <= lower_band
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 70.0]
        signal = strategy.evaluate(build_candles(closes))
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "bollinger_mean_reversion")

    # ------------------------------------------------------------------
    # 3. Flat / stable prices, no position → HOLD
    # ------------------------------------------------------------------
    def test_hold_when_price_in_middle(self) -> None:
        config = _small_config()
        strategy = MeanReversionStrategy(config, _flat_regime_config())

        # Prices oscillate symmetrically so the last close lands on the mean,
        # well above the lower Bollinger band → no entry condition met.
        closes = [98.0, 102.0, 98.0, 102.0, 98.0, 102.0, 98.0, 102.0, 100.0]
        signal = strategy.evaluate(build_candles(closes))
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "entry_conditions_not_met")

    # ------------------------------------------------------------------
    # 4. Position open + price rises to upper Bollinger band → SELL
    # ------------------------------------------------------------------
    def test_sell_at_upper_band(self) -> None:
        config = _small_config(bollinger_stddev=1.5)
        strategy = MeanReversionStrategy(config, _flat_regime_config())

        # Stable base then spike above; entry_index=0 keeps holding_bars < max
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 130.0]
        candles = build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "bollinger_upper_touch")

    # ------------------------------------------------------------------
    # 5. Position open + holding_bars >= max_holding_bars → SELL
    # ------------------------------------------------------------------
    def test_sell_on_max_holding_bars(self) -> None:
        config = _small_config(max_holding_bars=2)
        strategy = MeanReversionStrategy(config, _flat_regime_config())

        # 8 candles; entry_index=0 → holding_bars = 8 - 0 - 1 = 7 >= 2
        closes = [100.0] * 8
        candles = build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")

    # ------------------------------------------------------------------
    # 6. Position open + price at middle band + RSI overbought → SELL
    # ------------------------------------------------------------------
    def test_sell_mean_reversion_target(self) -> None:
        # Strongly rising prices push RSI high; final price lands at/above middle band.
        # Use a large max_holding_bars so that path is not triggered first.
        config = _small_config(max_holding_bars=200, rsi_overbought=60.0)
        strategy = MeanReversionStrategy(config, _flat_regime_config())

        # Prices climb steadily; RSI will be high (all gains, no losses → RSI=100)
        # and latest_close >= middle_band
        closes = [90.0, 92.0, 94.0, 96.0, 98.0, 100.0, 102.0]
        candles = build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=90.0,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        # middle_band_target fires first when price >= middle band with 2%+ profit
        self.assertIn(signal.reason, ["mean_reversion_target", "middle_band_target"])


if __name__ == "__main__":
    unittest.main()
