from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crypto_trader.models import RuntimeCheckpoint
from crypto_trader.operator.runtime_state import RuntimeCheckpointStore


class RuntimeCheckpointStoreTests(unittest.TestCase):
    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "checkpoint.json"
            store = RuntimeCheckpointStore(path)
            checkpoint = RuntimeCheckpoint(
                generated_at="2026-03-24T00:00:00Z",
                iteration=5,
                symbol="KRW-BTC",
                latest_price=100.0,
                last_signal_action="hold",
                last_verdict_status="continue_paper",
                success=True,
                error=None,
                cash=1_000.0,
                mark_to_market_equity=1_000.0,
            )
            store.save(checkpoint)
            loaded = store.load()
            assert loaded is not None
            self.assertEqual(loaded.iteration, 5)
            self.assertEqual(loaded.symbol, "KRW-BTC")
