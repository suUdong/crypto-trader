from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal, TypedDict

DEFAULT_ERROR_PATTERNS = [
    "Credit balance is too low",
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "ImportError",
    "ConnectionError",
    "TimeoutError",
    "Error:",
]
DEFAULT_MIN_MEANINGFUL_TRADES = 30
DEFAULT_MIN_PROMISING_SHARPE = 3.0
DEFAULT_MIN_MARGINAL_SHARPE = 0.5

_SHARPE_RE = re.compile(r"[Ss]harpe[:\s=]+([+-]?\d+\.?\d*)")
_WR_RE = re.compile(r"(?:WR|win_rate|wr)[=:\s]+(\d+\.?\d*)%?")
_TRADES_RE = re.compile(r"(?:trades|n)[=:\s]+(\d+)")
_AVG_RE = re.compile(r"(?:avg|mean)[%=:\s]+([+-]?\d+\.?\d*)%?")
_EDGE_RE = re.compile(r"[Ee]dge[:\s=]+([+-]?\d+\.?\d*)%?")


class ResearchResult(TypedDict):
    best_sharpe: float | None
    best_wr: float | None
    total_trades: int | None
    avg_pct: float | None
    raw_tail: str


class QualityVerdict(TypedDict):
    grade: Literal["promising", "marginal", "poor", "error", "ok"]
    reason: str


def parse_research_result(output: str) -> ResearchResult:
    sharpes = [float(match) for match in _SHARPE_RE.findall(output)]
    wrs = [float(match) for match in _WR_RE.findall(output)]
    trades = [int(match) for match in _TRADES_RE.findall(output)]
    avgs = [float(match) for match in _AVG_RE.findall(output)]
    edges = [float(match) for match in _EDGE_RE.findall(output)]

    best_sharpe = max(sharpes) if sharpes else (max(edges) if edges else None)
    return {
        "best_sharpe": best_sharpe,
        "best_wr": max(wrs) if wrs else None,
        "total_trades": max(trades) if trades else None,
        "avg_pct": max(avgs) if avgs else None,
        "raw_tail": output[-2000:],
    }


def quality_check_backtest(
    result: ResearchResult,
    *,
    error_patterns: list[str] | None = None,
    min_meaningful_trades: int = DEFAULT_MIN_MEANINGFUL_TRADES,
    min_promising_sharpe: float = DEFAULT_MIN_PROMISING_SHARPE,
    min_marginal_sharpe: float = DEFAULT_MIN_MARGINAL_SHARPE,
) -> QualityVerdict:
    raw = result["raw_tail"]
    patterns = error_patterns or DEFAULT_ERROR_PATTERNS
    for pattern in patterns:
        if pattern in raw:
            return {"grade": "error", "reason": f"에러 감지: {pattern[:40]}"}

    sharpe = result["best_sharpe"]
    trades = result["total_trades"]
    if sharpe is None:
        return {"grade": "poor", "reason": "Sharpe 없음 — 스크립트 실패 또는 거래 없음"}
    if trades is not None and trades < min_meaningful_trades:
        return {
            "grade": "poor",
            "reason": f"거래 수 부족: {trades} < {min_meaningful_trades}",
        }
    if sharpe >= min_promising_sharpe:
        return {"grade": "promising", "reason": f"Sharpe {sharpe:+.3f} — 유의미한 엣지 확인"}
    if sharpe >= min_marginal_sharpe:
        return {"grade": "marginal", "reason": f"Sharpe {sharpe:+.3f} — 추가 검증 필요"}
    return {"grade": "poor", "reason": f"Sharpe {sharpe:+.3f} — 엣지 부족"}


def quality_check_hypothesis(
    text: str,
    *,
    error_patterns: list[str] | None = None,
) -> QualityVerdict:
    patterns = error_patterns or DEFAULT_ERROR_PATTERNS
    for pattern in patterns:
        if pattern in text:
            return {"grade": "error", "reason": f"에러 응답: {pattern[:40]}"}
    if len(text.strip()) < 50:
        return {"grade": "error", "reason": "응답 너무 짧음 (API 오류 의심)"}
    return {"grade": "ok", "reason": "정상 응답"}


def grade_emoji(grade: str) -> str:
    return {
        "promising": "🌟",
        "marginal": "🔶",
        "poor": "🔻",
        "error": "❌",
        "ok": "✅",
    }.get(grade, "")


def format_history_entry(
    task: dict[str, str],
    result: ResearchResult,
    *,
    note: str = "",
    grade: str = "",
    now: datetime | None = None,
) -> str:
    timestamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    sharpe_str = (
        f"{result['best_sharpe']:+.3f}"
        if result["best_sharpe"] is not None
        else "N/A"
    )
    wr_str = f"{result['best_wr']:.1f}%" if result["best_wr"] is not None else "N/A"
    trades_str = str(result["total_trades"]) if result["total_trades"] else "N/A"
    grade_str = f" {grade_emoji(grade)}[{grade}]" if grade else ""
    note_line = f"**메모**: {note}" if note else ""
    return f"""
## {timestamp} — {task['desc']} [ralph:{task['id']}]{grade_str}

**결과**: Sharpe {sharpe_str} | WR {wr_str} | trades {trades_str}
{note_line}

<details><summary>raw output</summary>

```
{result['raw_tail']}
```

</details>

---
"""
