from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import PipelineResult, Signal, SignalAction
from crypto_trader.monitoring import HealthMonitor


class HealthMonitorTests(unittest.TestCase):
    def test_monitor_writes_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "health.json"
            monitor = HealthMonitor(path)
            broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0)
            result = PipelineResult(
                symbol="KRW-BTC",
                signal=Signal(action=SignalAction.HOLD, reason="ok", confidence=1.0),
                order=None,
                message="ok",
            )
            snapshot = monitor.record(result, broker)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(snapshot.success)
            self.assertEqual(payload["open_positions"], 0)
            self.assertEqual(payload["cash"], 1_000.0)
