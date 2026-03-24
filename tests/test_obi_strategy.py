from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, OrderbookEntry, OrderbookSnapshot, Position, SignalAction
from crypto_trader.strategy.obi import OBIStrategy


def build_candles(closes: list[float], opens: list[float] | None = None) -> list[Candle]:
    start = datetime(2025, 1, 1)
    if opens is None:
        opens = [c * 0.99 for c in closes]  # default: bullish candles
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=o,
            high=max(c, o) * 1.01,
            low=min(c, o) * 0.99,
            close=c,
            volume=1000.0,
        )
        for i, (c, o) in enumerate(zip(closes, opens, strict=True))
    ]


def _make_config(**kwargs: object) -> StrategyConfig:
    defaults: dict[str, object] = {
        "rsi_period": 5,
        "rsi_overbought": 80.0,
        "max_holding_bars": 48,
    }
    defaults.update(kwargs)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


class OBIStrategyTests(unittest.TestCase):
    def test_insufficient_data_returns_hold(self) -> None:
        """Fewer candles than rsi_period + 1 → HOLD with reason insufficient_data."""
        config = _make_config(rsi_period=5)
        strategy = OBIStrategy(config)
        # rsi_period=5 → minimum=6; provide only 4 candles
        candles = build_candles([100.0, 101.0, 102.0, 103.0])
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    def test_buy_with_orderbook_bid_imbalance(self) -> None:
        """Orderbook with heavy bids: OBI = (1000-100)/1100 = 0.818 > 0.3 → BUY."""
        config = _make_config(rsi_period=5, rsi_overbought=80.0)
        snapshot = OrderbookSnapshot(
            symbol="KRW-BTC",
            bids=[OrderbookEntry(100, 500), OrderbookEntry(99, 500)],
            asks=[OrderbookEntry(101, 100)],
        )
        provider = MagicMock()
        provider.get_orderbook.return_value = snapshot

        strategy = OBIStrategy(config, orderbook_provider=provider, obi_buy_threshold=0.3)
        # Mixed closes (dip every 4th) keeps RSI ~61 which is below overbought=80
        closes: list[float] = [100.0]
        for i in range(21):
            closes.append(closes[-1] * (0.995 if i % 4 == 3 else 1.002))
        candles = build_candles(closes)
        signal = strategy.evaluate(candles)

        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "obi_strong_bid_imbalance")
        self.assertGreater(signal.confidence, 0.0)

    def test_hold_without_orderbook_flat_candles(self) -> None:
        """No provider + alternating up/down candles → estimated OBI near 0 → HOLD."""
        config = _make_config(rsi_period=5, rsi_overbought=80.0)
        strategy = OBIStrategy(config, obi_buy_threshold=0.3)

        # Alternate: bullish then bearish so buy_volume ≈ sell_volume → OBI near 0
        closes = [100.0] * 22
        opens = []
        for i in range(22):
            if i % 2 == 0:
                opens.append(closes[i] * 1.01)  # bearish: open > close
            else:
                opens.append(closes[i] * 0.99)  # bullish: open < close
        candles = build_candles(closes, opens)

        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "entry_conditions_not_met")

    def test_sell_on_ask_imbalance(self) -> None:
        """Position open + orderbook with heavy asks: OBI well below -0.3 → SELL."""
        config = _make_config(rsi_period=5, rsi_overbought=80.0, max_holding_bars=48)
        snapshot = OrderbookSnapshot(
            symbol="KRW-BTC",
            bids=[OrderbookEntry(99, 100)],
            asks=[OrderbookEntry(100, 500), OrderbookEntry(101, 500)],
        )
        provider = MagicMock()
        provider.get_orderbook.return_value = snapshot

        strategy = OBIStrategy(config, orderbook_provider=provider, obi_sell_threshold=-0.3)
        candles = build_candles([100.0] * 22)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=20,  # only 1 bar held → not max_holding_bars
        )

        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "obi_strong_ask_imbalance")

    def test_sell_on_max_holding(self) -> None:
        """Position at index 0, max_holding_bars=2 -> SELL."""
        config = _make_config(rsi_period=5, rsi_overbought=80.0, max_holding_bars=2)
        strategy = OBIStrategy(config)

        candles = build_candles([100.0] * 22)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,  # holding_bars = 22 - 0 - 1 = 21 >= 2
        )

        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")

    def test_candle_obi_estimation_bullish(self) -> None:
        """No provider, all bullish bodies -> OBI=1.0 -> BUY."""
        config = _make_config(rsi_period=5, rsi_overbought=80.0)
        strategy = OBIStrategy(config, obi_buy_threshold=0.3)

        # Mixed closes (dip every 4th) keeps RSI ~70 which is below overbought=80.
        # open = close * 0.99 always ensures close > open (bullish body) on every candle.
        # The last 5 candles used by _estimate_obi_from_candles will all be bullish → OBI = 1.0.
        closes: list[float] = [100.0]
        for i in range(21):
            closes.append(closes[-1] * (0.995 if i % 4 == 3 else 1.003))
        opens = [c * 0.99 for c in closes]
        candles = build_candles(closes, opens)

        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "obi_strong_bid_imbalance")


if __name__ == "__main__":
    unittest.main()
