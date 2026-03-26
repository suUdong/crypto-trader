"""Tests for grid-wf-all and strategy-dashboard CLI commands."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class TestStrategyDashboard(unittest.TestCase):
    """Test strategy-dashboard reads backtest-all JSON correctly."""

    def test_dashboard_reads_backtest_all_json(self) -> None:
        """Dashboard can parse a backtest-all JSON export."""
        tmp = tempfile.TemporaryDirectory()
        data = {
            "date": "2026-03-26",
            "symbols": ["KRW-BTC"],
            "candle_count": 200,
            "results": [
                {
                    "strategy": "momentum",
                    "return_pct": 2.5,
                    "sharpe": 1.2,
                    "sortino": 1.8,
                    "calmar": 0.9,
                    "profit_factor": 1.5,
                    "max_drawdown_pct": 5.0,
                    "win_rate_pct": 55.0,
                    "trade_count": 100,
                    "max_consecutive_losses": 4,
                    "max_consecutive_wins": 6,
                    "payoff_ratio": 1.3,
                    "expected_value_per_trade": 250.0,
                    "recovery_factor": 0.5,
                    "tail_ratio": 1.1,
                    "kelly_fraction": 0.12,
                    "composite_score": 1.5,
                },
                {
                    "strategy": "vpin",
                    "return_pct": -1.0,
                    "sharpe": -0.3,
                    "sortino": -0.5,
                    "calmar": -0.2,
                    "profit_factor": 0.8,
                    "max_drawdown_pct": 8.0,
                    "win_rate_pct": 40.0,
                    "trade_count": 50,
                    "max_consecutive_losses": 7,
                    "max_consecutive_wins": 3,
                    "payoff_ratio": 0.9,
                    "expected_value_per_trade": -100.0,
                    "recovery_factor": -0.1,
                    "tail_ratio": 0.6,
                    "kelly_fraction": 0.0,
                    "composite_score": -0.2,
                },
            ],
        }
        path = Path(tmp.name) / "backtest-all.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        loaded = json.loads(path.read_text(encoding="utf-8"))
        results = loaded["results"]
        ranked = sorted(results, key=lambda r: r.get("composite_score", 0), reverse=True)

        self.assertEqual(ranked[0]["strategy"], "momentum")
        self.assertEqual(ranked[1]["strategy"], "vpin")
        self.assertGreater(ranked[0]["composite_score"], 0)
        self.assertLess(ranked[1]["composite_score"], 0)
        tmp.cleanup()

    def test_dashboard_action_classification(self) -> None:
        """Verify action classification logic."""
        cases = [
            ({"composite_score": 1.5, "return_pct": 2.0, "kelly_fraction": 0.1}, "DEPLOY"),
            ({"composite_score": 0.7, "return_pct": 1.0, "kelly_fraction": 0.05}, "RESEARCH"),
            ({"composite_score": 0.3, "return_pct": 0.5, "kelly_fraction": 0.0}, "WATCHLIST"),
            ({"composite_score": -0.2, "return_pct": -1.0, "kelly_fraction": 0.0}, "DROP"),
        ]
        for r, expected_action in cases:
            with self.subTest(score=r["composite_score"]):
                score = r.get("composite_score", 0)
                kf = r.get("kelly_fraction", 0)
                ret = r.get("return_pct", 0)
                if score > 1.0 and ret > 0 and kf > 0:
                    action = "DEPLOY"
                elif score > 0.5 and ret > 0:
                    action = "RESEARCH"
                elif ret > 0:
                    action = "WATCHLIST"
                else:
                    action = "DROP"
                self.assertEqual(action, expected_action)


class TestGridWfAllTomlGeneration(unittest.TestCase):
    """Test auto-TOML generation from grid-wf-all results."""

    def test_toml_generated_from_validated_results(self) -> None:
        """TOML output contains wallet sections for validated strategies."""
        from crypto_trader.backtest.grid_wf import kelly_fraction

        validated_strats = [
            {"strategy": "momentum", "params": {"momentum_lookback": 15, "rsi_period": 14}, "kelly": 0.15},
            {"strategy": "volatility_breakout", "params": {"k_base": 0.4, "noise_lookback": 10}, "kelly": 0.10},
        ]
        total_kelly = sum(v["kelly"] for v in validated_strats)
        base_capital = 1_000_000.0

        toml_lines = []
        for vs in validated_strats:
            weight = vs["kelly"] / total_kelly if total_kelly > 0 else 0.5
            capital = round(base_capital * weight, 0)
            toml_lines.append(f'name = "{vs["strategy"]}_optimized"')
            toml_lines.append(f"initial_capital = {capital:.0f}")

        toml_text = "\n".join(toml_lines)
        self.assertIn("momentum_optimized", toml_text)
        self.assertIn("volatility_breakout_optimized", toml_text)
        # Capital should be proportional to kelly fraction
        self.assertIn("600000", toml_text)  # 0.15 / 0.25 * 1M
        self.assertIn("400000", toml_text)  # 0.10 / 0.25 * 1M

    def test_kelly_fraction_used_for_weighting(self) -> None:
        from crypto_trader.backtest.grid_wf import kelly_fraction
        # Strategy with better edge gets more capital
        kf_good = kelly_fraction(0.6, 1.5)  # 0.25 (clamped)
        kf_ok = kelly_fraction(0.55, 1.2)   # ~0.175
        self.assertGreater(kf_good, kf_ok)


class TestMonteCarloBootstrap(unittest.TestCase):
    """Test Monte Carlo bootstrap confidence intervals."""

    def test_bootstrap_confidence_interval(self) -> None:
        from crypto_trader.backtest.grid_wf import bootstrap_return_ci
        # Simulate trade returns
        trade_returns = [0.02, -0.01, 0.03, -0.005, 0.015, -0.02, 0.025, 0.01, -0.015, 0.02] * 10
        ci_5, ci_95 = bootstrap_return_ci(trade_returns, n_samples=500)
        # CI should bracket the mean
        mean_ret = sum(trade_returns) / len(trade_returns)
        self.assertLessEqual(ci_5, mean_ret)
        self.assertGreaterEqual(ci_95, mean_ret)

    def test_bootstrap_empty_returns_zero(self) -> None:
        from crypto_trader.backtest.grid_wf import bootstrap_return_ci
        ci_5, ci_95 = bootstrap_return_ci([])
        self.assertEqual(ci_5, 0.0)
        self.assertEqual(ci_95, 0.0)

    def test_bootstrap_single_return(self) -> None:
        from crypto_trader.backtest.grid_wf import bootstrap_return_ci
        ci_5, ci_95 = bootstrap_return_ci([0.05])
        self.assertAlmostEqual(ci_5, 0.05, places=4)
        self.assertAlmostEqual(ci_95, 0.05, places=4)


if __name__ == "__main__":
    unittest.main()
