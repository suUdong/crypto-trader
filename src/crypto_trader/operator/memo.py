from __future__ import annotations

from pathlib import Path

from crypto_trader.models import DriftReport, PromotionGateDecision, StrategyRunRecord


class OperatorDailyMemo:
    def render(
        self,
        *,
        latest_run: StrategyRunRecord | None,
        drift_report: DriftReport,
        promotion_decision: PromotionGateDecision,
    ) -> str:
        run_section = self._render_run_section(latest_run)
        drift_reasons = "\n".join(f"- {reason}" for reason in drift_report.reasons)
        promotion_reasons = "\n".join(f"- {reason}" for reason in promotion_decision.reasons)

        return f"""# Strategy Lab Daily Memo

## Run Snapshot
{run_section}

## Drift Status

- Status: `{drift_report.status.value}`
- Paper realized PnL: `{drift_report.paper_realized_pnl_pct:.2%}`
- Backtest return: `{drift_report.backtest_total_return_pct:.2%}`
- Paper runs observed: `{drift_report.paper_run_count}`

Reasons:
{drift_reasons}

## Promotion Gate

- Decision: `{promotion_decision.status.value}`
- Minimum paper runs required: `{promotion_decision.minimum_paper_runs_required}`
- Observed paper runs: `{promotion_decision.observed_paper_runs}`

Reasons:
{promotion_reasons}
"""

    def save(self, content: str, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _render_run_section(self, latest_run: StrategyRunRecord | None) -> str:
        if latest_run is None:
            return "- No strategy runs have been recorded yet."
        return (
            f"- Recorded at: `{latest_run.recorded_at}`\n"
            f"- Symbol: `{latest_run.symbol}`\n"
            f"- Market regime: `{latest_run.market_regime}`\n"
            f"- Signal: `{latest_run.signal_action}` ({latest_run.signal_reason})\n"
            f"- Verdict: `{latest_run.verdict_status}`\n"
            f"- Latest price: `{latest_run.latest_price}`\n"
            f"- Cash: `{latest_run.cash:.2f}`\n"
            f"- Realized PnL: `{latest_run.realized_pnl:.2f}`\n"
            f"- Consecutive failures: `{latest_run.consecutive_failures}`"
        )
