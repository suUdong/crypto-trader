from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def build_quality_summary(quality_log: Sequence[dict[str, Any]]) -> str:
    if not quality_log:
        return ""
    promising = [q for q in quality_log if q.get("grade") == "promising"]
    marginal = [q for q in quality_log if q.get("grade") == "marginal"]
    poor = [q for q in quality_log if q.get("grade") == "poor"]
    lines: list[str] = []
    if promising:
        lines.append(
            "✅ 유망 결과: "
            + ", ".join(
                f"{q['id']}(Sharpe{q.get('sharpe', '?'):+.2f})" for q in promising[-5:]
            )
        )
    if marginal:
        lines.append(
            "🔶 추가검증 필요: "
            + ", ".join(
                f"{q['id']}(Sharpe{q.get('sharpe', '?'):+.2f})" for q in marginal[-5:]
            )
        )
    if poor:
        lines.append(
            "🔻 엣지 부족 (재탐색 불필요): "
            + ", ".join(q["id"] for q in poor[-5:])
        )
    return "\n".join(lines)


def build_promising_summary(quality_log: Sequence[dict[str, Any]]) -> str:
    promising = [q for q in quality_log if q.get("grade") == "promising"]
    return (
        "\n".join(
            f"  - {q['id']}: Sharpe {q.get('sharpe', 0):+.2f} — {q.get('reason', '')}"
            for q in promising[-5:]
        )
        or "  없음"
    )


def build_poor_ids(quality_log: Sequence[dict[str, Any]]) -> list[str]:
    return [str(q["id"]) for q in quality_log if q.get("grade") == "poor"]


def build_quality_review_lines(quality_log: Sequence[dict[str, Any]]) -> str:
    promising_items = [q for q in quality_log if q.get("grade") == "promising"]
    return (
        "\n".join(
            f"- {q['id']}: Sharpe{q.get('sharpe', 0):+.2f} ({q['reason']})"
            for q in promising_items[-10:]
        )
        or "없음"
    )
