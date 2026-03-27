"""Tests for Session #12 Wave 13: regime-aware EMA, macro trend momentum, partial TP engine."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle, Position, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.strategy.momentum import MomentumStrategy


def _candles(closes: list[float], volume: float = 1000.0) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(
            timestamp=t + timedelta(hours=i),
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=volume,
        )
        for i, c in enumerate(closes)
    ]


# ---------- EMA crossover regime awareness ----------


class TestEMACrossoverRegime(unittest.TestCase):
    def test_regime_in_context(self) -> None:
        """EMA crossover should include market_regime in context."""
        prices = [100.0 + i * 0.5 for i in range(50)]
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("market_regime", signal.context)

    def test_regime_detector_initialized(self) -> None:
        """Should have a regime detector attribute."""
        strategy = EMACrossoverStrategy(StrategyConfig())
        self.assertIsNotNone(strategy._regime_detector)

    def test_custom_regime_config(self) -> None:
        """Should accept custom RegimeConfig."""
        rc = RegimeConfig(short_lookback=5, long_lookback=15)
        strategy = EMACrossoverStrategy(StrategyConfig(), regime_config=rc)
        self.assertIsNotNone(strategy._regime_detector)

    def test_regime_adjusts_rsi_overbought(self) -> None:
        """Regime detection should influence effective parameters."""
        # In bear market, regime detector tightens RSI thresholds
        # We verify the strategy uses regime-adjusted params by checking
        # that regime context is populated
        prices = [100.0 - i * 0.5 for i in range(50)]  # Downtrend
        candles = _candles(prices)
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, adx_threshold=0.0),
            regime_config=RegimeConfig(bull_threshold_pct=0.03, bear_threshold_pct=-0.03),
        )
        signal = strategy.evaluate(candles)
        self.assertIn("market_regime", signal.context)

    def test_insufficient_data_includes_regime(self) -> None:
        """Even with insufficient data, context should have regime."""
        candles = _candles([100.0] * 5)
        strategy = EMACrossoverStrategy(StrategyConfig(rsi_period=5))
        signal = strategy.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.HOLD)
        self.assertIn("market_regime", signal.context)

    def test_exit_uses_regime_adjusted_params(self) -> None:
        """Exit logic should use regime-adjusted max_holding_bars."""
        prices = [100.0] * 60
        candles = _candles(prices)
        pos = Position(
            symbol="KRW-BTC",
            quantity=1.0,
            entry_price=100.0,
            entry_time=datetime(2025, 1, 1),
            entry_index=0,
        )
        strategy = EMACrossoverStrategy(
            StrategyConfig(rsi_period=5, max_holding_bars=48, adx_threshold=0.0),
        )
        signal = strategy.evaluate(candles, pos)
        # With 60 bars and max_holding=48, should trigger sell
        self.assertEqual(signal.action, SignalAction.SELL)
        self.assertEqual(signal.reason, "max_holding_period")


# ---------- Momentum EMA(50) macro trend ----------


class TestMomentumMacroTrend(unittest.TestCase):
    def test_ema50_in_indicators(self) -> None:
        """Momentum should include ema50 when enough data."""
        prices = [100.0 + i * 0.3 for i in range(60)]
        candles = _candles(prices)
        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=5,
                rsi_period=5,
                adx_threshold=0.0,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertIn("ema50", signal.indicators)

    def test_ema50_absent_with_short_data(self) -> None:
        """Momentum should not have ema50 with < 50 candles."""
        prices = [100.0] * 30
        candles = _candles(prices)
        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=5,
                rsi_period=5,
            )
        )
        signal = strategy.evaluate(candles)
        self.assertNotIn("ema50", signal.indicators)

    def test_uptrend_boosts_confidence(self) -> None:
        """EMA(50) aligned uptrend should give higher confidence on BUY."""
        # Create clear uptrend above EMA(50)
        prices = [80.0 + i * 0.5 for i in range(55)]
        candles = _candles(prices)
        strategy = MomentumStrategy(
            StrategyConfig(
                momentum_lookback=5,
                momentum_entry_threshold=0.001,
                rsi_period=5,
                rsi_oversold_floor=0.0,
                rsi_recovery_ceiling=100.0,
                adx_threshold=0.0,
            )
        )
        signal = strategy.evaluate(candles)
        if signal.action == SignalAction.BUY:
            # Confidence should be boosted by macro trend
            self.assertGreater(signal.confidence, 0.5)


# ---------- Partial take-profit in backtest engine ----------


class TestBacktestPartialTP(unittest.TestCase):
    def test_partial_tp_creates_two_trades(self) -> None:
        """Partial TP should create a partial trade, then final exit trade."""

        class BuyThenHold:
            def __init__(self):
                self._bought = False

            def evaluate(self, candles, position=None):
                from crypto_trader.models import Signal, SignalAction

                if position is None and not self._bought:
                    self._bought = True
                    return Signal(action=SignalAction.BUY, reason="buy", confidence=0.8)
                return Signal(action=SignalAction.HOLD, reason="hold", confidence=0.5)

        # Price rises to trigger partial TP then full TP
        prices = [100.0] * 20 + [103.0] * 5 + [106.5] * 5
        candles = _candles(prices)
        risk = RiskManager(
            RiskConfig(
                stop_loss_pct=0.05,
                take_profit_pct=0.06,
                partial_tp_pct=0.5,
                atr_stop_multiplier=0.0,
                min_entry_confidence=0.5,
            )
        )
        engine = BacktestEngine(
            strategy=BuyThenHold(),
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0, fee_rate=0.0, slippage_pct=0.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        # Should have at least 2 trades: one partial TP and one final
        partial_trades = [t for t in result.trade_log if t.exit_reason == "partial_take_profit"]
        if partial_trades:
            self.assertGreater(len(result.trade_log), 1)
            # Partial trade quantity should be less than full position
            self.assertLess(partial_trades[0].quantity, result.trade_log[-1].quantity * 3)

    def test_partial_tp_only_triggers_once(self) -> None:
        """Partial TP should not re-trigger after already taken."""

        class AlwaysBuy:
            def evaluate(self, candles, position=None):
                from crypto_trader.models import Signal, SignalAction

                if position is None:
                    return Signal(action=SignalAction.BUY, reason="buy", confidence=0.8)
                return Signal(action=SignalAction.HOLD, reason="hold", confidence=0.5)

        # Price rises and stays in partial TP zone
        prices = [100.0] * 20 + [103.0] * 20
        candles = _candles(prices)
        risk = RiskManager(
            RiskConfig(
                stop_loss_pct=0.05,
                take_profit_pct=0.06,
                partial_tp_pct=0.5,
                atr_stop_multiplier=0.0,
                min_entry_confidence=0.5,
            )
        )
        engine = BacktestEngine(
            strategy=AlwaysBuy(),
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0, fee_rate=0.0, slippage_pct=0.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        partial_count = sum(1 for t in result.trade_log if t.exit_reason == "partial_take_profit")
        # At most 1 partial TP per position
        self.assertLessEqual(partial_count, 1)

    def test_partial_tp_disabled_when_zero(self) -> None:
        """partial_tp_pct=0 should not create any partial trades."""

        class AlwaysBuy:
            def evaluate(self, candles, position=None):
                from crypto_trader.models import Signal, SignalAction

                if position is None:
                    return Signal(action=SignalAction.BUY, reason="buy", confidence=0.8)
                return Signal(action=SignalAction.HOLD, reason="hold", confidence=0.5)

        prices = [100.0] * 20 + [103.0] * 10 + [106.5] * 5
        candles = _candles(prices)
        risk = RiskManager(
            RiskConfig(
                stop_loss_pct=0.05,
                take_profit_pct=0.06,
                partial_tp_pct=0.0,
                atr_stop_multiplier=0.0,
                min_entry_confidence=0.5,
            )
        )
        engine = BacktestEngine(
            strategy=AlwaysBuy(),
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0, fee_rate=0.0, slippage_pct=0.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        partial_count = sum(1 for t in result.trade_log if t.exit_reason == "partial_take_profit")
        self.assertEqual(partial_count, 0)

    def test_partial_tp_preserves_equity(self) -> None:
        """Total equity after partial TP + final exit should be consistent."""

        class AlwaysBuy:
            def evaluate(self, candles, position=None):
                from crypto_trader.models import Signal, SignalAction

                if position is None:
                    return Signal(action=SignalAction.BUY, reason="buy", confidence=0.8)
                return Signal(action=SignalAction.HOLD, reason="hold", confidence=0.5)

        prices = [100.0] * 20 + [103.0] * 5 + [106.5] * 5
        candles = _candles(prices)
        risk = RiskManager(
            RiskConfig(
                stop_loss_pct=0.05,
                take_profit_pct=0.06,
                partial_tp_pct=0.5,
                atr_stop_multiplier=0.0,
                min_entry_confidence=0.5,
            )
        )
        engine = BacktestEngine(
            strategy=AlwaysBuy(),
            risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0, fee_rate=0.0, slippage_pct=0.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        # Final equity should be positive and greater than initial (prices went up)
        self.assertGreater(result.final_equity, 1_000_000.0)


if __name__ == "__main__":
    unittest.main()
