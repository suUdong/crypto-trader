"""Tests for Session #11 Wave 4: dynamic stop tightening, Sortino ratio."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine, _sortino_ratio
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle, Position
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy


def _candles(closes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=1000.0)
        for i, c in enumerate(closes)
    ]


# ---------- Dynamic stop tightening ----------

class TestDynamicStopTightening(unittest.TestCase):
    def test_stop_tightens_after_3_losses(self) -> None:
        """After 3 consecutive losses, effective_stop_loss_pct should be 80% of base."""
        risk = RiskManager(RiskConfig(stop_loss_pct=0.03))
        # No losses yet
        self.assertAlmostEqual(risk.effective_stop_loss_pct, 0.03)
        # Record 3 losses
        risk.record_trade(-0.02)
        risk.record_trade(-0.01)
        risk.record_trade(-0.015)
        self.assertAlmostEqual(risk.effective_stop_loss_pct, 0.024)  # 0.03 * 0.8

    def test_stop_resets_on_win(self) -> None:
        """Winning trade should reset consecutive loss counter."""
        risk = RiskManager(RiskConfig(stop_loss_pct=0.03))
        risk.record_trade(-0.02)
        risk.record_trade(-0.01)
        risk.record_trade(-0.015)
        self.assertAlmostEqual(risk.effective_stop_loss_pct, 0.024)
        # Win resets
        risk.record_trade(0.05)
        self.assertAlmostEqual(risk.effective_stop_loss_pct, 0.03)

    def test_stop_normal_with_fewer_than_3_losses(self) -> None:
        """2 consecutive losses should NOT tighten stop."""
        risk = RiskManager(RiskConfig(stop_loss_pct=0.05))
        risk.record_trade(-0.01)
        risk.record_trade(-0.02)
        self.assertAlmostEqual(risk.effective_stop_loss_pct, 0.05)

    def test_exit_reason_uses_tightened_stop(self) -> None:
        """exit_reason should use tightened stop after losing streak."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        # Record 3 losses to tighten stop to 4%
        risk.record_trade(-0.02)
        risk.record_trade(-0.02)
        risk.record_trade(-0.02)
        pos = Position(
            symbol="KRW-BTC", quantity=1.0, entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        # Price at -4.5%: within tightened stop (4%) but outside normal (5%)
        reason = risk.exit_reason(pos, 95.5)
        self.assertEqual(reason, "stop_loss")

    def test_no_trigger_without_tightened_stop(self) -> None:
        """Without losing streak, wider stop should not trigger."""
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, atr_stop_multiplier=0.0),
            atr_stop_multiplier=0.0,
        )
        pos = Position(
            symbol="KRW-BTC", quantity=1.0, entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
        )
        # Price at -4.5%: within normal 5% stop, should NOT trigger
        reason = risk.exit_reason(pos, 95.5)
        self.assertIsNone(reason)


# ---------- Sortino ratio ----------

class TestSortinoRatio(unittest.TestCase):
    def test_sortino_positive_for_uptrend(self) -> None:
        curve = [1000.0 + i * 10.0 for i in range(100)]
        sortino = _sortino_ratio(curve)
        self.assertGreater(sortino, 0)

    def test_sortino_negative_for_downtrend(self) -> None:
        curve = [1000.0 - i * 10.0 for i in range(50)]
        sortino = _sortino_ratio(curve)
        self.assertLess(sortino, 0)

    def test_sortino_zero_for_flat(self) -> None:
        curve = [1000.0] * 100
        sortino = _sortino_ratio(curve)
        self.assertEqual(sortino, 0.0)

    def test_sortino_inf_for_no_downside(self) -> None:
        """Pure uptrend with no negative returns should return inf."""
        curve = [1000.0 + i * 10.0 for i in range(50)]
        sortino = _sortino_ratio(curve)
        self.assertEqual(sortino, float("inf"))

    def test_sortino_on_short_curve(self) -> None:
        self.assertEqual(_sortino_ratio([100.0, 101.0]), 0.0)

    def test_backtest_result_has_sortino(self) -> None:
        candles = _candles([100.0] * 30)
        strategy = CompositeStrategy(StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5))
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(strategy=strategy, risk_manager=risk,
                                config=BacktestConfig(initial_capital=1_000_000.0), symbol="KRW-BTC")
        result = engine.run(candles)
        self.assertIsInstance(result.sortino_ratio, float)

    def test_sortino_greater_than_sharpe_for_low_downside(self) -> None:
        """Sortino should be >= Sharpe when downside is smaller than total vol."""
        from crypto_trader.backtest.engine import _sharpe_ratio
        # Mostly up with few dips
        curve = [1000.0]
        for i in range(100):
            if i % 10 == 5:
                curve.append(curve[-1] * 0.99)  # small dip
            else:
                curve.append(curve[-1] * 1.01)  # up
        sharpe = _sharpe_ratio(curve)
        sortino = _sortino_ratio(curve)
        # Sortino penalizes only downside, so should be >= Sharpe for skewed returns
        if sortino != float("inf"):
            self.assertGreaterEqual(sortino, sharpe)


if __name__ == "__main__":
    unittest.main()
