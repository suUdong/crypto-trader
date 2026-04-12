"""Opus formatter + fallback for evaluation reports."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from crypto_trader.evaluator.models import EvaluationReport

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def fallback_format(report: EvaluationReport) -> str:
    """Template-based formatting when Opus is unavailable."""
    lines = [f"[평가 {report.eval_id}] {report.timestamp[:16]}"]
    lines.append(
        f"종합: {report.overall_grade.value} (score={report.overall_score:.2f})"
    )
    for cr in report.check_results:
        emoji = {"pass": "✅", "warn": "⚠️", "fail": "🔴", "skip": "⏭️"}.get(
            cr.grade.value, "❓"
        )
        summary = "; ".join(cr.findings[:2]) if cr.findings else "—"
        lines.append(f"  {emoji} {cr.check_name}: {cr.grade.value} — {summary}")
    if any(cr.suggestions for cr in report.check_results):
        lines.append("제안:")
        for cr in report.check_results:
            for s in cr.suggestions[:2]:
                lines.append(f"  • {s}")
    return "\n".join(lines)


def _build_opus_prompt(report: EvaluationReport) -> str:
    """Build a prompt for Opus to format the report."""
    checks_block = ""
    for cr in report.check_results:
        checks_block += (
            f"\n### {cr.check_name}: {cr.grade.value} (score={cr.score:.2f})\n"
            f"- 발견: {'; '.join(cr.findings)}\n"
            f"- 메트릭: {json.dumps(cr.metrics, ensure_ascii=False)}\n"
        )
        if cr.suggestions:
            checks_block += f"- 제안: {'; '.join(cr.suggestions)}\n"

    return f"""당신은 트레이딩 전략 평가 결과를 정리하는 리포터입니다.
아래 정량 평가 결과를 사람이 읽기 좋은 한국어 요약으로 변환하세요.

## 판정 결과 (변경 금지)
종합 등급: {report.overall_grade.value}
종합 점수: {report.overall_score:.2f}
트리거: {report.trigger_reason}
{checks_block}

## 지시사항
- 위 판정 결과의 등급을 변경하거나 재해석하지 마세요.
- 핵심 수치는 반드시 포함하세요.
- 반드시 아래 JSON을 마크다운 코드블록으로 출력하세요:

```json
{{{{
  "telegram_summary": "5-8줄, 이모지 포함, 한국어 요약",
  "detailed_summary": "섹션별 분석, 마크다운 포맷"
}}}}
```
"""


def _call_opus(prompt: str, timeout: int = 120) -> str | None:
    """Call Claude CLI for Opus formatting."""
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
        )
        output = result.stdout.strip()
        return output if output else None
    except Exception:
        return None


def _parse_opus_response(raw: str) -> dict[str, str] | None:
    """Extract JSON from Opus response."""
    m = re.search(r"```json\s*([\s\S]+?)\s*```", raw)
    if not m:
        return None
    try:
        parsed: dict[str, Any] = json.loads(m.group(1))
        return {
            "telegram_summary": str(parsed.get("telegram_summary", "")),
            "detailed_summary": str(parsed.get("detailed_summary", "")),
        }
    except (json.JSONDecodeError, KeyError):
        return None


def format_report(
    report: EvaluationReport, *, dry_run: bool = False
) -> EvaluationReport:
    """Format the report using Opus, falling back to template.

    Returns the same report with summary fields populated.
    """
    if dry_run:
        fb = fallback_format(report)
        report.telegram_summary = fb
        report.summary_for_human = fb
        return report

    prompt = _build_opus_prompt(report)
    raw = _call_opus(prompt)
    if raw:
        parsed = _parse_opus_response(raw)
        if parsed:
            report.telegram_summary = parsed["telegram_summary"]
            report.summary_for_human = parsed["detailed_summary"]
            return report

    fb = fallback_format(report)
    report.telegram_summary = fb
    report.summary_for_human = fb
    return report
