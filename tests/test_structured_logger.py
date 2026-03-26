"""Tests for StructuredLogger."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.monitoring.structured_logger import StructuredLogger


class TestStructuredLogger(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name)
        self.logger = StructuredLogger(self.log_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _read_events(self) -> list[dict]:
        events_file = self.log_dir / "events.jsonl"
        if not events_file.exists():
            return []
        return [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]

    def _read_wallet_events(self, wallet_name: str) -> list[dict]:
        wallet_file = self.log_dir / f"{wallet_name}.jsonl"
        if not wallet_file.exists():
            return []
        return [json.loads(line) for line in wallet_file.read_text().splitlines() if line.strip()]

    def test_log_signal_writes_to_events_and_wallet_file(self) -> None:
        self.logger.log_signal(
            wallet_name="momentum_wallet",
            strategy_type="momentum",
            symbol="KRW-BTC",
            action="buy",
            reason="breakout",
            confidence=0.85,
            indicators={"rsi": 45.0, "momentum": 0.02},
            market_regime="bull",
        )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["event_type"], "signal")
        self.assertEqual(ev["wallet_name"], "momentum_wallet")
        self.assertEqual(ev["symbol"], "KRW-BTC")
        self.assertEqual(ev["action"], "buy")
        self.assertAlmostEqual(ev["confidence"], 0.85)
        self.assertIn("timestamp", ev)

        wallet_events = self._read_wallet_events("momentum_wallet")
        self.assertEqual(len(wallet_events), 1)

    def test_log_trade_records_fill_details(self) -> None:
        self.logger.log_trade(
            wallet_name="obi_wallet",
            strategy_type="obi",
            symbol="KRW-ETH",
            side="buy",
            quantity=0.5,
            fill_price=3_500_000.0,
            fee_paid=1_750.0,
            order_status="filled",
            reason="obi_signal",
        )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["event_type"], "trade")
        self.assertAlmostEqual(ev["quantity"], 0.5)
        self.assertAlmostEqual(ev["fill_price"], 3_500_000.0)
        self.assertEqual(ev["order_status"], "filled")

    def test_log_rejection_records_reason(self) -> None:
        self.logger.log_rejection(
            wallet_name="mean_reversion_wallet",
            strategy_type="mean_reversion",
            symbol="KRW-XRP",
            side="buy",
            reason="cooldown_active",
            requested_quantity=100.0,
        )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "rejection")
        self.assertEqual(events[0]["reason"], "cooldown_active")

    def test_log_error_includes_traceback(self) -> None:
        try:
            raise ValueError("test error")
        except ValueError as exc:
            self.logger.log_error(
                wallet_name="test_wallet",
                strategy_type="test",
                symbol="KRW-BTC",
                error_message="something failed",
                exc=exc,
            )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["event_type"], "error")
        self.assertIn("ValueError", ev["traceback"])

    def test_log_error_without_exception(self) -> None:
        self.logger.log_error(
            wallet_name="test_wallet",
            strategy_type="test",
            symbol="KRW-BTC",
            error_message="timeout",
        )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["traceback"])

    def test_log_system_event(self) -> None:
        self.logger.log_system(
            wallet_name="portfolio",
            strategy_type="kill_switch",
            symbol="*",
            message="Kill switch triggered",
            details={"dd": 0.15},
        )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "system")
        self.assertEqual(events[0]["details"]["dd"], 0.15)

    def test_multiple_events_append(self) -> None:
        for i in range(5):
            self.logger.log_signal(
                wallet_name="w1",
                strategy_type="momentum",
                symbol="KRW-BTC",
                action="hold",
                reason=f"reason_{i}",
                confidence=0.5,
                indicators={},
                market_regime="sideways",
            )
        events = self._read_events()
        self.assertEqual(len(events), 5)

    def test_per_wallet_file_isolation(self) -> None:
        self.logger.log_signal(
            wallet_name="wallet_a", strategy_type="momentum",
            symbol="KRW-BTC", action="buy", reason="r1",
            confidence=0.7, indicators={}, market_regime="bull",
        )
        self.logger.log_signal(
            wallet_name="wallet_b", strategy_type="obi",
            symbol="KRW-ETH", action="sell", reason="r2",
            confidence=0.6, indicators={}, market_regime="bear",
        )
        a_events = self._read_wallet_events("wallet_a")
        b_events = self._read_wallet_events("wallet_b")
        self.assertEqual(len(a_events), 1)
        self.assertEqual(len(b_events), 1)
        self.assertEqual(a_events[0]["wallet_name"], "wallet_a")
        self.assertEqual(b_events[0]["wallet_name"], "wallet_b")


if __name__ == "__main__":
    unittest.main()
