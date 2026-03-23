from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crypto_trader.models import StrategyRunRecord
from crypto_trader.operator.journal import StrategyRunJournal


class StrategyRunJournalTests(unittest.TestCase):
    def test_append_and_load_recent_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = StrategyRunJournal(Path(temp_dir) / "runs.jsonl")
            journal.append(
                StrategyRunRecord(
                    recorded_at="2026-03-23T00:00:00Z",
                    symbol="KRW-BTC",
                    latest_price=100.0,
                    signal_action="buy",
                    signal_reason="entry",
                    signal_confidence=0.8,
                    order_status="filled",
                    order_side="buy",
                    session_starting_equity=1_000.0,
                    cash=900.0,
                    open_positions=1,
                    realized_pnl=0.0,
                    success=True,
                    error=None,
                    consecutive_failures=0,
                    verdict_status="continue_paper",
                    verdict_confidence=0.6,
                    verdict_reasons=["ok"],
                )
            )
            records = journal.load_recent()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].symbol, "KRW-BTC")
            self.assertEqual(records[0].verdict_status, "continue_paper")
