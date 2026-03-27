"""Tests for grid-wf (grid search + walk-forward combo)."""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta

from crypto_trader.backtest.grid_wf import (
    GridCandidate,
    GridWFResult,
    GridWFSummary,
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

    def test_returns_candidates_for_consensus(self) -> None:
        candles = _build_candles(_trending_with_pullbacks(300))
        candles_map = {"KRW-BTC": candles}
        candidates = grid_search("consensus", candles_map, top_n=3)
        self.assertGreater(len(candidates), 0)
        for c in candidates:
            self.assertEqual(c.strategy_type, "consensus")

    def test_regime_filter_none_same_as_default(self) -> None:
        candles = _build_candles(_trending_with_pullbacks(300))
        candles_map = {"KRW-BTC": candles}
        candidates_default = grid_search("momentum", candles_map, top_n=3)
        candidates_none = grid_search("momentum", candles_map, top_n=3, regime_filter=None)
        self.assertEqual(len(candidates_default), len(candidates_none))

    def test_regime_filter_returns_valid_candidates(self) -> None:
        candles = _build_candles(_trending_with_pullbacks(300))
        candles_map = {"KRW-BTC": candles}
        # Should not crash; may return fewer candidates or same
        candidates = grid_search("momentum", candles_map, top_n=3, regime_filter="bull")
        self.assertIsInstance(candidates, list)
        for c in candidates:
            self.assertEqual(c.strategy_type, "momentum")
            self.assertIsInstance(c.avg_sharpe, float)


class TestValidateWithWalkForward(unittest.TestCase):
    def test_validates_candidate(self) -> None:
        candles = _build_candles(_trending_with_pullbacks(400))
        candidate = GridCandidate(
            strategy_type="momentum",
            params={
                "momentum_lookback": 15,
                "momentum_entry_threshold": 0.005,
                "rsi_period": 14,
                "max_holding_bars": 48,
            },
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

    def test_multi_symbol_folds_combined(self) -> None:
        """WF report should contain folds from all symbols, not just one."""
        candles_btc = _build_candles(_trending_with_pullbacks(400))
        candles_eth = _build_candles(_sideways(400), start=datetime(2025, 2, 1))
        candidate = GridCandidate(
            strategy_type="momentum",
            params={
                "momentum_lookback": 15,
                "momentum_entry_threshold": 0.005,
                "rsi_period": 14,
                "max_holding_bars": 48,
            },
            avg_sharpe=1.5,
            avg_return_pct=3.0,
            total_trades=20,
        )
        result = validate_with_walk_forward(
            candidate,
            {"KRW-BTC": candles_btc, "KRW-ETH": candles_eth},
            BacktestConfig(),
            RiskConfig(),
            n_folds=3,
        )
        self.assertIsNotNone(result.wf_report)
        self.assertIsInstance(result.validated, bool)
        # Combined report should have folds from both symbols (2 symbols * 3 folds each = 6)
        self.assertGreater(result.wf_report.total_folds, 3)
        self.assertEqual(result.wf_report.symbol, "multi")


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


class TestGridWFSummaryToDict(unittest.TestCase):
    def _make_summary(self, validated: bool) -> GridWFSummary:
        from unittest.mock import MagicMock

        candidate = GridCandidate(
            strategy_type="momentum",
            params={"momentum_lookback": 15, "rsi_period": 14},
            avg_sharpe=1.2,
            avg_return_pct=5.0,
            total_trades=30,
        )
        wf_report = MagicMock()
        wf_report.avg_efficiency_ratio = 0.6
        wf_report.oos_win_rate = 0.67
        result = GridWFResult(candidate=candidate, wf_report=wf_report, validated=validated)
        return GridWFSummary(
            strategy_type="momentum",
            candidates_tested=3,
            candidates_validated=1 if validated else 0,
            results=[result],
        )

    def test_to_dict_keys(self) -> None:
        summary = self._make_summary(validated=True)
        d = summary.to_dict()
        self.assertIn("strategy_type", d)
        self.assertIn("candidates_tested", d)
        self.assertIn("candidates_validated", d)
        self.assertIn("results", d)
        self.assertIn("best_validated", d)

    def test_to_dict_values(self) -> None:
        summary = self._make_summary(validated=True)
        d = summary.to_dict()
        self.assertEqual(d["strategy_type"], "momentum")
        self.assertEqual(d["candidates_tested"], 3)
        self.assertEqual(d["candidates_validated"], 1)
        self.assertIsInstance(d["results"], list)
        self.assertEqual(len(d["results"]), 1)

    def test_to_dict_result_keys(self) -> None:
        summary = self._make_summary(validated=True)
        r = summary.to_dict()["results"][0]
        for key in (
            "params",
            "avg_sharpe",
            "avg_return_pct",
            "total_trades",
            "avg_profit_factor",
            "validated",
            "wf_avg_efficiency_ratio",
            "wf_oos_win_rate",
        ):
            self.assertIn(key, r)

    def test_to_dict_best_validated_none_when_no_pass(self) -> None:
        summary = self._make_summary(validated=False)
        d = summary.to_dict()
        self.assertIsNone(d["best_validated"])

    def test_to_dict_best_validated_present_when_pass(self) -> None:
        summary = self._make_summary(validated=True)
        d = summary.to_dict()
        self.assertIsNotNone(d["best_validated"])
        self.assertIn("params", d["best_validated"])
        self.assertIn("avg_sharpe", d["best_validated"])

    def test_to_dict_is_json_serializable(self) -> None:
        import json

        summary = self._make_summary(validated=True)
        # Should not raise
        json.dumps(summary.to_dict())


class TestProfitFactor(unittest.TestCase):
    def test_grid_candidate_has_avg_profit_factor(self) -> None:
        candidate = GridCandidate(
            strategy_type="momentum",
            params={"momentum_lookback": 15},
            avg_sharpe=1.0,
            avg_return_pct=5.0,
            total_trades=10,
        )
        self.assertEqual(candidate.avg_profit_factor, 1.0)

        candidate_explicit = GridCandidate(
            strategy_type="momentum",
            params={"momentum_lookback": 15},
            avg_sharpe=1.0,
            avg_return_pct=5.0,
            total_trades=10,
            avg_profit_factor=2.5,
        )
        self.assertEqual(candidate_explicit.avg_profit_factor, 2.5)

    def test_grid_search_includes_profit_factor(self) -> None:
        candles = _build_candles(_trending_with_pullbacks(300))
        candidates = grid_search("momentum", {"KRW-BTC": candles}, top_n=3)
        self.assertGreater(len(candidates), 0)
        for c in candidates:
            self.assertIsInstance(c.avg_profit_factor, float)
            self.assertGreaterEqual(c.avg_profit_factor, 0.0)

    def test_to_dict_includes_profit_factor(self) -> None:
        from unittest.mock import MagicMock

        candidate = GridCandidate(
            strategy_type="momentum",
            params={"momentum_lookback": 15, "rsi_period": 14},
            avg_sharpe=1.2,
            avg_return_pct=5.0,
            total_trades=30,
            avg_profit_factor=1.8,
        )
        wf_report = MagicMock()
        wf_report.avg_efficiency_ratio = 0.6
        wf_report.oos_win_rate = 0.67
        result = GridWFResult(candidate=candidate, wf_report=wf_report, validated=True)
        summary = GridWFSummary(
            strategy_type="momentum",
            candidates_tested=1,
            candidates_validated=1,
            results=[result],
        )
        d = summary.to_dict()
        self.assertIn("avg_profit_factor", d["results"][0])
        self.assertEqual(d["results"][0]["avg_profit_factor"], 1.8)
        self.assertIn("avg_profit_factor", d["best_validated"])
        self.assertEqual(d["best_validated"]["avg_profit_factor"], 1.8)


if __name__ == "__main__":
    unittest.main()
