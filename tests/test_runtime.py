from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_trader.config import RiskConfig
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import PipelineResult, Signal, SignalAction
from crypto_trader.monitoring import HealthMonitor
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.verdicts import StrategyVerdictEngine
from crypto_trader.runtime import TradingRuntime


class FakePipeline:
    def __init__(self) -> None:
        self.broker = PaperBroker(starting_cash=1_000.0, fee_rate=0.0, slippage_pct=0.0)
        self.session_starting_equity = 1_000.0

    def run_once(self) -> PipelineResult:
        return PipelineResult(
            symbol="KRW-BTC",
            signal=Signal(
                action=SignalAction.HOLD,
                reason="noop",
                confidence=0.5,
                context={"market_regime": "sideways"},
            ),
            order=None,
            message="noop",
            latest_price=100.0,
        )


class TradingRuntimeTests(unittest.TestCase):
    def test_runtime_records_strategy_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = TradingRuntime(
                pipeline=FakePipeline(),
                monitor=HealthMonitor(Path(temp_dir) / "health.json"),
                journal=StrategyRunJournal(Path(temp_dir) / "runs.jsonl"),
                verdict_engine=StrategyVerdictEngine(RiskConfig()),
                poll_interval_seconds=1,
            )
            runtime.run(max_iterations=1)
            lines = (Path(temp_dir) / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["verdict_status"], "continue_paper")
            self.assertEqual(payload["symbol"], "KRW-BTC")
