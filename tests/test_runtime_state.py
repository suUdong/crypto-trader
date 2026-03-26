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
                symbols=["KRW-BTC", "KRW-ETH"],
                wallet_states={
                    "momentum_wallet": {
                        "strategy_type": "momentum",
                        "cash": 1_000.0,
                        "realized_pnl": 0.0,
                        "open_positions": 0,
                        "equity": 1_000.0,
                        "trade_count": 0,
                    },
                },
            )
            store.save(checkpoint)
            loaded = store.load()
            assert loaded is not None
            self.assertEqual(loaded.iteration, 5)
            self.assertEqual(loaded.symbols, ["KRW-BTC", "KRW-ETH"])
            self.assertIn("momentum_wallet", loaded.wallet_states)

    def test_load_returns_none_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing.json"
            store = RuntimeCheckpointStore(path)
            self.assertIsNone(store.load())

    def test_save_overwrites_previous_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "checkpoint.json"
            store = RuntimeCheckpointStore(path)
            cp1 = RuntimeCheckpoint(
                generated_at="2026-03-24T00:00:00Z",
                iteration=1,
                symbols=["KRW-BTC"],
                wallet_states={
                    "w1": {"strategy_type": "momentum", "cash": 1_000.0,
                           "realized_pnl": 0.0, "open_positions": 0,
                           "equity": 1_000.0, "trade_count": 0},
                },
            )
            store.save(cp1)
            cp2 = RuntimeCheckpoint(
                generated_at="2026-03-24T01:00:00Z",
                iteration=10,
                symbols=["KRW-BTC", "KRW-ETH"],
                wallet_states={
                    "w1": {"strategy_type": "momentum", "cash": 900.0,
                           "realized_pnl": 50.0, "open_positions": 1,
                           "equity": 950.0, "trade_count": 3},
                },
            )
            store.save(cp2)
            loaded = store.load()
            assert loaded is not None
            self.assertEqual(loaded.iteration, 10)
            self.assertEqual(loaded.symbols, ["KRW-BTC", "KRW-ETH"])
