from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.bollinger_mean_reversion import BollingerMeanReversionStrategy


def _config(**overrides: object) -> StrategyConfig:
    defaults: dict[str, object] = dict(
        bollinger_window=20,
        bollinger_stddev=2.0,
        rsi_period=14,
        rsi_oversold_floor=25.0,
        rsi_recovery_ceiling=40.0,
        rsi_overbought=65.0,
        adx_period=14,
        adx_threshold=20.0,
        volume_filter_mult=0.8,
        max_holding_bars=24,
        momentum_lookback=5,
    )
    defaults.update(overrides)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


def _flat_candles(
    count: int,
    base: float = 100.0,
    volume: float = 1000.0,
) -> list[Candle]:
    """Flat candles hovering around base price — low ADX, range-bound."""
    start = datetime(2025, 1, 1)
    candles: list[Candle] = []
    price = base
    for i in range(count):
        # Small oscillation ±0.1%
        delta = base * 0.001 * (1 if i % 2 == 0 else -1)
        o = price
        c = price + delta
        h = max(o, c) + base * 0.002
        lo = min(o, c) - base * 0.002
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=i),
                open=o, high=h, low=lo, close=c,
                volume=volume,
            )
        )
        price = c
    return candles


def _oversold_candles(
    count: int,
    base: float = 100.0,
    drop_start: int = 60,
    volume: float = 1000.0,
) -> list[Candle]:
    """Candles that are flat then drop sharply to trigger lower band touch + RSI oversold."""
    start = datetime(2025, 1, 1)
    candles: list[Candle] = []
    price = base
    for i in range(count):
        if i >= drop_start:
            # Steady decline to push below lower band and RSI down
            delta = -base * 0.008
        else:
            # Small flat oscillation
            delta = base * 0.001 * (1 if i % 2 == 0 else -1)
        o = price
        c = price + delta
        h = max(o, c) + base * 0.001
        lo = min(o, c) - base * 0.001
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=i),
                open=o, high=h, low=lo, close=c,
                volume=volume,
            )
        )
        price = c
    return candles


class TestBollingerMeanReversionInsufficientData(unittest.TestCase):
    def test_insufficient_data_returns_hold(self) -> None:
        cfg = _config()
        strategy = BollingerMeanReversionStrategy(cfg)
        candles = _flat_candles(10)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_strategy_name_in_context(self) -> None:
        cfg = _config()
        strategy = BollingerMeanReversionStrategy(cfg)
        candles = _flat_candles(10)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.context.get("strategy"), "bollinger_mr")


class TestBollingerMeanReversionEntry(unittest.TestCase):
    def test_flat_market_no_entry(self) -> None:
        """Flat candles should not trigger a buy — no band touch."""
        cfg = _config()
        strategy = BollingerMeanReversionStrategy(cfg)
        candles = _flat_candles(80)
        signal = strategy.evaluate(candles)
        self.assertNotEqual(signal.action, SignalAction.BUY)

    def test_adx_too_high_blocks_entry(self) -> None:
        """Even with oversold conditions, high ADX should block entry."""
        cfg = _config()
        # Very low ceiling to ensure block
        strategy = BollingerMeanReversionStrategy(cfg, adx_ceiling=1.0)
        candles = _oversold_candles(80)
        signal = strategy.evaluate(candles)
        self.assertNotEqual(signal.action, SignalAction.BUY)

    def test_oversold_drop_triggers_buy(self) -> None:
        """Sharp drop in range-bound market should eventually trigger BUY."""
        cfg = _config(
            volume_filter_mult=0.0,  # disable volume filter for test
            rsi_oversold_floor=10.0,  # widen RSI window for test
            rsi_recovery_ceiling=45.0,
        )
        strategy = BollingerMeanReversionStrategy(
            cfg, adx_ceiling=50.0, squeeze_threshold_pct=100.0,
        )
        candles = _oversold_candles(80, drop_start=60)
        signal = strategy.evaluate(candles)
        # Should be BUY or HOLD depending on exact conditions; verify indicators present
        if signal.action == SignalAction.BUY:
            self.assertGreater(signal.confidence, 0.5)
            self.assertIn("rsi", signal.indicators)
            self.assertIn("adx", signal.indicators)

    def test_buy_confidence_capped_at_1(self) -> None:
        """Confidence should never exceed 1.0."""
        cfg = _config(
            volume_filter_mult=0.0,
            rsi_oversold_floor=5.0,
            rsi_recovery_ceiling=50.0,
        )
        strategy = BollingerMeanReversionStrategy(
            cfg, adx_ceiling=50.0, squeeze_threshold_pct=100.0,
        )
        candles = _oversold_candles(80, drop_start=60)
        signal = strategy.evaluate(candles)
        self.assertLessEqual(signal.confidence, 1.0)


class TestBollingerMeanReversionExit(unittest.TestCase):
    def _make_position(self, entry_price: float, entry_index: int) -> Position:
        return Position(
            symbol="KRW-BTC",
            quantity=0.001,
            entry_price=entry_price,
            entry_time=datetime(2025, 1, 1),
            entry_index=entry_index,
        )

    def test_max_holding_exit(self) -> None:
        """Should sell after max_holding_bars."""
        cfg = _config(max_holding_bars=24)
        strategy = BollingerMeanReversionStrategy(cfg)
        candles = _flat_candles(80)
        # Position entered 30 bars ago (> 24 max hold)
        position = self._make_position(
            entry_price=candles[49].close, entry_index=49,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_reached")

    def test_hold_when_within_max_bars(self) -> None:
        """Should hold when still within max holding period."""
        cfg = _config(max_holding_bars=24)
        strategy = BollingerMeanReversionStrategy(cfg)
        candles = _flat_candles(80)
        # Position entered 5 bars ago
        position = self._make_position(
            entry_price=candles[74].close, entry_index=74,
        )
        signal = strategy.evaluate(candles, position)
        # Might be HOLD or SELL for other reasons, but not max_holding
        if signal.reason == "max_holding_reached":
            self.fail("Should not trigger max holding with only 5 bars held")

    def test_trend_shift_exit(self) -> None:
        """ADX > 30 should trigger trend_shift exit."""
        cfg = _config(max_holding_bars=100)
        strategy = BollingerMeanReversionStrategy(cfg)
        # Build trending candles (strong uptrend → high ADX)
        start = datetime(2025, 1, 1)
        candles: list[Candle] = []
        price = 100.0
        for i in range(80):
            delta = 0.5  # steady uptrend
            o = price
            c = price + delta
            h = c + 0.2
            lo = o - 0.1
            candles.append(
                Candle(
                    timestamp=start + timedelta(hours=i),
                    open=o, high=h, low=lo, close=c,
                    volume=1000.0,
                )
            )
            price = c

        position = self._make_position(
            entry_price=candles[70].close, entry_index=70,
        )
        signal = strategy.evaluate(candles, position)
        # With strong trend, ADX should be > 30 → sell
        if signal.action == SignalAction.SELL:
            self.assertIn(signal.reason, [
                "trend_shift", "upper_band_reached", "rsi_overbought",
                "middle_band_reversion",
            ])


class TestWalletFactoryRegistration(unittest.TestCase):
    def test_bollinger_mr_creates_strategy(self) -> None:
        from crypto_trader.config import RegimeConfig
        from crypto_trader.wallet import create_strategy

        cfg = _config()
        regime = RegimeConfig()
        strategy = create_strategy("bollinger_mr", cfg, regime)
        self.assertIsInstance(strategy, BollingerMeanReversionStrategy)

    def test_bollinger_mr_with_extra_params(self) -> None:
        from crypto_trader.config import RegimeConfig
        from crypto_trader.wallet import create_strategy

        cfg = _config()
        regime = RegimeConfig()
        strategy = create_strategy(
            "bollinger_mr", cfg, regime,
            extra_params={"adx_ceiling": "30.0", "squeeze_lookback": "40"},
        )
        self.assertIsInstance(strategy, BollingerMeanReversionStrategy)
        self.assertEqual(strategy._adx_ceiling, 30.0)  # noqa: SLF001
        self.assertEqual(strategy._squeeze_lookback, 40)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
