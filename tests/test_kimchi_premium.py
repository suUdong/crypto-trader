from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from crypto_trader.config import StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.strategy.kimchi_premium import KimchiPremiumStrategy


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


def _make_strategy(
    binance_price: float | None = 78.0,
    fx_rate: float | None = 1300.0,
    **config_overrides: object,
) -> KimchiPremiumStrategy:
    """Build a KimchiPremiumStrategy with mocked external clients."""
    defaults: dict[str, object] = dict(rsi_period=14, max_holding_bars=48)
    defaults.update(config_overrides)
    config = StrategyConfig(**defaults)  # type: ignore[arg-type]

    mock_binance = MagicMock()
    mock_binance.get_btc_usdt_price.return_value = binance_price
    mock_fx = MagicMock()
    mock_fx.get_usd_krw_rate.return_value = fx_rate

    return KimchiPremiumStrategy(config, binance_client=mock_binance, fx_client=mock_fx)


# 30 flat candles at a given close price — enough for RSI(14) to have data
def _flat_closes(price: float, count: int = 30) -> list[float]:
    return [price] * count


class TestKimchiPremiumStrategy(unittest.TestCase):
    # ------------------------------------------------------------------
    # 1. Insufficient data -> HOLD
    # ------------------------------------------------------------------
    def test_insufficient_data_returns_hold(self) -> None:
        """Fewer candles than rsi_period + 1 → HOLD reason=insufficient_data."""
        strategy = _make_strategy(rsi_period=14)
        # rsi_period=14, minimum=15; give only 5
        candles = build_candles([100_000.0] * 5)
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "insufficient_data")

    # ------------------------------------------------------------------
    # 2. Contrarian BUY when premium < -1%
    # ------------------------------------------------------------------
    def test_contrarian_buy_on_negative_premium(self) -> None:
        """upbit=100000, binance=78.0, fx=1300 → global=101400, premium≈-1.38% → BUY."""
        # global_krw = 78.0 * 1300.0 = 101_400
        # premium = (100_000 - 101_400) / 101_400 ≈ -0.0138 (< -0.01)
        strategy = _make_strategy(binance_price=78.0, fx_rate=1300.0)
        candles = build_candles(_flat_closes(100_000.0))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "kimchi_premium_contrarian_buy")
        self.assertIn("kimchi_premium", signal.indicators)
        self.assertLess(signal.indicators["kimchi_premium"], -0.01)

    # ------------------------------------------------------------------
    # 3. HOLD when premium > 5% (no entry allowed)
    # ------------------------------------------------------------------
    def test_hold_when_premium_too_high(self) -> None:
        """upbit=110000, binance=78.0, fx=1300 → global=101400, premium≈+8.5% → HOLD."""
        # global_krw = 78.0 * 1300.0 = 101_400
        # premium = (110_000 - 101_400) / 101_400 ≈ +0.0848 (> 0.05)
        strategy = _make_strategy(binance_price=78.0, fx_rate=1300.0)
        candles = build_candles(_flat_closes(110_000.0))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "premium_too_high_for_entry")
        self.assertIn("kimchi_premium", signal.indicators)
        self.assertGreater(signal.indicators["kimchi_premium"], 0.05)

    # ------------------------------------------------------------------
    # 4. Safe zone BUY: 0% < premium < 5%, RSI in range
    # ------------------------------------------------------------------
    def test_safe_zone_buy_with_rsi(self) -> None:
        """Premium ~2% with open RSI window -> BUY safe zone."""
        # global_krw = 78.0 * 1300.0 = 101_400
        # upbit = 103_428 → premium = (103_428 - 101_400) / 101_400 ≈ +0.02 (2%)
        upbit_price = 103_428.0
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_period=14,
            rsi_oversold_floor=0.0,
            rsi_recovery_ceiling=100.0,
        )
        candles = build_candles(_flat_closes(upbit_price))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertEqual(signal.reason, "kimchi_premium_safe_zone_rsi_entry")
        premium = signal.indicators["kimchi_premium"]
        self.assertGreater(premium, 0.0)
        self.assertLess(premium, 0.05)

    # ------------------------------------------------------------------
    # 5. SELL when position open and premium >= 7%
    # ------------------------------------------------------------------
    def test_sell_on_premium_overheated(self) -> None:
        """Position open + premium >= 7% → SELL reason=kimchi_premium_overheated."""
        # global_krw = 78.0 * 1300.0 = 101_400
        # upbit = 109_000 → premium = (109_000 - 101_400) / 101_400 ≈ +0.075 (7.5%)
        upbit_price = 109_000.0
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_overbought=90.0,   # high threshold so RSI doesn't fire first
            max_holding_bars=1000,
        )
        candles = build_candles(_flat_closes(upbit_price))
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=upbit_price,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "kimchi_premium_overheated")
        self.assertGreaterEqual(signal.indicators["kimchi_premium"], 0.07)

    # ------------------------------------------------------------------
    # 6. HOLD when binance price unavailable (None)
    # ------------------------------------------------------------------
    def test_hold_when_data_unavailable(self) -> None:
        """Binance returns None -> HOLD premium_data_unavailable."""
        strategy = _make_strategy(binance_price=None, fx_rate=1300.0)
        candles = build_candles(_flat_closes(100_000.0))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertEqual(signal.reason, "premium_data_unavailable")

    # ------------------------------------------------------------------
    # 7. SELL on max_holding_bars regardless of premium
    # ------------------------------------------------------------------
    def test_sell_on_max_holding_bars(self) -> None:
        """Position entered at index 0 with max_holding_bars=2 → SELL after enough candles."""
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            max_holding_bars=2,
        )
        closes = _flat_closes(100_000.0, count=30)
        candles = build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100_000.0,
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        # holding_bars = len(candles) - 0 - 1 = 29 >= 2
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")

    # ------------------------------------------------------------------
    # 8. SELL on RSI overbought with position open
    # ------------------------------------------------------------------
    def test_sell_on_rsi_overbought(self) -> None:
        """Rising prices → RSI near 100 > rsi_overbought=30 → SELL reason=rsi_overbought."""
        # Use a premium in the neutral zone (0-5%) so it doesn't fire first
        # global_krw = 78.0 * 1300.0 = 101_400; upbit ~103_428 → premium ~2%
        upbit_price = 103_428.0
        strategy = _make_strategy(
            binance_price=78.0,
            fx_rate=1300.0,
            rsi_overbought=30.0,   # very low threshold — rising prices breach it easily
            max_holding_bars=1000,
        )
        # Steadily rising prices ensure RSI is high (all gains, no losses → RSI=100)
        closes = [upbit_price + i * 100 for i in range(30)]
        candles = build_candles(closes)
        position = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=closes[0],
            entry_time=candles[0].timestamp,
            entry_index=0,
        )
        signal = strategy.evaluate(candles, position)
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "rsi_overbought")


if __name__ == "__main__":
    unittest.main()
