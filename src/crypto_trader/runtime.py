from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from crypto_trader.models import RuntimeCheckpoint, StrategyRunRecord
from crypto_trader.monitoring import HealthMonitor
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.paper_trading import PaperTradingOperations
from crypto_trader.operator.runtime_state import RuntimeCheckpointStore
from crypto_trader.operator.verdicts import StrategyVerdictEngine
from crypto_trader.pipeline import TradingPipeline


class TradingRuntime:
    def __init__(
        self,
        pipeline: TradingPipeline,
        monitor: HealthMonitor,
        journal: StrategyRunJournal,
        verdict_engine: StrategyVerdictEngine,
        paper_trading_operations: PaperTradingOperations,
        checkpoint_store: RuntimeCheckpointStore,
        poll_interval_seconds: int,
    ) -> None:
        self._pipeline = pipeline
        self._monitor = monitor
        self._journal = journal
        self._verdict_engine = verdict_engine
        self._paper_trading_operations = paper_trading_operations
        self._checkpoint_store = checkpoint_store
        self._poll_interval_seconds = poll_interval_seconds
        self._logger = logging.getLogger(__name__)

    def run(self, max_iterations: int = 0) -> None:
        checkpoint = self._checkpoint_store.load()
        iteration = 0 if checkpoint is None else checkpoint.iteration
        while True:
            result = self._pipeline.run_once()
            snapshot = self._monitor.record(result, self._pipeline.broker)
            recent_runs = self._journal.load_recent()
            verdict = self._verdict_engine.evaluate(
                consecutive_failures=snapshot.consecutive_failures,
                realized_pnl=self._pipeline.broker.realized_pnl,
                session_starting_equity=self._pipeline.session_starting_equity,
                current_success=result.error is None,
                recent_runs=recent_runs,
            )
            record = StrategyRunRecord(
                recorded_at=snapshot.updated_at,
                symbol=result.symbol,
                latest_price=result.latest_price,
                market_regime=result.signal.context.get("market_regime"),
                signal_action=result.signal.action.value,
                signal_reason=result.signal.reason,
                signal_confidence=result.signal.confidence,
                order_status=None if result.order is None else result.order.status,
                order_side=None if result.order is None else result.order.side.value,
                session_starting_equity=self._pipeline.session_starting_equity,
                cash=self._pipeline.broker.cash,
                open_positions=len(self._pipeline.broker.positions),
                realized_pnl=self._pipeline.broker.realized_pnl,
                success=result.error is None,
                error=result.error,
                consecutive_failures=snapshot.consecutive_failures,
                verdict_status=verdict.status.value,
                verdict_confidence=verdict.confidence,
                verdict_reasons=verdict.reasons,
            )
            self._journal.append(record)
            latest_prices = {}
            if result.latest_price is not None:
                latest_prices[result.symbol] = result.latest_price
            self._paper_trading_operations.sync(self._pipeline.broker, latest_prices)
            self._checkpoint_store.save(
                RuntimeCheckpoint(
                    generated_at=datetime.now(UTC).isoformat(),
                    iteration=iteration + 1,
                    symbol=result.symbol,
                    latest_price=result.latest_price,
                    last_signal_action=result.signal.action.value,
                    last_verdict_status=verdict.status.value,
                    success=result.error is None,
                    error=result.error,
                    cash=self._pipeline.broker.cash,
                    mark_to_market_equity=self._pipeline.broker.equity(latest_prices),
                )
            )
            if result.error is None:
                self._logger.info(result.message)
            else:
                self._logger.error(result.message)
            self._logger.info(
                "health success=%s failures=%s positions=%s cash=%.2f verdict=%s",
                snapshot.success,
                snapshot.consecutive_failures,
                snapshot.open_positions,
                snapshot.cash,
                verdict.status.value,
            )

            iteration += 1
            if max_iterations > 0 and iteration >= max_iterations:
                return
            time.sleep(self._poll_interval_seconds)
