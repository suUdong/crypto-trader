"""Tests for Session #11 Wave 6: consensus ema_crossover, win-streak boost."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from crypto_trader.config import RegimeConfig, RiskConfig, StrategyConfig
from crypto_trader.models import Candle, Position
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.wallet import create_strategy


def _candles(closes: list[float]) -> list[Candle]:
    t = datetime(2025, 1, 1)
    return [
        Candle(timestamp=t + timedelta(hours=i), open=c, high=c * 1.01,
               low=c * 0.99, close=c, volume=1000.0)
        for i, c in enumerate(closes)
    ]


# ---------- Consensus with ema_crossover ----------

class TestConsensusEMACrossover(unittest.TestCase):
    def test_default_consensus_includes_ema_crossover(self) -> None:
        """Default consensus should have 3 sub-strategies: momentum, vpin, ema_crossover."""
        strategy = create_strategy("consensus", StrategyConfig(), RegimeConfig())
        # ConsensusStrategy stores sub-strategies in _strategies
        self.assertEqual(len(strategy._strategies), 3)

    def test_consensus_with_ema_crossover_evaluates(self) -> None:
        """Consensus with ema_crossover should evaluate without errors."""
        candles = _candles([100.0] * 40)
        strategy = create_strategy("consensus", StrategyConfig(
            momentum_lookback=3, rsi_period=5,
        ), RegimeConfig())
        signal = strategy.evaluate(candles)
        self.assertIsNotNone(signal)
        self.assertIn("consensus", signal.context.get("strategy", ""))

    def test_consensus_custom_sub_strategies(self) -> None:
        """Custom sub-strategy list should override default."""
        strategy = create_strategy(
            "consensus", StrategyConfig(), RegimeConfig(),
            extra_params={"sub_strategies": ["momentum", "mean_reversion"]},
        )
        self.assertEqual(len(strategy._strategies), 2)


# ---------- Win-streak boost ----------

class TestWinStreakBoost(unittest.TestCase):
    def test_no_boost_under_3_wins(self) -> None:
        """Position size should be normal with < 3 consecutive wins."""
        risk = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.03, max_position_pct=1.0))
        risk.record_trade(0.02)
        risk.record_trade(0.03)
        size_2wins = risk.size_position(100_000.0, 50_000.0)

        risk2 = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.03, max_position_pct=1.0))
        size_0wins = risk2.size_position(100_000.0, 50_000.0)

        # Should be equal (no streak boost yet)
        self.assertAlmostEqual(size_2wins, size_0wins, places=6)

    def test_boost_after_3_wins(self) -> None:
        """Position size should increase after 3+ consecutive wins."""
        risk = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.03, max_position_pct=1.0))
        base_size = risk.size_position(100_000.0, 50_000.0)

        risk.record_trade(0.02)
        risk.record_trade(0.03)
        risk.record_trade(0.01)
        boosted_size = risk.size_position(100_000.0, 50_000.0)

        self.assertGreater(boosted_size, base_size)

    def test_boost_capped_at_1_3x(self) -> None:
        """Win-streak boost should not exceed 1.3x."""
        risk = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.03, max_position_pct=1.0))
        base_size = risk.size_position(100_000.0, 50_000.0)

        # 10 consecutive wins
        for _ in range(10):
            risk.record_trade(0.02)
        boosted_size = risk.size_position(100_000.0, 50_000.0)

        ratio = boosted_size / base_size
        self.assertLessEqual(ratio, 1.31)  # small float tolerance
        self.assertGreaterEqual(ratio, 1.29)

    def test_boost_resets_on_loss(self) -> None:
        """Losing trade should reset win streak and remove boost."""
        risk = RiskManager(RiskConfig(risk_per_trade_pct=0.01, stop_loss_pct=0.03, max_position_pct=1.0))
        for _ in range(5):
            risk.record_trade(0.02)
        boosted = risk.size_position(100_000.0, 50_000.0)

        risk.record_trade(-0.01)  # loss resets streak
        normal = risk.size_position(100_000.0, 50_000.0)

        self.assertGreater(boosted, normal)

    def test_consecutive_wins_counter(self) -> None:
        """Track consecutive wins correctly."""
        risk = RiskManager(RiskConfig())
        self.assertEqual(risk._consecutive_wins, 0)
        risk.record_trade(0.05)
        self.assertEqual(risk._consecutive_wins, 1)
        risk.record_trade(0.03)
        self.assertEqual(risk._consecutive_wins, 2)
        risk.record_trade(-0.01)
        self.assertEqual(risk._consecutive_wins, 0)
        risk.record_trade(0.02)
        self.assertEqual(risk._consecutive_wins, 1)


if __name__ == "__main__":
    unittest.main()
