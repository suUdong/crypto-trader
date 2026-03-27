from __future__ import annotations

import unittest

from scripts.portfolio_optimizer import build_portfolio_allocations


class PortfolioOptimizerTests(unittest.TestCase):
    def test_allocations_use_positive_walk_forward_sharpe_weights(self) -> None:
        tuned_payload = {
            "optimized_results": [
                {"strategy": "momentum", "avg_sharpe": 1.0, "avg_return_pct": 4.0},
                {"strategy": "momentum_pullback", "avg_sharpe": 2.0, "avg_return_pct": 6.0},
            ]
        }
        walk_forward_payload = {
            "strategies": [
                {
                    "strategy": "momentum",
                    "best": {
                        "avg_sharpe": 0.5,
                        "avg_return_pct": 1.0,
                        "avg_profit_factor": 1.1,
                        "validated": False,
                    },
                },
                {
                    "strategy": "momentum_pullback",
                    "best": {
                        "avg_sharpe": 1.5,
                        "avg_return_pct": 2.5,
                        "avg_profit_factor": 1.3,
                        "validated": True,
                    },
                },
            ]
        }

        allocations, score_basis, total_capital = build_portfolio_allocations(
            tuned_payload,
            walk_forward_payload,
            capital_per_strategy=1_000_000.0,
        )

        self.assertEqual(score_basis, "walk_forward_sharpe")
        self.assertEqual(total_capital, 2_000_000.0)
        self.assertEqual(allocations[0].strategy, "momentum_pullback")
        self.assertAlmostEqual(allocations[0].weight, 0.75)
        self.assertAlmostEqual(allocations[1].weight, 0.25)

    def test_allocations_fallback_to_tuned_sharpe_when_oos_scores_non_positive(self) -> None:
        tuned_payload = {
            "optimized_results": [
                {"strategy": "momentum", "avg_sharpe": 1.0, "avg_return_pct": 4.0},
                {"strategy": "momentum_pullback", "avg_sharpe": 3.0, "avg_return_pct": 7.0},
            ]
        }
        walk_forward_payload = {
            "strategies": [
                {
                    "strategy": "momentum",
                    "best": {
                        "avg_sharpe": -0.2,
                        "avg_return_pct": -0.5,
                        "avg_profit_factor": 0.9,
                        "validated": False,
                    },
                },
                {
                    "strategy": "momentum_pullback",
                    "best": {
                        "avg_sharpe": 0.0,
                        "avg_return_pct": 0.1,
                        "avg_profit_factor": 1.0,
                        "validated": False,
                    },
                },
            ]
        }

        allocations, score_basis, _ = build_portfolio_allocations(
            tuned_payload,
            walk_forward_payload,
            capital_per_strategy=1_000_000.0,
        )

        self.assertEqual(score_basis, "tuned_sharpe_fallback")
        self.assertEqual(allocations[0].strategy, "momentum_pullback")
        self.assertAlmostEqual(allocations[0].weight, 0.75)


if __name__ == "__main__":
    unittest.main()
