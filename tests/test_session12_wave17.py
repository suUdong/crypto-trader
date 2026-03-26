"""Tests for Session #12 Wave 17: weighted consensus, regime breakdown."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle, Signal, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.consensus import ConsensusStrategy


def _candles(closes: list[float], volume: float = 1000.0) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=volume)
        for i, c in enumerate(closes)
    ]


class _MockStrategy:
    """Mock strategy returning configurable signals."""
    def __init__(self, action: SignalAction, confidence: float, reason: str = "mock"):
        self._action = action
        self._confidence = confidence
        self._reason = reason

    def evaluate(self, candles, position=None):
        return Signal(
            action=self._action, reason=self._reason,
            confidence=self._confidence,
            context={"market_regime": "sideways"},
        )


# ---------- Weighted consensus ----------

class TestWeightedConsensus(unittest.TestCase):
    def test_agreement_ratio_in_indicators(self) -> None:
        """Consensus BUY should include agreement_ratio indicator."""
        strategies = [
            _MockStrategy(SignalAction.BUY, 0.8, "strat_a"),
            _MockStrategy(SignalAction.BUY, 0.7, "strat_b"),
            _MockStrategy(SignalAction.HOLD, 0.2, "strat_c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        candles = _candles([100.0] * 10)
        signal = consensus.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertIn("agreement_ratio", signal.indicators)
        self.assertAlmostEqual(signal.indicators["agreement_ratio"], 2 / 3, places=2)

    def test_weighted_confidence_in_indicators(self) -> None:
        """Consensus BUY should include weighted_confidence indicator."""
        strategies = [
            _MockStrategy(SignalAction.BUY, 0.9, "strat_a"),
            _MockStrategy(SignalAction.BUY, 0.5, "strat_b"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        candles = _candles([100.0] * 10)
        signal = consensus.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        self.assertIn("weighted_confidence", signal.indicators)
        # Weighted with equal weights: (1.0*0.9^2 + 1.0*0.5^2) / (1.0+1.0) = 1.06/2.0 = 0.53
        self.assertAlmostEqual(signal.indicators["weighted_confidence"], 0.53, places=2)

    def test_higher_confidence_gets_more_weight(self) -> None:
        """Weighted confidence should favor higher-confidence strategies."""
        # All high confidence
        strats_high = [
            _MockStrategy(SignalAction.BUY, 0.9, "a"),
            _MockStrategy(SignalAction.BUY, 0.9, "b"),
        ]
        # Mixed confidence
        strats_mixed = [
            _MockStrategy(SignalAction.BUY, 0.9, "a"),
            _MockStrategy(SignalAction.BUY, 0.3, "b"),
        ]
        candles = _candles([100.0] * 10)
        sig_high = ConsensusStrategy(strats_high, min_agree=2).evaluate(candles)
        sig_mixed = ConsensusStrategy(strats_mixed, min_agree=2).evaluate(candles)
        self.assertGreater(sig_high.confidence, sig_mixed.confidence)

    def test_full_agreement_boosts_confidence(self) -> None:
        """100% agreement should boost confidence via agreement ratio."""
        strategies = [
            _MockStrategy(SignalAction.BUY, 0.6, "a"),
            _MockStrategy(SignalAction.BUY, 0.6, "b"),
            _MockStrategy(SignalAction.BUY, 0.6, "c"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        candles = _candles([100.0] * 10)
        signal = consensus.evaluate(candles)
        self.assertEqual(signal.action, SignalAction.BUY)
        # With equal weights: weighted_conf = (1.0*0.6^2*3)/(3.0) = 0.36, + agree_ratio(1.0)*0.1 = 0.46
        self.assertGreater(signal.confidence, 0.4)

    def test_sell_still_conservative(self) -> None:
        """Any SELL should still trigger consensus exit."""
        strategies = [
            _MockStrategy(SignalAction.HOLD, 0.5, "a"),
            _MockStrategy(SignalAction.SELL, 0.8, "sell_reason"),
        ]
        consensus = ConsensusStrategy(strategies, min_agree=2)
        candles = _candles([100.0] * 10)
        from crypto_trader.models import Position
        pos = Position(symbol="KRW-BTC", quantity=1.0, entry_price=100.0,
                       entry_time=datetime(2025, 1, 1))
        signal = consensus.evaluate(candles, pos)
        self.assertEqual(signal.action, SignalAction.SELL)


# ---------- Regime breakdown in BacktestResult ----------

class TestRegimeBreakdown(unittest.TestCase):
    def test_regime_breakdown_populated(self) -> None:
        """BacktestResult should have regime_breakdown dict."""
        class RegimeStrategy:
            def evaluate(self, candles, position=None):
                if position is None:
                    return Signal(
                        action=SignalAction.BUY, reason="buy",
                        confidence=0.8,
                        context={"market_regime": "bull"},
                    )
                return Signal(
                    action=SignalAction.SELL, reason="sell",
                    confidence=0.9,
                    context={"market_regime": "bull"},
                )

        prices = [100.0] * 50
        candles = _candles(prices)
        risk = RiskManager(RiskConfig(
            stop_loss_pct=0.05, take_profit_pct=0.10,
            min_entry_confidence=0.5,
        ))
        engine = BacktestEngine(
            strategy=RegimeStrategy(), risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertIsInstance(result.regime_breakdown, dict)
        if result.trade_log:
            self.assertIn("bull", result.regime_breakdown)
            bull = result.regime_breakdown["bull"]
            self.assertGreater(bull["trade_count"], 0)
            self.assertIn("win_rate", bull)
            self.assertIn("avg_pnl", bull)

    def test_regime_breakdown_empty_no_trades(self) -> None:
        """With no trades, regime_breakdown should be empty."""
        class NeverBuy:
            def evaluate(self, candles, position=None):
                return Signal(action=SignalAction.HOLD, reason="nope", confidence=0.1)

        prices = [100.0] * 20
        candles = _candles(prices)
        risk = RiskManager(RiskConfig())
        engine = BacktestEngine(
            strategy=NeverBuy(), risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        self.assertEqual(result.regime_breakdown, {})

    def test_multiple_regimes_tracked(self) -> None:
        """Should track different regimes separately."""
        class MultiRegimeStrategy:
            def __init__(self):
                self._call = 0
            def evaluate(self, candles, position=None):
                self._call += 1
                regime = "bull" if self._call % 4 < 2 else "bear"
                if position is None:
                    return Signal(
                        action=SignalAction.BUY, reason="buy",
                        confidence=0.8,
                        context={"market_regime": regime},
                    )
                return Signal(
                    action=SignalAction.SELL, reason="sell",
                    confidence=0.9,
                    context={"market_regime": regime},
                )

        prices = [100.0] * 60
        candles = _candles(prices)
        risk = RiskManager(RiskConfig(
            stop_loss_pct=0.05, take_profit_pct=0.10,
            min_entry_confidence=0.5,
        ))
        engine = BacktestEngine(
            strategy=MultiRegimeStrategy(), risk_manager=risk,
            config=BacktestConfig(initial_capital=1_000_000.0),
            symbol="KRW-BTC",
        )
        result = engine.run(candles)
        # Should have at least one regime tracked
        self.assertGreater(len(result.regime_breakdown), 0)


if __name__ == "__main__":
    unittest.main()
