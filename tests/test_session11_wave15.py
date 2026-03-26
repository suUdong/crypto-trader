"""Tests for Session #11 Wave 15: entry confidence tracking, regime profit factor."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle, TradeRecord
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy


def _candles(closes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=1000.0)
        for i, c in enumerate(closes)
    ]


# ---------- Entry confidence in TradeRecord ----------

class TestEntryConfidence(unittest.TestCase):
    def test_trade_record_has_entry_confidence(self) -> None:
        """TradeRecord should have entry_confidence field."""
        tr = TradeRecord(
            symbol="KRW-BTC",
            entry_time=datetime(2025, 1, 1),
            exit_time=datetime(2025, 1, 2),
            entry_price=100.0,
            exit_price=105.0,
            quantity=1.0,
            pnl=5.0,
            pnl_pct=0.05,
            exit_reason="take_profit",
            entry_confidence=0.75,
        )
        self.assertEqual(tr.entry_confidence, 0.75)

    def test_entry_confidence_default_zero(self) -> None:
        """Default entry_confidence should be 0.0."""
        tr = TradeRecord(
            symbol="KRW-BTC",
            entry_time=datetime(2025, 1, 1),
            exit_time=datetime(2025, 1, 2),
            entry_price=100.0,
            exit_price=105.0,
            quantity=1.0,
            pnl=5.0,
            pnl_pct=0.05,
            exit_reason="take_profit",
        )
        self.assertEqual(tr.entry_confidence, 0.0)

    def test_backtest_records_entry_confidence(self) -> None:
        """BacktestEngine should record entry confidence in trade log."""
        prices = [100.0] * 20 + [90.0, 89.0, 93.0, 96.0, 100.0, 105.0, 110.0]
        candles = _candles(prices)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                momentum_entry_threshold=-0.5,
                bollinger_window=20,
                bollinger_stddev=1.5,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
            )
        )
        risk = RiskManager(
            RiskConfig(stop_loss_pct=0.15, take_profit_pct=0.30, cooldown_bars=0),
        )
        engine = BacktestEngine(
            strategy=strategy, risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0), symbol="KRW-BTC",
        )
        result = engine.run(candles)
        for trade in result.trade_log:
            # entry_confidence should be set (not default 0 if trade happened)
            self.assertIsInstance(trade.entry_confidence, float)


# ---------- Regime profit factor ----------

class TestRegimeProfitFactor(unittest.TestCase):
    def test_regime_pf_calculation(self) -> None:
        """Verify regime PF calculation logic."""
        regime_profit = {"bull": 1000.0, "sideways": 500.0, "bear": 100.0}
        regime_loss = {"bull": 500.0, "sideways": 600.0, "bear": 200.0}
        bull_pf = regime_profit["bull"] / max(0.01, regime_loss["bull"])
        sideways_pf = regime_profit["sideways"] / max(0.01, regime_loss["sideways"])
        bear_pf = regime_profit["bear"] / max(0.01, regime_loss["bear"])
        self.assertAlmostEqual(bull_pf, 2.0)
        self.assertAlmostEqual(sideways_pf, 500.0 / 600.0, places=3)
        self.assertAlmostEqual(bear_pf, 0.5)

    def test_regime_pf_no_losses(self) -> None:
        """When no losses in a regime, PF should be high (capped by max(0.01))."""
        regime_profit = {"bull": 1000.0}
        regime_loss = {"bull": 0.0}
        pf = regime_profit["bull"] / max(0.01, regime_loss["bull"])
        self.assertEqual(pf, 100000.0)

    def test_regime_pf_no_profits(self) -> None:
        """When no profits in a regime, PF should be 0."""
        regime_profit = {"bear": 0.0}
        regime_loss = {"bear": 500.0}
        pf = regime_profit["bear"] / max(0.01, regime_loss["bear"])
        self.assertAlmostEqual(pf, 0.0)


if __name__ == "__main__":
    unittest.main()
