"""Tests for trailing stop and ATR-based dynamic stop/take-profit."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle, Position
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import create_strategy


def _pos(entry_price: float = 100.0, high_watermark: float = 0.0) -> Position:
    return Position(
        symbol="KRW-BTC",
        quantity=1.0,
        entry_price=entry_price,
        entry_time=datetime(2025, 1, 1),
        entry_index=0,
        high_watermark=high_watermark,
    )


class TestPositionWatermark(unittest.TestCase):
    def test_watermark_defaults_to_entry_price(self) -> None:
        pos = _pos(entry_price=100.0)
        self.assertEqual(pos.high_watermark, 100.0)

    def test_update_watermark_tracks_high(self) -> None:
        pos = _pos(entry_price=100.0)
        pos.update_watermark(110.0)
        self.assertEqual(pos.high_watermark, 110.0)
        pos.update_watermark(105.0)  # lower, no update
        self.assertEqual(pos.high_watermark, 110.0)
        pos.update_watermark(120.0)
        self.assertEqual(pos.high_watermark, 120.0)

    def test_watermark_explicit_value(self) -> None:
        pos = _pos(entry_price=100.0, high_watermark=150.0)
        self.assertEqual(pos.high_watermark, 150.0)


class TestTrailingStop(unittest.TestCase):
    def test_trailing_stop_triggers_after_profit(self) -> None:
        """Price rallies to 120, drops to 110 with 5% trailing → triggers at 114."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50),
            trailing_stop_pct=0.05,
        )
        pos = _pos(entry_price=100.0)
        # Price rises to 120 (updates watermark)
        self.assertIsNone(rm.exit_reason(pos, 120.0))
        self.assertEqual(pos.high_watermark, 120.0)
        # Price drops to 114 = 120 * 0.95 → exactly at trailing stop
        reason = rm.exit_reason(pos, 113.9)
        self.assertEqual(reason, "trailing_stop")

    def test_trailing_stop_not_triggered_without_profit(self) -> None:
        """Trailing stop only triggers when watermark > entry_price."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50),
            trailing_stop_pct=0.05,
        )
        pos = _pos(entry_price=100.0)
        # Price stays at entry, watermark == entry → no trailing stop
        reason = rm.exit_reason(pos, 95.5)
        # Should hit regular stop_loss instead (100 * 0.90 = 90)
        self.assertIsNone(reason)

    def test_trailing_stop_before_fixed_tp(self) -> None:
        """Trailing stop can trigger before fixed take-profit."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50),
            trailing_stop_pct=0.03,
        )
        pos = _pos(entry_price=100.0)
        rm.exit_reason(pos, 130.0)  # watermark = 130
        # 130 * 0.97 = 126.1, price drops to 126 → trailing stop
        reason = rm.exit_reason(pos, 126.0)
        self.assertEqual(reason, "trailing_stop")

    def test_no_trailing_stop_when_disabled(self) -> None:
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.03, take_profit_pct=0.50),  # wide TP
            trailing_stop_pct=0.0,
        )
        pos = _pos(entry_price=100.0)
        rm.exit_reason(pos, 120.0)  # watermark = 120
        reason = rm.exit_reason(pos, 115.0)
        # No trailing stop (disabled), no fixed SL/TP hit
        self.assertIsNone(reason)


class TestATRBasedStops(unittest.TestCase):
    def test_atr_stop_loss(self) -> None:
        """ATR-based stop loss: entry - ATR * multiplier."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.03, take_profit_pct=0.06),
            atr_stop_multiplier=2.0,
        )
        rm.set_atr(500.0)  # ATR = 500
        pos = _pos(entry_price=100_000.0)
        # stop = 100000 - 500*2 = 99000
        self.assertIsNone(rm.exit_reason(pos, 99_100.0))
        reason = rm.exit_reason(pos, 98_900.0)
        self.assertEqual(reason, "atr_stop_loss")

    def test_atr_take_profit(self) -> None:
        """ATR-based take profit: entry + ATR * multiplier * 2 (2:1 R:R)."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.03, take_profit_pct=0.06),
            atr_stop_multiplier=2.0,
        )
        rm.set_atr(500.0)
        pos = _pos(entry_price=100_000.0)
        # tp = 100000 + 500*2*2 = 102000
        self.assertIsNone(rm.exit_reason(pos, 101_900.0))
        reason = rm.exit_reason(pos, 102_100.0)
        self.assertEqual(reason, "atr_take_profit")

    def test_atr_overrides_fixed_stops(self) -> None:
        """When ATR multiplier is set, fixed stops are not used."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.01, take_profit_pct=0.02),  # tight fixed stops
            atr_stop_multiplier=3.0,
        )
        rm.set_atr(1000.0)
        pos = _pos(entry_price=100_000.0)
        # Fixed SL at 99000, but ATR SL at 97000 → price at 99000 should NOT trigger
        reason = rm.exit_reason(pos, 99_000.0)
        self.assertIsNone(reason)
        # ATR SL triggers at 97000
        reason = rm.exit_reason(pos, 96_900.0)
        self.assertEqual(reason, "atr_stop_loss")

    def test_falls_back_to_fixed_when_no_atr(self) -> None:
        """Without ATR data, uses fixed stops."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.03, take_profit_pct=0.06),
            atr_stop_multiplier=2.0,
        )
        # Don't set ATR → falls back to fixed
        pos = _pos(entry_price=100.0)
        reason = rm.exit_reason(pos, 97.0)
        self.assertEqual(reason, "stop_loss")

    def test_atr_with_trailing_stop_combined(self) -> None:
        """ATR stops and trailing stop can coexist — trailing fires first."""
        rm = RiskManager(
            RiskConfig(stop_loss_pct=0.10, take_profit_pct=0.50),
            trailing_stop_pct=0.02,
            atr_stop_multiplier=3.0,
        )
        rm.set_atr(500.0)
        pos = _pos(entry_price=100_000.0)
        # Rally to 105000, watermark = 105000
        rm.exit_reason(pos, 105_000.0)
        # Trailing stop at 105000 * 0.98 = 102900
        # ATR SL at 100000 - 1500 = 98500
        # Price at 102800 triggers trailing before ATR
        reason = rm.exit_reason(pos, 102_800.0)
        self.assertEqual(reason, "trailing_stop")


class TestBacktestWithTrailingStop(unittest.TestCase):
    def test_backtest_runs_with_trailing_stop(self) -> None:
        """Backtest completes without error when trailing stop is enabled."""
        import math
        closes = [100_000.0 + 5000 * math.sin(i * 0.15) for i in range(300)]
        candles = []
        base = datetime(2025, 1, 1)
        for i, c in enumerate(closes):
            prev = closes[i - 1] if i > 0 else c
            candles.append(Candle(
                timestamp=base + timedelta(hours=i),
                open=prev, high=c * 1.02, low=c * 0.98,
                close=c, volume=1000.0,
            ))
        strategy = create_strategy("mean_reversion", StrategyConfig(bollinger_stddev=1.5), RegimeConfig())
        rm = RiskManager(RiskConfig(), trailing_stop_pct=0.03)
        engine = BacktestEngine(strategy=strategy, risk_manager=rm, config=BacktestConfig(), symbol="KRW-BTC")
        result = engine.run(candles)
        self.assertIsInstance(result.total_return_pct, float)
        self.assertGreaterEqual(len(result.equity_curve), 2)

    def test_backtest_runs_with_atr_stops(self) -> None:
        """Backtest completes with ATR-based dynamic stops."""
        import math
        closes = [100_000.0 + 5000 * math.sin(i * 0.15) for i in range(300)]
        candles = []
        base = datetime(2025, 1, 1)
        for i, c in enumerate(closes):
            prev = closes[i - 1] if i > 0 else c
            candles.append(Candle(
                timestamp=base + timedelta(hours=i),
                open=prev, high=c * 1.02, low=c * 0.98,
                close=c, volume=1000.0,
            ))
        strategy = create_strategy("mean_reversion", StrategyConfig(bollinger_stddev=1.5), RegimeConfig())
        rm = RiskManager(RiskConfig(), atr_stop_multiplier=2.0)
        engine = BacktestEngine(strategy=strategy, risk_manager=rm, config=BacktestConfig(), symbol="KRW-BTC")
        result = engine.run(candles)
        self.assertIsInstance(result.total_return_pct, float)


if __name__ == "__main__":
    unittest.main()
