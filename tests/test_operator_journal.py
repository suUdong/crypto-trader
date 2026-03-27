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
                    market_regime="sideways",
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
                    session_id="session-1",
                )
            )
            records = journal.load_recent()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].symbol, "KRW-BTC")
            self.assertEqual(records[0].verdict_status, "continue_paper")
            self.assertEqual(records[0].session_id, "session-1")
            self.assertIsNone(records[0].order_type)

    def test_append_and_load_recent_preserves_order_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = StrategyRunJournal(Path(temp_dir) / "runs.jsonl")
            journal.append(
                StrategyRunRecord(
                    recorded_at="2026-03-23T00:00:00Z",
                    symbol="KRW-BTC",
                    latest_price=100.0,
                    market_regime="sideways",
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
                    session_id="session-1",
                    order_type="limit",
                )
            )

            records = journal.load_recent()

            self.assertEqual(records[0].order_type, "limit")

    def test_load_recent_accepts_legacy_records_without_market_regime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runs.jsonl"
            path.write_text(
                '{"recorded_at":"2026-03-23T00:00:00Z","symbol":"KRW-BTC","latest_price":100.0,'
                '"signal_action":"hold","signal_reason":"noop","signal_confidence":0.5,'
                '"order_status":null,"order_side":null,"session_starting_equity":1000.0,'
                '"cash":1000.0,"open_positions":0,"realized_pnl":0.0,"success":true,'
                '"error":null,"consecutive_failures":0,"verdict_status":"continue_paper",'
                '"verdict_confidence":0.6,"verdict_reasons":[]}\n',
                encoding="utf-8",
            )
            records = StrategyRunJournal(path).load_recent()
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0].market_regime)
            self.assertEqual(records[0].session_id, "")

    def test_load_recent_returns_empty_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = StrategyRunJournal(Path(temp_dir) / "nonexistent.jsonl")
            records = journal.load_recent()
            self.assertEqual(records, [])

    def test_load_recent_respects_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = StrategyRunJournal(Path(temp_dir) / "runs.jsonl")
            for i in range(5):
                journal.append(
                    StrategyRunRecord(
                        recorded_at=f"2026-03-23T0{i}:00:00Z",
                        symbol="KRW-BTC",
                        latest_price=100.0,
                        market_regime="sideways",
                        signal_action="hold",
                        signal_reason="noop",
                        signal_confidence=0.5,
                        order_status=None,
                        order_side=None,
                        session_starting_equity=1_000.0,
                        cash=1_000.0,
                        open_positions=0,
                        realized_pnl=0.0,
                        success=True,
                        error=None,
                        consecutive_failures=0,
                        verdict_status="continue_paper",
                        verdict_confidence=0.6,
                        verdict_reasons=[],
                    )
                )
            records = journal.load_recent(limit=3)
            self.assertEqual(len(records), 3)
