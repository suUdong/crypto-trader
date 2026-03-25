from __future__ import annotations

from pathlib import Path
from typing import Any

from crypto_trader.models import DriftReport, PromotionGateDecision, StrategyRunRecord


class OperatorDailyMemo:
    def render(
        self,
        *,
        latest_run: StrategyRunRecord | None,
        drift_report: DriftReport,
        promotion_decision: PromotionGateDecision,
        macro_summary: dict[str, Any] | None = None,
    ) -> str:
        run_section = self._render_run_section(latest_run)
        drift_reasons = "\n".join(f"- {reason}" for reason in drift_report.reasons)
        promotion_reasons = "\n".join(f"- {reason}" for reason in promotion_decision.reasons)
        macro_section = self._render_macro_section(macro_summary)

        return f"""# Strategy Lab Daily Memo

## Run Snapshot
{run_section}
{macro_section}
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

    def _render_macro_section(self, macro_summary: dict[str, Any] | None) -> str:
        if macro_summary is None:
            return ""
        regime = macro_summary.get("overall_regime", "unknown")
        confidence = macro_summary.get("overall_confidence", 0.0)
        layers = macro_summary.get("layers", {})
        crypto_signals = macro_summary.get("crypto_signals", {})

        lines = [
            "## Macro Environment",
            "",
            f"- Overall regime: `{regime}` (confidence: `{confidence:.0%}`)",
        ]
        for name, layer in layers.items():
            lines.append(
                f"- {name}: `{layer['regime']}` (confidence: `{layer['confidence']:.0%}`)"
            )

        btc_dom = crypto_signals.get("btc_dominance")
        kimchi = crypto_signals.get("kimchi_premium")
        fg = crypto_signals.get("fear_greed_index")

        lines.append("")
        lines.append("Crypto signals:")
        btc_str = f"`{btc_dom:.1f}%`" if btc_dom is not None else "`N/A`"
        kimchi_str = f"`{kimchi:.1f}%`" if kimchi is not None else "`N/A`"
        lines.append(f"- BTC dominance: {btc_str}")
        lines.append(f"- Kimchi premium: {kimchi_str}")
        lines.append(f"- Fear & Greed: `{fg}`" if fg is not None else "- Fear & Greed: `N/A`")
        lines.append("")

        return "\n".join(lines) + "\n"

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
