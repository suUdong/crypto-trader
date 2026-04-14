from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.vpin_v2 import VPINV2Strategy
from crypto_trader.wallet import create_strategy


def _default_config(**overrides: object) -> StrategyConfig:
    defaults: dict[str, object] = dict(
        momentum_lookback=5,
        momentum_entry_threshold=-0.5,
        rsi_period=5,
        rsi_recovery_ceiling=100,
        rsi_overbought=90,
        max_holding_bars=48,
        adx_threshold=15.0,
    )
    defaults.update(overrides)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


def _build_candles(
    count: int,
    *,
    base: float = 100.0,
    change: float = 0.05,
    high_pad: float = 1.0,
    low_pad: float = 1.0,
) -> list[Candle]:
    start = datetime(2025, 1, 1)
    candles: list[Candle] = []
    price = base
    for i in range(count):
        direction = 1 if i % 4 != 3 else -0.2
        o = price
        c = price + change * direction
        h = max(o, c) + high_pad
        lo = min(o, c) - low_pad
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


class TestVPINV2Strategy(unittest.TestCase):
    def test_insufficient_data_returns_hold(self) -> None:
        strategy = VPINV2Strategy(_default_config(), bucket_count=20)

        signal = strategy.evaluate(_build_candles(10))

        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_high_vpin_blocks_entry(self) -> None:
        strategy = VPINV2Strategy(
            _default_config(),
            vpin_high_threshold=0.6,
            bucket_count=10,
        )

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

        signal = strategy.evaluate(candles)

        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "vpin_high_toxicity")

    def test_buy_on_relaxed_scored_entry(self) -> None:
        strategy = VPINV2Strategy(
            _default_config(adx_threshold=0.0),
            vpin_low_threshold=0.5,
            bucket_count=10,
            vpin_momentum_threshold=-0.5,
            vpin_rsi_ceiling=100.0,
            adx_threshold=0.0,
            entry_score_threshold=2.0,
            vpin_roc_min=-1.0,
            rsi_delta_min=-100.0,
            ema_slope_min=-1.0,
        )

        signal = strategy.evaluate(_build_candles(40))

        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "vpin_v2_entry_score")
        self.assertGreaterEqual(signal.indicators.get("entry_score", 0.0), 2.0)

    def test_vpin_roc_fail_reason_is_explicit(self) -> None:
        strategy = VPINV2Strategy(
            _default_config(adx_threshold=0.0),
            vpin_low_threshold=0.5,
            bucket_count=10,
            vpin_momentum_threshold=-0.5,
            vpin_rsi_ceiling=100.0,
            adx_threshold=0.0,
            entry_score_threshold=1.0,
            vpin_roc_min=1.0,
            rsi_delta_min=-100.0,
            ema_slope_min=-1.0,
        )

        signal = strategy.evaluate(_build_candles(40))

        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "vpin_roc_fail")

    def test_score_below_min_reason_is_explicit(self) -> None:
        strategy = VPINV2Strategy(
            _default_config(adx_threshold=0.0),
            vpin_low_threshold=0.5,
            bucket_count=10,
            vpin_momentum_threshold=-0.5,
            vpin_rsi_ceiling=100.0,
            adx_threshold=0.0,
            entry_score_threshold=10.0,
            vpin_roc_min=-1.0,
            rsi_delta_min=-100.0,
            ema_slope_min=-1.0,
        )

        signal = strategy.evaluate(_build_candles(40))

        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "score_below_min")

    def test_exit_path_reuses_parent_exit_logic(self) -> None:
        strategy = VPINV2Strategy(_default_config(max_holding_bars=2), bucket_count=10)
        candles = _build_candles(30, change=0.01)
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

    def test_create_strategy_passes_vpin_v2_params(self) -> None:
        strategy = create_strategy(
            "vpin_v2",
            _default_config(),
            RegimeConfig(),
            {
                "entry_score_threshold": 3.4,
                "vpin_roc_lookback": 4,
                "vpin_roc_min": -0.02,
                "rsi_delta_lookback": 5,
                "rsi_delta_min": 2.0,
                "ema_slope_lookback": 6,
                "ema_slope_min": 0.0004,
            },
        )

        self.assertIsInstance(strategy, VPINV2Strategy)
        self.assertAlmostEqual(strategy._entry_score_threshold, 3.4)
        self.assertEqual(strategy._vpin_roc_lookback, 4)
        self.assertAlmostEqual(strategy._vpin_roc_min, -0.02)
        self.assertEqual(strategy._rsi_delta_lookback, 5)
        self.assertAlmostEqual(strategy._rsi_delta_min, 2.0)
        self.assertEqual(strategy._ema_slope_lookback, 6)
        self.assertAlmostEqual(strategy._ema_slope_min, 0.0004)


if __name__ == "__main__":
    unittest.main()
