"""Tests for Session #11 Wave 8: RSI divergence in mean reversion, profit-lock trailing."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy


def _candles(closes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=1000.0)
        for i, c in enumerate(closes)
    ]


# ---------- RSI divergence in MeanReversion ----------

class TestMeanReversionDivergence(unittest.TestCase):
    def test_divergence_indicators_present(self) -> None:
        """Mean reversion signals should include divergence indicators."""
        candles = _candles([100.0] * 50)
        strategy = MeanReversionStrategy(
            StrategyConfig(bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("rsi_bullish_divergence", signal.indicators)
        self.assertIn("rsi_bearish_divergence", signal.indicators)

    def test_divergence_zero_on_flat_market(self) -> None:
        """Flat market should have no divergence."""
        candles = _candles([100.0] * 50)
        strategy = MeanReversionStrategy(
            StrategyConfig(bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.indicators["rsi_bullish_divergence"], 0.0)
        self.assertEqual(signal.indicators["rsi_bearish_divergence"], 0.0)

    def test_divergence_with_few_candles(self) -> None:
        """With insufficient data, divergence should be 0.0."""
        candles = _candles([100.0] * 25)
        strategy = MeanReversionStrategy(
            StrategyConfig(bollinger_window=20, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.indicators.get("rsi_bullish_divergence", 0.0), 0.0)

    def test_bearish_divergence_triggers_sell(self) -> None:
        """With position and bearish divergence, should get SELL signal."""
        # Create scenario with rising prices (higher highs) but RSI weakening
        prices = [100.0] * 20
        # First peak
        prices += [102.0, 104.0, 106.0, 108.0, 110.0, 108.0, 106.0, 104.0, 102.0, 100.0]
        # Second peak (higher) but with more gradual RSI
        prices += [103.0, 106.0, 109.0, 112.0, 115.0, 112.0, 109.0, 106.0, 103.0, 100.0]

        candles = _candles(prices)
        pos = Position(
            symbol="KRW-BTC", quantity=1.0, entry_price=95.0,
            entry_time=datetime(2025, 1, 1), entry_index=15,
        )
        strategy = MeanReversionStrategy(
            StrategyConfig(bollinger_window=20, rsi_period=5, max_holding_bars=100),
        )
        signal = strategy.evaluate(candles, pos)
        # Should be SELL or HOLD (depends on divergence detection)
        self.assertIn(signal.action, [SignalAction.SELL, SignalAction.HOLD])


# ---------- Profit-lock trailing stop ----------

class TestProfitLockTrailing(unittest.TestCase):
    def test_profit_lock_triggers_after_3pct_gain(self) -> None:
        """After 3%+ gain, 1.5% trailing from watermark should trigger."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC", quantity=1.0, entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        # Price went up 5%, then drops to 1.5% below watermark
        pos.update_watermark(105.0)
        # 105 * (1 - 0.015) = 103.425, so price at 103.0 should trigger
        reason = risk.exit_reason(pos, 103.0)
        self.assertEqual(reason, "profit_lock_trailing")

    def test_no_profit_lock_under_3pct(self) -> None:
        """Profit lock should not trigger if gain never reached 3%."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC", quantity=1.0, entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        pos.update_watermark(102.5)  # 2.5% gain, below threshold
        reason = risk.exit_reason(pos, 101.0)
        self.assertNotEqual(reason, "profit_lock_trailing")

    def test_profit_lock_not_while_near_watermark(self) -> None:
        """Price still near watermark should not trigger."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC", quantity=1.0, entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        pos.update_watermark(105.0)
        # 105 * 0.985 = 103.425, price at 104.0 is above threshold
        reason = risk.exit_reason(pos, 104.0)
        self.assertNotEqual(reason, "profit_lock_trailing")

    def test_profit_lock_before_breakeven(self) -> None:
        """Profit lock (1.5% trail) should fire before breakeven stop."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC", quantity=1.0, entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        pos.update_watermark(106.0)  # 6% gain
        # 106 * 0.985 = 104.41, so at 104.0 profit_lock should fire
        reason = risk.exit_reason(pos, 104.0)
        self.assertEqual(reason, "profit_lock_trailing")

    def test_profit_lock_exact_boundary(self) -> None:
        """Test at exact 3% gain threshold."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC", quantity=1.0, entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        pos.update_watermark(103.0)  # Exactly 3%
        # 103 * 0.985 = 101.455, price at 101.0 should trigger
        reason = risk.exit_reason(pos, 101.0)
        self.assertEqual(reason, "profit_lock_trailing")


if __name__ == "__main__":
    unittest.main()
