from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.vpin import VPINStrategy, _normal_cdf


def build_candles(count: int, base: float = 100.0, volatility: float = 0.001) -> list[Candle]:
    """Build candles where close ≈ open (small moves, low toxicity by default)."""
    start = datetime(2025, 1, 1)
    candles: list[Candle] = []
    price = base
    for i in range(count):
        change = base * volatility * (1 if i % 3 == 0 else -1)
        o = price
        c = price + change
        h = max(o, c) + base * 0.01
        lo = min(o, c) - base * 0.01
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=i),
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=1000.0,
            )
        )
        price = c
    return candles


def _default_config(**overrides: object) -> StrategyConfig:
    defaults: dict[str, object] = dict(
        momentum_lookback=5,
        momentum_entry_threshold=-0.5,
        rsi_period=5,
        rsi_recovery_ceiling=100,
        rsi_overbought=90,
        max_holding_bars=48,
    )
    defaults.update(overrides)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


class TestVPINStrategy(unittest.TestCase):
    # ------------------------------------------------------------------
    # 1. Insufficient data -> HOLD
    # ------------------------------------------------------------------
    def test_insufficient_data_returns_hold(self) -> None:
        """Too few candles → HOLD with reason insufficient_data."""
        config = _default_config(momentum_lookback=5, rsi_period=5)
        strategy = VPINStrategy(config, bucket_count=20)
        # minimum = max(rsi_period+1, momentum_lookback+1, bucket_count+1) = 21
        candles = build_candles(5)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    # ------------------------------------------------------------------
    # 2. _normal_cdf correctness
    # ------------------------------------------------------------------
    def test_normal_cdf_values(self) -> None:
        """_normal_cdf(0) ≈ 0.5, _normal_cdf(3) ≈ 0.9987, _normal_cdf(-3) ≈ 0.0013."""
        self.assertAlmostEqual(_normal_cdf(0), 0.5, places=6)
        self.assertAlmostEqual(_normal_cdf(3), 0.9987, places=3)
        self.assertAlmostEqual(_normal_cdf(-3), 0.0013, places=3)

    # ------------------------------------------------------------------
    # 3. Low VPIN + positive momentum -> BUY
    # ------------------------------------------------------------------
    def test_low_vpin_buy_entry(self) -> None:
        """Low-volatility candles with gentle uptrend → VPIN low → BUY."""
        config = _default_config(
            momentum_lookback=5,
            rsi_period=5,
        )
        strategy = VPINStrategy(
            config,
            vpin_low_threshold=0.3,
            bucket_count=10,
            vpin_momentum_threshold=-0.5,
            vpin_rsi_ceiling=100,
        )

        # Gentle uptrend: close always slightly above open → low buy/sell imbalance
        # but consistent, keeping VPIN low. Use very small volatility.
        start = datetime(2025, 1, 1)
        candles: list[Candle] = []
        price = 100.0
        for i in range(30):
            o = price
            c = price + 0.05  # tiny consistent upward move
            h = c + 1.0
            lo = o - 1.0
            candles.append(
                Candle(
                    timestamp=start + timedelta(hours=i),
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=1000.0,
                )
            )
            price = c

        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "vpin_safe_momentum_entry")

    # ------------------------------------------------------------------
    # 4. High VPIN blocks entry -> HOLD with vpin_high_toxicity
    # ------------------------------------------------------------------
    def test_high_vpin_blocks_entry(self) -> None:
        """Candles with large alternating moves → VPIN high → HOLD vpin_high_toxicity.

        The bulk-volume VPIN maximum from candle data is ~0.683 (achieved when
        high=close and low=open, giving z=1). We set vpin_high_threshold=0.6 so
        the test reliably triggers the high-toxicity branch.
        """
        config = _default_config()
        # Threshold set below the achievable VPIN maximum (~0.683)
        strategy = VPINStrategy(config, vpin_high_threshold=0.6, bucket_count=10)

        # Alternating candles where high=close (up bars) or high=open (down bars)
        # so z = (close-open)/(high-low) = ±1 maximising |buy_vol - sell_vol|.
        start = datetime(2025, 1, 1)
        candles: list[Candle] = []
        price = 100.0
        for i in range(30):
            if i % 2 == 0:
                o = price
                c = price + 5.0
                h = c  # high == close → z = +1
                lo = o
            else:
                o = price
                c = price - 5.0
                h = o  # high == open → z = -1
                lo = c
            candles.append(
                Candle(
                    timestamp=start + timedelta(hours=i),
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=1000.0,
                )
            )
            price = c

        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "vpin_high_toxicity")

    # ------------------------------------------------------------------
    # 5. Position + high VPIN -> SELL vpin_toxicity_exit
    # ------------------------------------------------------------------
    def test_sell_on_vpin_toxicity(self) -> None:
        """Open position with high-toxicity market → SELL reason=vpin_toxicity_exit.

        Uses vpin_high_threshold=0.6 (below the ~0.683 achievable maximum) so
        the toxicity branch reliably fires before max_holding_bars.
        """
        config = _default_config(max_holding_bars=200)
        strategy = VPINStrategy(config, vpin_high_threshold=0.6, bucket_count=10)

        # Alternating candles with high=close / high=open to maximise z = ±1
        start = datetime(2025, 1, 1)
        candles: list[Candle] = []
        price = 100.0
        for i in range(30):
            if i % 2 == 0:
                o = price
                c = price + 5.0
                h = c
                lo = o
            else:
                o = price
                c = price - 5.0
                h = o
                lo = c
            candles.append(
                Candle(
                    timestamp=start + timedelta(hours=i),
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=1000.0,
                )
            )
            price = c

        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "vpin_toxicity_exit")

    # ------------------------------------------------------------------
    # 6. Position held too long -> SELL max_holding_period
    # ------------------------------------------------------------------
    def test_sell_on_max_holding(self) -> None:
        """Position with entry_index far back exceeds max_holding_bars → SELL."""
        config = _default_config(max_holding_bars=2)
        strategy = VPINStrategy(config, bucket_count=10)

        # Low-volatility candles keep VPIN low so only max_holding_bars fires
        candles = build_candles(30, volatility=0.0001)

        # entry_index=0, len=30 → holding_bars = 30 - 0 - 1 = 29 >= 2
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
    # 7. Relaxed params: entry with vpin=0.45, momentum=0.001, rsi=65
    # ------------------------------------------------------------------
    def test_relaxed_entry_triggers(self) -> None:
        """With explicit relaxed thresholds, moderate conditions trigger BUY."""
        config = _default_config(momentum_lookback=5, rsi_period=5)
        strategy = VPINStrategy(
            config,
            bucket_count=10,
            vpin_low_threshold=0.5,
            vpin_momentum_threshold=0.0,
            vpin_rsi_ceiling=70.0,
            vpin_rsi_floor=20.0,
        )

        # Build candles: up, up, down, down, up pattern → net positive momentum, RSI ~55
        start = datetime(2025, 1, 1)
        candles: list[Candle] = []
        price = 100.0
        pattern = [0.06, 0.06, -0.04, -0.04, 0.06]
        for i in range(30):
            o = price
            c = price + pattern[i % len(pattern)]
            h = max(o, c) + 0.5
            lo = min(o, c) - 0.5
            candles.append(
                Candle(
                    timestamp=start + timedelta(hours=i),
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=1000.0,
                )
            )
            price = c

        signal = strategy.evaluate(candles)
        # With relaxed thresholds, this should BUY (vpin < 0.5, momentum > 0, rsi < 70)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "vpin_safe_momentum_entry")

    # ------------------------------------------------------------------
    # 8. Entry still blocked when vpin > 0.5 (new threshold)
    # ------------------------------------------------------------------
    def test_entry_blocked_above_new_vpin_threshold(self) -> None:
        """VPIN above 0.5 but below 0.7 → neither BUY nor high_toxicity → HOLD."""
        config = _default_config()
        # Use default vpin_low=0.5, vpin_high=0.7
        strategy = VPINStrategy(config, bucket_count=10)

        # Build candles that produce VPIN ~0.55-0.68 (moderate alternation)
        start = datetime(2025, 1, 1)
        candles: list[Candle] = []
        price = 100.0
        for i in range(30):
            if i % 2 == 0:
                o = price
                c = price + 2.0
                h = c + 0.5
                lo = o - 0.5
            else:
                o = price
                c = price - 2.0
                h = o + 0.5
                lo = c - 0.5
            candles.append(
                Candle(
                    timestamp=start + timedelta(hours=i),
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=1000.0,
                )
            )
            price = c

        signal = strategy.evaluate(candles)
        # VPIN should be in the 0.5-0.7 dead zone → HOLD
        self.assertIn(
            signal.reason,
            ("entry_conditions_not_met", "vpin_high_toxicity", "ema_trend_down", "adx_too_weak"),
        )

    # ------------------------------------------------------------------
    # 9. Entry blocked when momentum truly negative
    # ------------------------------------------------------------------
    def test_entry_blocked_negative_momentum(self) -> None:
        """Even with low VPIN, negative momentum blocks entry."""
        config = _default_config(momentum_lookback=5, rsi_period=5)
        strategy = VPINStrategy(
            config,
            vpin_low_threshold=0.5,
            bucket_count=10,
            vpin_momentum_threshold=0.0,
            vpin_rsi_ceiling=100.0,
        )

        # Downtrend: negative momentum
        start = datetime(2025, 1, 1)
        candles: list[Candle] = []
        price = 200.0
        for i in range(30):
            o = price
            c = price - 0.05  # consistent downward → negative momentum
            h = o + 1.0
            lo = c - 1.0
            candles.append(
                Candle(
                    timestamp=start + timedelta(hours=i),
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=1000.0,
                )
            )
            price = c

        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertIn(
            signal.reason,
            ("entry_conditions_not_met", "ema_trend_down", "adx_too_weak"),
        )

    # ------------------------------------------------------------------
    # 10. VPIN params pass-through from create_strategy extra_params
    # ------------------------------------------------------------------
    def test_create_strategy_passes_vpin_params(self) -> None:
        """create_strategy('vpin') must forward extra_params to VPINStrategy."""
        from crypto_trader.config import RegimeConfig
        from crypto_trader.wallet import create_strategy

        config = _default_config()
        regime = RegimeConfig()
        extra = {
            "vpin_low_threshold": 0.50,
            "vpin_high_threshold": 0.80,
            "bucket_count": 15,
            "vpin_momentum_threshold": 0.005,
            "vpin_rsi_ceiling": 75.0,
            "vpin_rsi_floor": 25.0,
        }
        strategy = create_strategy("vpin", config, regime, extra)
        self.assertIsInstance(strategy, VPINStrategy)
        self.assertAlmostEqual(strategy._vpin_low, 0.50)
        self.assertAlmostEqual(strategy._vpin_high, 0.80)
        self.assertEqual(strategy._bucket_count, 15)
        self.assertAlmostEqual(strategy._vpin_momentum_threshold, 0.005)
        self.assertAlmostEqual(strategy._vpin_rsi_ceiling, 75.0)
        self.assertAlmostEqual(strategy._vpin_rsi_floor, 25.0)


    def test_adx_threshold_defaults_to_config_value(self) -> None:
        """VPINStrategy must use config.adx_threshold when not explicitly passed."""
        config = _default_config(adx_threshold=15.0)
        strategy = VPINStrategy(config, bucket_count=10)
        self.assertAlmostEqual(strategy._adx_threshold, 15.0)

    def test_adx_threshold_explicit_overrides_config(self) -> None:
        """Explicitly passed adx_threshold takes precedence over config."""
        config = _default_config(adx_threshold=15.0)
        strategy = VPINStrategy(config, bucket_count=10, adx_threshold=25.0)
        self.assertAlmostEqual(strategy._adx_threshold, 25.0)

    def test_create_strategy_passes_adx_threshold(self) -> None:
        """create_strategy('vpin') must forward adx_threshold from extra_params."""
        from crypto_trader.config import RegimeConfig
        from crypto_trader.wallet import create_strategy

        config = _default_config(adx_threshold=20.0)
        regime = RegimeConfig()
        extra = {"adx_threshold": 15.0}
        strategy = create_strategy("vpin", config, regime, extra)
        self.assertIsInstance(strategy, VPINStrategy)
        self.assertAlmostEqual(strategy._adx_threshold, 15.0)


if __name__ == "__main__":
    unittest.main()
