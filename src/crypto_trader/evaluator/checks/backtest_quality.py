"""Backtest quality check: n_trades, Sharpe significance, OOS efficiency."""

from __future__ import annotations

import math
import re
from typing import Any

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import CheckResult, EvalContext, Grade

MIN_TRADES_FAIL = 10
MIN_TRADES_WARN = 30
MIN_OOS_EFFICIENCY = 0.3
MIN_SHARPE_SIGNIFICANCE = 0.5


def _parse_backtest_entries(text: str) -> list[dict[str, Any]]:
    """Parse backtest history markdown lines into structured entries."""
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        n_match = re.search(r"n=(\d+)", line)
        sharpe_match = re.search(r"Sharpe[=:]\s*([+-]?[\d.]+)", line)
        oos_match = re.search(r"OOS효율[=:]\s*([\d.]+)", line)
        wr_match = re.search(r"WR[=:]\s*([\d.]+)%", line)
        if n_match:
            entry: dict[str, Any] = {"n_trades": int(n_match.group(1))}
            if sharpe_match:
                entry["sharpe"] = float(sharpe_match.group(1))
            if oos_match:
                entry["oos_efficiency"] = float(oos_match.group(1))
            if wr_match:
                entry["win_rate"] = float(wr_match.group(1)) / 100.0
            entries.append(entry)
    return entries


class BacktestQualityCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "backtest_quality"

    def run(self, ctx: EvalContext) -> CheckResult:
        entries = _parse_backtest_entries(ctx.backtest_history_tail)
        if not entries:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["백테스트 히스토리에서 파싱 가능한 항목 없음"],
                metrics={},
                suggestions=["backtest_history.md에 결과 기록 필요"],
            )

        findings: list[str] = []
        suggestions: list[str] = []
        worst_grade = Grade.PASS
        scores: list[float] = []

        for entry in entries:
            n = entry["n_trades"]
            sharpe = entry.get("sharpe", 0.0)
            oos_eff = entry.get("oos_efficiency")

            if n < MIN_TRADES_FAIL:
                worst_grade = Grade.worst([worst_grade, Grade.FAIL])
                findings.append(f"n={n} < {MIN_TRADES_FAIL}: 통계적으로 무의미")
                scores.append(0.0)
            elif n < MIN_TRADES_WARN:
                worst_grade = Grade.worst([worst_grade, Grade.WARN])
                findings.append(f"n={n} < {MIN_TRADES_WARN}: 통계적 신뢰도 부족")
                scores.append(0.4)
            else:
                scores.append(0.8)

            if n > 0 and sharpe > 0:
                significance = sharpe / math.sqrt(n)
                if significance < MIN_SHARPE_SIGNIFICANCE:
                    worst_grade = Grade.worst([worst_grade, Grade.WARN])
                    findings.append(
                        f"Sharpe {sharpe:.2f}/sqrt({n})={significance:.2f}"
                        f" < {MIN_SHARPE_SIGNIFICANCE}: 유의성 부족"
                    )
                    scores.append(0.3)
                else:
                    scores.append(1.0)

            if oos_eff is not None and oos_eff < MIN_OOS_EFFICIENCY:
                worst_grade = Grade.worst([worst_grade, Grade.FAIL])
                findings.append(
                    f"OOS 효율 {oos_eff:.2f} < {MIN_OOS_EFFICIENCY}: 과적합 의심"
                )
                suggestions.append("walk-forward 윈도우 재설정 또는 파라미터 단순화")
                scores.append(0.1)
            elif oos_eff is not None:
                scores.append(min(oos_eff / 0.6, 1.0))

        if not findings:
            findings.append(f"최근 백테스트 {len(entries)}건 — 품질 기준 충족")

        avg_score = sum(scores) / len(scores) if scores else 0.0

        metrics: dict[str, Any] = {
            "entries_parsed": len(entries),
            "avg_n_trades": sum(e["n_trades"] for e in entries) / len(entries),
        }
        sharpes = [e["sharpe"] for e in entries if "sharpe" in e]
        if sharpes:
            metrics["avg_sharpe"] = sum(sharpes) / len(sharpes)

        return CheckResult(
            check_name=self.name,
            grade=worst_grade,
            score=round(min(avg_score, 1.0), 4),
            findings=findings,
            metrics=metrics,
            suggestions=suggestions,
        )
