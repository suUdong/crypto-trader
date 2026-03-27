from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.macro.client import MacroSnapshot
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy
from crypto_trader.strategy.regime import KST


def build_candles(
    closes: list[float],
    *,
    start: datetime | None = None,
    volumes: list[float] | None = None,
) -> list[Candle]:
    start = start or datetime(2025, 1, 1)
    volumes = volumes or [1000.0] * len(closes)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=volumes[i],
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

    def test_weekend_profile_can_relax_volume_filter(self) -> None:
        strategy = MeanReversionStrategy(
            _small_config(
                bollinger_stddev=1.5,
                rsi_recovery_ceiling=100.0,
                volume_filter_mult=1.1,
            ),
            _flat_regime_config(),
            weekend_volume_filter_mult=0.7,
        )
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 70.0]
        volumes = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 950.0]

        weekday_signal = strategy.evaluate(
            build_candles(
                closes,
                start=datetime(2026, 3, 25, 0, 0, tzinfo=KST),
                volumes=volumes,
            )
        )
        weekend_signal = strategy.evaluate(
            build_candles(
                closes,
                start=datetime(2026, 3, 28, 0, 0, tzinfo=KST),
                volumes=volumes,
            )
        )

        self.assertEqual(weekday_signal.reason, "volume_too_low")
        self.assertEqual(weekend_signal.action, SignalAction.BUY)
        self.assertTrue(weekend_signal.context.get("is_weekend"))

    def test_extreme_fear_can_unlock_contrarian_buy(self) -> None:
        strategy = MeanReversionStrategy(
            _small_config(bollinger_stddev=1.5, rsi_recovery_ceiling=25.0),
            _flat_regime_config(),
            fear_greed_extreme_threshold=20,
            fear_greed_entry_rsi_ceiling=40.0,
            fear_greed_band_buffer_pct=0.05,
            fear_greed_confidence_boost=0.1,
        )
        candles = build_candles([100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 95.5])

        baseline_signal = strategy.evaluate(candles)
        strategy.set_macro_snapshot(
            MacroSnapshot(
                overall_regime="neutral",
                overall_confidence=0.7,
                us_regime="neutral",
                us_confidence=0.7,
                kr_regime="neutral",
                kr_confidence=0.7,
                crypto_regime="neutral",
                crypto_confidence=0.7,
                crypto_signals={},
                btc_dominance=55.0,
                kimchi_premium=2.0,
                fear_greed_index=12,
            )
        )
        fear_signal = strategy.evaluate(candles)

        self.assertEqual(baseline_signal.reason, "entry_conditions_not_met")
        self.assertEqual(fear_signal.action, SignalAction.BUY)
        self.assertEqual(fear_signal.reason, "fear_greed_contrarian_buy")
        self.assertEqual(fear_signal.context.get("fear_greed_index"), "12")


if __name__ == "__main__":
    unittest.main()
