"""Tests for grid-wf (grid search + walk-forward combo)."""
from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.grid_wf import (
    GridCandidate,
    grid_search,
    run_grid_wf,
    validate_with_walk_forward,
)
from crypto_trader.config import BacktestConfig, RiskConfig
from crypto_trader.models import Candle


def _build_candles(
    closes: list[float],
    start: datetime | None = None,
) -> list[Candle]:
    base = start or datetime(2025, 1, 1)
    candles = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i > 0 else c
        candles.append(
            Candle(
                timestamp=base + timedelta(hours=i),
                open=prev,
                high=c * 1.02,
                low=c * 0.98,
                close=c,
                volume=1000.0 + i * 10,
            )
        )
    return candles


def _trending_with_pullbacks(n: int = 400) -> list[float]:
    closes = []
    price = 100_000.0
    for i in range(n):
        if i % 5 == 4:
            price -= 1500
        else:
            price += 1500
        closes.append(max(price, 50_000.0))
    return closes


def _sideways(n: int = 400) -> list[float]:
    return [100_000.0 + 5000.0 * math.sin(i * 0.15) for i in range(n)]


class TestGridSearch(unittest.TestCase):
    def test_returns_candidates_for_momentum(self) -> None:
        candles = _build_candles(_trending_with_pullbacks(300))
        candles_map = {"KRW-BTC": candles}
        candidates = grid_search("momentum", candles_map, top_n=3)
        self.assertGreater(len(candidates), 0)
        self.assertLessEqual(len(candidates), 3)
        for c in candidates:
            self.assertEqual(c.strategy_type, "momentum")
            self.assertIsInstance(c.avg_sharpe, float)

    def test_candidates_sorted_by_sharpe(self) -> None:
        candles = _build_candles(_sideways(300))
        candles_map = {"KRW-BTC": candles}
        candidates = grid_search("mean_reversion", candles_map, top_n=5)
        if len(candidates) >= 2:
            self.assertGreaterEqual(candidates[0].avg_sharpe, candidates[1].avg_sharpe)

    def test_unknown_strategy_returns_empty(self) -> None:
        candles = _build_candles(_sideways(300))
        candidates = grid_search("nonexistent", {"KRW-BTC": candles}, top_n=3)
        self.assertEqual(len(candidates), 0)


class TestValidateWithWalkForward(unittest.TestCase):
    def test_validates_candidate(self) -> None:
        candles = _build_candles(_trending_with_pullbacks(400))
        candidate = GridCandidate(
            strategy_type="momentum",
            params={"momentum_lookback": 15, "momentum_entry_threshold": 0.005,
                    "rsi_period": 14, "max_holding_bars": 48},
            avg_sharpe=1.5,
            avg_return_pct=3.0,
            total_trades=20,
        )
        result = validate_with_walk_forward(
            candidate,
            {"KRW-BTC": candles},
            BacktestConfig(),
            RiskConfig(),
        )
        self.assertIsNotNone(result.wf_report)
        self.assertIsInstance(result.validated, bool)
        self.assertGreater(result.wf_report.total_folds, 0)


class TestRunGridWF(unittest.TestCase):
    def test_full_pipeline_momentum(self) -> None:
        candles = _build_candles(_trending_with_pullbacks(400))
        summary = run_grid_wf(
            "momentum",
            {"KRW-BTC": candles},
            top_n=2,
        )
        self.assertGreater(summary.candidates_tested, 0)
        self.assertGreater(len(summary.results), 0)
        # Each result has a WF report
        for r in summary.results:
            self.assertIsNotNone(r.wf_report)

    def test_full_pipeline_mean_reversion(self) -> None:
        candles = _build_candles(_sideways(400))
        summary = run_grid_wf(
            "mean_reversion",
            {"KRW-BTC": candles},
            top_n=2,
        )
        self.assertGreater(summary.candidates_tested, 0)


if __name__ == "__main__":
    unittest.main()
