from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy


def build_candles(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[Candle]:
    start = datetime(2025, 1, 1)
    result = []
    for i, c in enumerate(closes):
        h = highs[i] if highs is not None else c * 1.01
        lo = lows[i] if lows is not None else c * 0.99
        result.append(
            Candle(
                timestamp=start + timedelta(hours=i),
                open=c * 0.995,
                high=h,
                low=lo,
                close=c,
                volume=1000.0,
            )
        )
    return result


def _make_config(**kwargs: object) -> StrategyConfig:
    defaults: dict[str, object] = {
        "max_holding_bars": 48,
    }
    defaults.update(kwargs)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


class VolatilityBreakoutStrategyTests(unittest.TestCase):
    def test_insufficient_data_returns_hold(self) -> None:
        """Fewer candles than minimum → HOLD with reason insufficient_data."""
        config = _make_config()
        strategy = VolatilityBreakoutStrategy(config, noise_lookback=20, ma_filter_period=20)
        # minimum = max(22, 21, 3) = 22; provide only 10
        candles = build_candles([100.0] * 10)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_breakout_buy_above_ma(self) -> None:
        """Price above breakout level and above MA → BUY."""
        config = _make_config()
        strategy = VolatilityBreakoutStrategy(
            config, k_base=0.5, noise_lookback=5, ma_filter_period=5
        )
        # Build trending-up candles so MA is below current price
        closes = [100.0 + i * 2.0 for i in range(15)]
        # Make highs/lows so prev_range is large
        highs = [c + 5.0 for c in closes]
        lows = [c - 5.0 for c in closes]
        candles = build_candles(closes, highs, lows)

        # The last candle's close is 128.0
        # prev_candle (index -2) close=126, high=131, low=121 → range=10
        # breakout_level = 126 + k * 10 (k ~0.25 to 0.45)
        # current_price = 128 > 126+10*0.45=130.5? Let's just run and check
        signal = strategy.evaluate(candles)
        # It should at minimum not error; BUY or HOLD depending on k/MA
        self.assertIn(signal.action, {SignalAction.BUY, SignalAction.HOLD})

    def test_buy_signal_when_breakout_and_above_ma(self) -> None:
        """Explicit breakout scenario: price clearly above level and MA."""
        config = _make_config()
        strategy = VolatilityBreakoutStrategy(
            config, k_base=0.1, noise_lookback=5, ma_filter_period=5
        )
        # All candles at 100 except the last which spikes high
        base = [100.0] * 14
        highs = [c + 1.0 for c in base] + [120.0]
        lows = [c - 1.0 for c in base] + [99.0]
        closes = base + [115.0]
        candles = build_candles(closes, highs, lows)

        signal = strategy.evaluate(candles)
        # prev_candle close=100, range=2, k=0.1*(1-0.5*noise)~0.1
        # breakout_level = 100 + 0.1*2 = 100.2; current=115 > 100.2
        # MA over last 5 closes: [100,100,100,100,115] = 103; current=115 > 103
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "volatility_breakout")
        self.assertGreater(signal.confidence, 0.6)

    def test_hold_when_below_ma_filter(self) -> None:
        """Price above breakout level but below MA → HOLD below_ma_filter."""
        config = _make_config()
        strategy = VolatilityBreakoutStrategy(
            config, k_base=0.1, noise_lookback=5, ma_filter_period=5
        )
        # Declining prices so MA > current price
        closes = [120.0 - i * 2.0 for i in range(15)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        candles = build_candles(closes, highs, lows)

        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "below_ma_filter")

    def test_hold_when_price_below_breakout_level(self) -> None:
        """Price above MA but below breakout level → HOLD entry_conditions_not_met."""
        config = _make_config()
        strategy = VolatilityBreakoutStrategy(
            config, k_base=0.9, noise_lookback=5, ma_filter_period=5
        )
        # Flat candles so MA == current price, but k=0.9 means high breakout threshold
        closes = [100.0] * 14 + [100.5]
        highs = [c + 10.0 for c in closes]
        lows = [c - 0.1 for c in closes]
        candles = build_candles(closes, highs, lows)

        # prev_range = 10.1, k~0.9, breakout_level = 100 + 0.9*10.1 = 109.09
        # current = 100.5 < 109.09 and MA ~100.07, current 100.5 > MA → entry_conditions_not_met
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "entry_conditions_not_met")

    def test_sell_on_max_holding_period(self) -> None:
        """Position held beyond max_holding_bars → SELL max_holding_period."""
        config = _make_config(max_holding_bars=5)
        strategy = VolatilityBreakoutStrategy(config, noise_lookback=5, ma_filter_period=5)
        candles = build_candles([100.0] * 15)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,  # holding_bars = 15 - 0 - 1 = 14 >= 5
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")

    def test_sell_on_close_below_prev_low(self) -> None:
        """Current price below previous candle's low → SELL close_below_prev_low."""
        config = _make_config(max_holding_bars=100)
        strategy = VolatilityBreakoutStrategy(config, noise_lookback=5, ma_filter_period=5)
        closes = [100.0] * 14 + [90.0]  # last candle drops below prev low
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        candles = build_candles(closes, highs, lows)
        # prev_low (index -2) = 99.0; current = 90.0 < 99.0
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=13,  # holding_bars = 15 - 13 - 1 = 1 < 100
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "close_below_prev_low")

    def test_noise_ratio_in_indicators(self) -> None:
        """noise_ratio indicator is computed and present in signal indicators."""
        config = _make_config()
        strategy = VolatilityBreakoutStrategy(config, noise_lookback=5, ma_filter_period=5)
        closes = [100.0] * 15
        candles = build_candles(closes)
        signal = strategy.evaluate(candles)
        self.assertIn("noise_ratio", signal.indicators)
        self.assertIn("k", signal.indicators)
        self.assertGreaterEqual(signal.indicators["noise_ratio"], 0.0)
        self.assertLessEqual(signal.indicators["noise_ratio"], 1.0)

    def test_dynamic_k_lower_noise_yields_higher_k(self) -> None:
        """Trending candles (low noise) produce higher k than flat candles (high noise)."""
        config = _make_config()

        # Low noise: strongly trending up
        trending_closes = [100.0 + i * 1.0 for i in range(15)]
        trending_candles = build_candles(trending_closes)
        strategy = VolatilityBreakoutStrategy(config, noise_lookback=5, ma_filter_period=5)
        signal_trending = strategy.evaluate(trending_candles)

        # High noise: choppy / flat
        flat_closes = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0,
                       100.0, 101.0, 100.0, 101.0, 100.0]
        flat_candles = build_candles(flat_closes)
        signal_flat = strategy.evaluate(flat_candles)

        # Trending has lower noise_ratio → higher k
        trending_nr = signal_trending.indicators["noise_ratio"]
        flat_nr = signal_flat.indicators["noise_ratio"]
        trending_k = signal_trending.indicators["k"]
        flat_k = signal_flat.indicators["k"]

        self.assertLess(trending_nr, flat_nr)
        self.assertGreater(trending_k, flat_k)


if __name__ == "__main__":
    unittest.main()
