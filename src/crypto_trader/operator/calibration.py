from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.models import (
    BacktestBaseline,
    DriftCalibrationEntry,
    DriftCalibrationReport,
    StrategyRunRecord,
)


class DriftCalibrationToolkit:
    def generate(
        self,
        *,
        symbol: str,
        backtest_baseline: BacktestBaseline,
        recent_runs: list[StrategyRunRecord],
    ) -> DriftCalibrationReport:
        entries: list[DriftCalibrationEntry] = []
        by_regime: dict[str, list[StrategyRunRecord]] = {}
        for run in recent_runs:
            regime = run.market_regime or "unknown"
            by_regime.setdefault(regime, []).append(run)

        for regime, runs in sorted(by_regime.items()):
            expected = backtest_baseline.total_return_pct
            gaps = [
                abs(expected - (run.realized_pnl / max(1.0, run.session_starting_equity)))
                for run in runs
            ]
            average_abs_gap = sum(gaps) / len(gaps)
            error_rate = sum(1 for run in runs if not run.success) / len(runs)
            entries.append(
                DriftCalibrationEntry(
                    regime=regime,
                    sample_count=len(runs),
                    average_abs_return_gap_pct=average_abs_gap,
                    suggested_return_tolerance_pct=max(0.02, average_abs_gap * 1.5),
                    observed_error_rate=error_rate,
                    suggested_error_rate_threshold=max(0.05, error_rate * 1.5),
                )
            )

        return DriftCalibrationReport(
            generated_at=datetime.now(UTC).isoformat(),
            symbol=symbol,
            entries=entries,
        )

    def save(self, report: DriftCalibrationReport, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
