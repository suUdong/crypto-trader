from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from crypto_trader.models import (
    BacktestBaseline,
    DriftCalibrationReport,
    DriftReport,
    OperatorReport,
    PromotionGateDecision,
    RegimeReport,
)


class OperatorReportBuilder:
    def build(
        self,
        *,
        baseline: BacktestBaseline,
        regime_report: RegimeReport,
        drift_report: DriftReport,
        promotion_decision: PromotionGateDecision,
        memo: str,
        calibration_report: DriftCalibrationReport | None = None,
    ) -> OperatorReport:
        calibration_section = self._render_calibration(calibration_report)
        markdown = f"""# Operator Report

## Baseline
- Symbol: `{baseline.symbol}`
- Interval: `{baseline.interval}`
- Candle count: `{baseline.candle_count}`
- Return: `{baseline.total_return_pct:.2%}`
- Win rate: `{baseline.win_rate:.2%}`
- Max drawdown: `{baseline.max_drawdown:.2%}`
- Trade count: `{baseline.trade_count}`

## Regime
- Market regime: `{regime_report.market_regime}`
- Short return: `{regime_report.short_return_pct:.2%}`
- Long return: `{regime_report.long_return_pct:.2%}`

Reasons:
{chr(10).join(f"- {reason}" for reason in regime_report.reasons)}

## Drift
- Drift status: `{drift_report.status.value}`
- Paper runs: `{drift_report.paper_run_count}`
- Paper realized PnL: `{drift_report.paper_realized_pnl_pct:.2%}`

Reasons:
{chr(10).join(f"- {reason}" for reason in drift_report.reasons)}

## Promotion
- Promotion status: `{promotion_decision.status.value}`
- Observed paper runs: `{promotion_decision.observed_paper_runs}`

Reasons:
{chr(10).join(f"- {reason}" for reason in promotion_decision.reasons)}

{calibration_section}

## Daily Memo
{memo}
"""
        return OperatorReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            symbol=baseline.symbol,
            market_regime=regime_report.market_regime,
            drift_status=drift_report.status.value,
            promotion_status=promotion_decision.status.value,
            report_markdown=markdown,
        )

    def save(self, report: OperatorReport, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report.report_markdown, encoding="utf-8")

    def _render_calibration(self, report: DriftCalibrationReport | None) -> str:
        if report is None or not report.entries:
            return "## Calibration\n- No calibration artifact available."
        lines = ["## Calibration"]
        for entry in report.entries:
            lines.append(
                f"- `{entry.regime}`: samples={entry.sample_count}, "
                f"suggested_return_tolerance={entry.suggested_return_tolerance_pct:.2%}, "
                f"suggested_error_threshold={entry.suggested_error_rate_threshold:.2%}"
            )
        return "\n".join(lines)
