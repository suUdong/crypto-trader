from __future__ import annotations

import logging
import time

from crypto_trader.monitoring import HealthMonitor
from crypto_trader.pipeline import TradingPipeline


class TradingRuntime:
    def __init__(
        self,
        pipeline: TradingPipeline,
        monitor: HealthMonitor,
        poll_interval_seconds: int,
    ) -> None:
        self._pipeline = pipeline
        self._monitor = monitor
        self._poll_interval_seconds = poll_interval_seconds
        self._logger = logging.getLogger(__name__)

    def run(self, max_iterations: int = 0) -> None:
        iteration = 0
        while True:
            result = self._pipeline.run_once()
            snapshot = self._monitor.record(result, self._pipeline.broker)
            if result.error is None:
                self._logger.info(result.message)
            else:
                self._logger.error(result.message)
            self._logger.info(
                "health success=%s failures=%s positions=%s cash=%.2f",
                snapshot.success,
                snapshot.consecutive_failures,
                snapshot.open_positions,
                snapshot.cash,
            )

            iteration += 1
            if max_iterations > 0 and iteration >= max_iterations:
                return
            time.sleep(self._poll_interval_seconds)
