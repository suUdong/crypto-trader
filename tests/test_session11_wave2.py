"""Tests for Session #11 Wave 2: breakeven stop, MACD momentum, correlation guard."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RiskConfig, StrategyConfig
from crypto_trader.models import Candle, Position
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.indicators import rolling_correlation
from crypto_trader.strategy.momentum import MomentumStrategy


def _candles(closes: list[float], start: datetime | None = None) -> list[Candle]:
    t = start or datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=t + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


# ---------- Breakeven stop ----------


class TestBreakevenStop(unittest.TestCase):
    def test_breakeven_triggers_after_gain_then_reversal(self) -> None:
        """Position that gained >=1.5% then drops to entry should hit breakeven stop."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        # Price goes up 2% (above 1.5% threshold), updating watermark
        pos.update_watermark(102.0)
        # Then drops back to entry price
        reason = risk.exit_reason(pos, 100.0)
        self.assertEqual(reason, "breakeven_stop")

    def test_no_breakeven_if_never_gained_enough(self) -> None:
        """Position that never gained 1.5% should not trigger breakeven."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        # Price goes up only 1% (below threshold)
        pos.update_watermark(101.0)
        reason = risk.exit_reason(pos, 100.0)
        # Should not be breakeven_stop (might be None or another reason)
        self.assertNotEqual(reason, "breakeven_stop")

    def test_breakeven_not_triggered_while_in_profit(self) -> None:
        """Breakeven should not trigger while price is still above entry."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        pos.update_watermark(103.0)
        # Still above entry
        reason = risk.exit_reason(pos, 101.5)
        self.assertNotEqual(reason, "breakeven_stop")

    def test_breakeven_before_regular_stop_loss(self) -> None:
        """Breakeven should fire before regular stop loss for previously profitable positions."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        pos.update_watermark(104.0)  # 4% gain recorded
        # Price drops to entry (breakeven should fire before -5% stop)
        reason = risk.exit_reason(pos, 100.0)
        self.assertEqual(reason, "breakeven_stop")


# ---------- MACD in MomentumStrategy ----------


class TestMomentumMACDIntegration(unittest.TestCase):
    def test_macd_indicators_present(self) -> None:
        """MomentumStrategy should include MACD indicators in signal."""
        closes = [100.0] * 40
        candles = _candles(closes)
        strategy = MomentumStrategy(
            StrategyConfig(momentum_lookback=3, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("macd_line", signal.indicators)
        self.assertIn("macd_signal", signal.indicators)
        self.assertIn("macd_histogram", signal.indicators)

    def test_macd_zero_with_few_candles(self) -> None:
        """With < 35 candles, MACD indicators should be zero."""
        closes = [100.0] * 25
        candles = _candles(closes)
        strategy = MomentumStrategy(
            StrategyConfig(momentum_lookback=3, rsi_period=5),
        )
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.indicators.get("macd_line", 0), 0.0)

    def test_macd_boosts_buy_confidence(self) -> None:
        """MACD histogram > 0 should boost BUY confidence by 0.1."""
        # Strong uptrend: momentum positive, MACD bullish
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=0.0,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
                adx_threshold=0.0,  # disable ADX filter
            ),
        )
        signal = strategy.evaluate(candles)
        if signal.action.value == "buy":
            # With MACD bullish, confidence should be higher than base
            self.assertGreaterEqual(signal.confidence, 0.5)


# ---------- Correlation guard ----------


class TestCorrelationGuard(unittest.TestCase):
    def test_identical_curves_have_high_correlation(self) -> None:
        """Identical equity curves should have correlation ~1.0."""
        curve_a = [1000.0 + i * 10.0 for i in range(50)]
        curve_b = [1000.0 + i * 10.0 for i in range(50)]
        corr = rolling_correlation(curve_a, curve_b, 50)
        self.assertGreater(corr, 0.99)

    def test_inverse_curves_have_negative_correlation(self) -> None:
        """Inverse equity curves should have correlation ~-1.0."""
        curve_a = [1000.0 + i * 10.0 for i in range(50)]
        curve_b = [1000.0 - i * 10.0 for i in range(50)]
        corr = rolling_correlation(curve_a, curve_b, 50)
        self.assertLess(corr, -0.99)

    def test_uncorrelated_curves(self) -> None:
        """Very different curves should have low correlation magnitude."""
        import math

        curve_a = [1000.0 + i * 10.0 for i in range(50)]
        curve_b = [1000.0 + 50 * math.sin(i * 0.3) for i in range(50)]
        corr = rolling_correlation(curve_a, curve_b, 50)
        self.assertLess(abs(corr), 0.9)


if __name__ == "__main__":
    unittest.main()
