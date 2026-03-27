from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_trader.models import PromotionStatus
from crypto_trader.operator.promotion import PortfolioPromotionGate

INITIAL_CAPITAL = 1_000_000.0


def _days_ago_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _write_checkpoint(path: Path, wallet_states: dict, generated_at: str) -> None:
    payload = {
        "generated_at": generated_at,
        "wallet_states": wallet_states,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _passing_wallet_states() -> dict:
    """Four wallets: 3 profitable, 1 at break-even-minus (still overall positive)."""
    return {
        "wallet_btc": {
            "equity": INITIAL_CAPITAL * 1.05,
            "realized_pnl": 50_000.0,
            "trade_count": 4,
            "strategy_type": "volatility_breakout",
            "cash": INITIAL_CAPITAL * 0.5,
            "open_positions": 1,
        },
        "wallet_eth": {
            "equity": INITIAL_CAPITAL * 1.03,
            "realized_pnl": 30_000.0,
            "trade_count": 4,
            "strategy_type": "momentum",
            "cash": INITIAL_CAPITAL * 0.6,
            "open_positions": 0,
        },
        "wallet_xrp": {
            "equity": INITIAL_CAPITAL * 1.01,
            "realized_pnl": 10_000.0,
            "trade_count": 2,
            "strategy_type": "mean_reversion",
            "cash": INITIAL_CAPITAL * 0.8,
            "open_positions": 0,
        },
    }


class TestMissingCheckpointReturnsDoNotPromote(unittest.TestCase):
    def test_missing_checkpoint_returns_do_not_promote(self, tmp_path=None) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            missing_path = Path(td) / "nonexistent_checkpoint.json"
            gate = PortfolioPromotionGate()
            decision = gate.evaluate_from_checkpoint(missing_path)
            self.assertEqual(decision.status, PromotionStatus.DO_NOT_PROMOTE)
            self.assertIn("not found", decision.reasons[0].lower())


class TestStayInPaperWhenNoTrades(unittest.TestCase):
    def test_stay_in_paper_when_no_trades(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "checkpoint.json"
            wallet_states = {
                "wallet_btc": {
                    "equity": INITIAL_CAPITAL,
                    "realized_pnl": 0.0,
                    "trade_count": 0,
                    "strategy_type": "volatility_breakout",
                    "cash": INITIAL_CAPITAL,
                    "open_positions": 0,
                },
                "wallet_eth": {
                    "equity": INITIAL_CAPITAL,
                    "realized_pnl": 0.0,
                    "trade_count": 0,
                    "strategy_type": "momentum",
                    "cash": INITIAL_CAPITAL,
                    "open_positions": 0,
                },
            }
            _write_checkpoint(cp, wallet_states, _days_ago_iso(8))
            decision = PortfolioPromotionGate().evaluate_from_checkpoint(cp)
            self.assertEqual(decision.status, PromotionStatus.STAY_IN_PAPER)
            self.assertEqual(decision.total_trades, 0)


class TestStayInPaperWhenInsufficientProfitableWallets(unittest.TestCase):
    def test_stay_in_paper_when_insufficient_profitable_wallets(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "checkpoint.json"
            wallet_states = {
                "wallet_btc": {
                    "equity": INITIAL_CAPITAL * 1.05,
                    "realized_pnl": 50_000.0,
                    "trade_count": 6,
                    "strategy_type": "volatility_breakout",
                    "cash": INITIAL_CAPITAL * 0.5,
                    "open_positions": 0,
                },
                "wallet_eth": {
                    "equity": INITIAL_CAPITAL * 0.98,  # unprofitable
                    "realized_pnl": -20_000.0,
                    "trade_count": 5,
                    "strategy_type": "momentum",
                    "cash": INITIAL_CAPITAL * 0.9,
                    "open_positions": 0,
                },
            }
            _write_checkpoint(cp, wallet_states, _days_ago_iso(8))
            decision = PortfolioPromotionGate().evaluate_from_checkpoint(cp)
            self.assertEqual(decision.status, PromotionStatus.STAY_IN_PAPER)
            self.assertEqual(decision.profitable_wallets, 1)


class TestStayInPaperWhenPortfolioReturnNegative(unittest.TestCase):
    def test_stay_in_paper_when_portfolio_return_negative(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "checkpoint.json"
            # Both wallets slightly below initial capital
            wallet_states = {
                "wallet_btc": {
                    "equity": INITIAL_CAPITAL * 0.999,
                    "realized_pnl": -1_000.0,
                    "trade_count": 6,
                    "strategy_type": "volatility_breakout",
                    "cash": INITIAL_CAPITAL * 0.9,
                    "open_positions": 0,
                },
                "wallet_eth": {
                    "equity": INITIAL_CAPITAL * 0.998,
                    "realized_pnl": -2_000.0,
                    "trade_count": 6,
                    "strategy_type": "momentum",
                    "cash": INITIAL_CAPITAL * 0.9,
                    "open_positions": 0,
                },
            }
            _write_checkpoint(cp, wallet_states, _days_ago_iso(8))
            decision = PortfolioPromotionGate().evaluate_from_checkpoint(cp)
            self.assertEqual(decision.status, PromotionStatus.STAY_IN_PAPER)
            self.assertLess(decision.portfolio_return_pct, 0.0)


class TestCandidateWhenAllCriteriaMet(unittest.TestCase):
    def test_candidate_when_all_criteria_met(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "checkpoint.json"
            _write_checkpoint(cp, _passing_wallet_states(), _days_ago_iso(8))
            decision = PortfolioPromotionGate().evaluate_from_checkpoint(cp)
            self.assertEqual(decision.status, PromotionStatus.CANDIDATE_FOR_PROMOTION)
            self.assertGreaterEqual(decision.paper_days, 7)
            self.assertGreaterEqual(decision.total_trades, 10)
            self.assertGreaterEqual(decision.profitable_wallets, 2)
            self.assertGreater(decision.portfolio_return_pct, 0.0)


class TestSaveWritesJson(unittest.TestCase):
    def test_save_writes_json(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "checkpoint.json"
            out = Path(td) / "subdir" / "decision.json"
            _write_checkpoint(cp, _passing_wallet_states(), _days_ago_iso(8))
            gate = PortfolioPromotionGate()
            decision = gate.evaluate_from_checkpoint(cp)
            gate.save(decision, out)

            self.assertTrue(out.exists())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("status", data)
            self.assertIn("reasons", data)
            self.assertIn("wallet_count", data)
            self.assertIn("total_equity", data)
            self.assertIn("portfolio_return_pct", data)
            self.assertIn("profitable_wallets", data)
            self.assertIn("total_trades", data)
            self.assertIn("paper_days", data)
            self.assertIn("per_wallet", data)
            self.assertIn("generated_at", data)
            # status must be serialized as string value, not enum object
            self.assertIsInstance(data["status"], str)


class TestPerWalletBreakdownPopulated(unittest.TestCase):
    def test_per_wallet_breakdown_populated(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "checkpoint.json"
            wallet_states = _passing_wallet_states()
            _write_checkpoint(cp, wallet_states, _days_ago_iso(8))
            decision = PortfolioPromotionGate().evaluate_from_checkpoint(cp)

            self.assertEqual(set(decision.per_wallet.keys()), set(wallet_states.keys()))
            for _name, entry in decision.per_wallet.items():
                self.assertIn("equity", entry)
                self.assertIn("realized_pnl", entry)
                self.assertIn("trades", entry)
                self.assertIn("return_pct", entry)
                # return_pct must match equity vs initial capital
                expected_return = (entry["equity"] - INITIAL_CAPITAL) / INITIAL_CAPITAL
                self.assertAlmostEqual(entry["return_pct"], expected_return, places=8)


if __name__ == "__main__":
    unittest.main()
