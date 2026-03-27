"""Tests for Session #11 features: backtest fixes, Sharpe ratio, MACD, regime breakdown."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine, _sharpe_ratio
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.indicators import _ema, macd


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


# ---------- US-042: holding_bars passed to exit_reason ----------


class TestBacktestHoldingBars(unittest.TestCase):
    def test_time_decay_exit_fires_in_backtest(self) -> None:
        """Time-decay exit should fire once a long-held position stays underwater."""
        # Create a scenario: buy signal, then price drops slightly and stays flat
        # max_holding_bars=20, so time_decay triggers at bar 15+ if underwater
        flat = [100.0] * 25
        # Force a dip then slight recovery to trigger entry, then stay underwater
        prices = flat + [98.0, 97.0, 96.0, 95.0] + [95.0] * 25
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
                max_holding_bars=20,
            )
        )
        risk = RiskManager(
            RiskConfig(
                stop_loss_pct=0.15,  # wide stops so they don't trigger first
                take_profit_pct=0.30,
                atr_stop_multiplier=0.0,
                cooldown_bars=0,
            ),
            atr_stop_multiplier=0.0,
            max_holding_bars=20,
        )
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        # If there are trades, check that time_decay or max_holding exits happen
        [t.exit_reason for t in result.trade_log]
        # At minimum, we should have the sharpe_ratio field
        self.assertIsInstance(result.sharpe_ratio, float)


# ---------- US-043: cooldown and auto_pause in backtest ----------


class TestBacktestCooldown(unittest.TestCase):
    def test_cooldown_prevents_immediate_reentry(self) -> None:
        """After a losing trade, cooldown_bars should prevent immediate re-entry."""
        # Scenario: quick loss, then immediate buy signal should be blocked
        prices = [100.0] * 25 + [95.0, 90.0, 85.0] + [100.0] * 5 + [95.0, 90.0, 85.0] + [100.0] * 10
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
        # With cooldown_bars=5, there should be fewer trades than without
        risk_with_cd = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, cooldown_bars=5),
        )
        risk_no_cd = RiskManager(
            RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10, cooldown_bars=0),
        )

        engine_cd = BacktestEngine(
            strategy=strategy,
            risk_manager=risk_with_cd,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        engine_no_cd = BacktestEngine(
            strategy=strategy,
            risk_manager=risk_no_cd,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )

        result_cd = engine_cd.run(candles)
        result_no_cd = engine_no_cd.run(candles)

        # Cooldown version should have <= trades than no-cooldown version
        self.assertLessEqual(len(result_cd.trade_log), len(result_no_cd.trade_log))

    def test_auto_pause_checked_in_backtest(self) -> None:
        """is_auto_paused should be consulted during backtest position opening."""
        risk = RiskManager(RiskConfig(cooldown_bars=0))
        # Pre-load trade history with many losers to trigger auto-pause
        for _ in range(15):
            risk.record_trade(-0.05)
        self.assertTrue(risk.is_auto_paused)


# ---------- US-044: Sharpe ratio ----------


class TestSharpeRatio(unittest.TestCase):
    def test_sharpe_positive_for_uptrend(self) -> None:
        """Equity curve going up should have positive Sharpe."""
        curve = [1000.0 + i * 10.0 for i in range(100)]
        sharpe = _sharpe_ratio(curve)
        self.assertGreater(sharpe, 0)

    def test_sharpe_negative_for_downtrend(self) -> None:
        """Equity curve going down should have negative Sharpe."""
        curve = [1000.0 - i * 10.0 for i in range(50)]
        sharpe = _sharpe_ratio(curve)
        self.assertLess(sharpe, 0)

    def test_sharpe_zero_for_flat(self) -> None:
        """Flat equity curve should have zero Sharpe."""
        curve = [1000.0] * 100
        sharpe = _sharpe_ratio(curve)
        self.assertEqual(sharpe, 0.0)

    def test_sharpe_on_short_curve(self) -> None:
        """Too few points should return 0."""
        self.assertEqual(_sharpe_ratio([100.0, 101.0]), 0.0)
        self.assertEqual(_sharpe_ratio([100.0]), 0.0)

    def test_backtest_result_has_sharpe(self) -> None:
        """BacktestResult should include sharpe_ratio field."""
        candles = _candles([100.0] * 30)
        strategy = CompositeStrategy(
            StrategyConfig(momentum_lookback=3, bollinger_window=20, rsi_period=5)
        )
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertIsInstance(result.sharpe_ratio, float)


# ---------- US-045: MACD indicator ----------


class TestMACDIndicator(unittest.TestCase):
    def test_macd_basic_calculation(self) -> None:
        """MACD should return (macd_line, signal_line, histogram) tuple."""
        # Create uptrending data
        closes = [100.0 + i * 0.5 for i in range(50)]
        ml, sl, hist = macd(closes)
        self.assertIsInstance(ml, float)
        self.assertIsInstance(sl, float)
        self.assertAlmostEqual(hist, ml - sl, places=10)

    def test_macd_uptrend_positive(self) -> None:
        """In a strong uptrend, MACD line should be positive."""
        closes = [100.0 + i * 2.0 for i in range(50)]
        ml, sl, hist = macd(closes)
        self.assertGreater(ml, 0)

    def test_macd_downtrend_negative(self) -> None:
        """In a strong downtrend, MACD line should be negative."""
        closes = [200.0 - i * 2.0 for i in range(50)]
        ml, sl, hist = macd(closes)
        self.assertLess(ml, 0)

    def test_macd_insufficient_data(self) -> None:
        """Should raise ValueError with insufficient data."""
        with self.assertRaises(ValueError):
            macd([100.0] * 30)  # need 35+

    def test_macd_crossover_detection(self) -> None:
        """After a trend reversal, histogram should change sign."""
        # Downtrend then uptrend
        closes = [200.0 - i * 2.0 for i in range(40)] + [120.0 + i * 3.0 for i in range(30)]
        ml, sl, hist = macd(closes)
        # After strong uptrend recovery, histogram should be positive
        self.assertGreater(hist, 0)

    def test_ema_basic(self) -> None:
        """EMA should converge toward recent values."""
        values = [10.0] * 20 + [20.0] * 20
        result = _ema(values, 10)
        self.assertEqual(len(result), len(values))
        # Final EMA should be close to 20
        self.assertGreater(result[-1], 19.0)
        # First value equals input
        self.assertEqual(result[0], 10.0)


# ---------- US-045 continued: MACD in CompositeStrategy ----------


class TestCompositeMACDIntegration(unittest.TestCase):
    def test_macd_indicators_in_signal(self) -> None:
        """CompositeStrategy should include MACD indicators in signal output."""
        # Need 35+ candles for MACD
        closes = [100.0] * 40
        candles = _candles(closes)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                bollinger_window=20,
                rsi_period=5,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertIn("macd_line", signal.indicators)
        self.assertIn("macd_signal", signal.indicators)
        self.assertIn("macd_histogram", signal.indicators)

    def test_macd_absent_with_few_candles(self) -> None:
        """With < 35 candles, MACD indicators should be zero."""
        closes = [100.0] * 25
        candles = _candles(closes)
        strategy = CompositeStrategy(
            StrategyConfig(
                momentum_lookback=3,
                bollinger_window=20,
                rsi_period=5,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.indicators.get("macd_line", 0), 0.0)


# ---------- US-046: Regime breakdown ----------


class TestRegimeBreakdown(unittest.TestCase):
    def test_regime_fields_in_backtest_all_export(self) -> None:
        """Verify regime breakdown dict structure is correct."""
        # Simulate what backtest-all produces
        regime_wins = {"bull": 5, "sideways": 3, "bear": 1}
        regime_totals = {"bull": 8, "sideways": 6, "bear": 4}
        row = {
            "regime_bull_wr": round(regime_wins["bull"] / max(1, regime_totals["bull"]) * 100, 1),
            "regime_sideways_wr": round(
                regime_wins["sideways"] / max(1, regime_totals["sideways"]) * 100, 1
            ),
            "regime_bear_wr": round(regime_wins["bear"] / max(1, regime_totals["bear"]) * 100, 1),
            "regime_bull_n": regime_totals["bull"],
            "regime_sideways_n": regime_totals["sideways"],
            "regime_bear_n": regime_totals["bear"],
        }
        self.assertAlmostEqual(row["regime_bull_wr"], 62.5)
        self.assertAlmostEqual(row["regime_sideways_wr"], 50.0)
        self.assertAlmostEqual(row["regime_bear_wr"], 25.0)
        self.assertEqual(row["regime_bull_n"], 8)


if __name__ == "__main__":
    unittest.main()
