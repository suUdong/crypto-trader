# Strategy Evaluator v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM-judged evaluator with a plugin-based quantitative evaluation pipeline that uses code for grading and Opus only for human-readable formatting.

**Architecture:** A `src/crypto_trader/evaluator/` package with an engine that auto-discovers `BaseCheck` plugins from `checks/`. Each check returns a `CheckResult` with a deterministic grade. The engine aggregates results into an `EvaluationReport`. An optional Opus formatter converts the report to Telegram/human summaries. Entry point script handles trigger logic (file mtime polling + min interval).

**Tech Stack:** Python 3.12, dataclasses, StrEnum, pkgutil, subprocess (claude CLI for Opus), pytest, mypy strict, ruff

**Spec:** `docs/superpowers/specs/2026-04-13-evaluator-v2-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/crypto_trader/evaluator/__init__.py` | Package marker |
| Create | `src/crypto_trader/evaluator/models.py` | Grade, CheckResult, EvalContext, EvaluationReport |
| Create | `src/crypto_trader/evaluator/engine.py` | discover_checks, run pipeline, aggregate |
| Create | `src/crypto_trader/evaluator/formatter.py` | Opus call + fallback template formatting |
| Create | `src/crypto_trader/evaluator/checks/__init__.py` | Package marker |
| Create | `src/crypto_trader/evaluator/checks/base.py` | BaseCheck ABC |
| Create | `src/crypto_trader/evaluator/checks/backtest_quality.py` | Backtest n/Sharpe/OOS checks |
| Create | `src/crypto_trader/evaluator/checks/strategy_health.py` | Daemon strategy health checks |
| Create | `src/crypto_trader/evaluator/checks/portfolio_risk.py` | Concentration + regime coverage |
| Create | `src/crypto_trader/evaluator/checks/research_progress.py` | Research loop progress checks |
| Create | `scripts/strategy_evaluator_v2.py` | Entry point script (loop + trigger) |
| Create | `tests/test_evaluator_models.py` | Model unit tests |
| Create | `tests/test_evaluator_engine.py` | Engine + discovery tests |
| Create | `tests/test_evaluator_checks.py` | All 4 check unit tests |
| Create | `tests/test_evaluator_formatter.py` | Formatter tests |
| Modify | `scripts/strategy_evaluator_loop.py:1-3` | Add deprecated notice |

---

### Task 1: Models — Grade, CheckResult, EvalContext, EvaluationReport

**Files:**
- Create: `src/crypto_trader/evaluator/__init__.py`
- Create: `src/crypto_trader/evaluator/models.py`
- Create: `tests/test_evaluator_models.py`

- [ ] **Step 1: Create package structure**

```bash
mkdir -p src/crypto_trader/evaluator/checks
```

- [ ] **Step 2: Write failing tests for models**

Create `tests/test_evaluator_models.py`:

```python
"""Tests for evaluator data models."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.models import (
    CheckResult,
    EvalContext,
    EvaluationReport,
    Grade,
)


class TestGrade(unittest.TestCase):
    def test_grade_values(self) -> None:
        self.assertEqual(Grade.PASS, "pass")
        self.assertEqual(Grade.WARN, "warn")
        self.assertEqual(Grade.FAIL, "fail")
        self.assertEqual(Grade.SKIP, "skip")

    def test_grade_ordering(self) -> None:
        # FAIL is worst, PASS is best
        grades = [Grade.PASS, Grade.FAIL, Grade.WARN, Grade.SKIP]
        worst = Grade.worst(grades)
        self.assertEqual(worst, Grade.FAIL)

    def test_grade_worst_skip_only(self) -> None:
        self.assertEqual(Grade.worst([Grade.SKIP]), Grade.SKIP)

    def test_grade_worst_empty(self) -> None:
        self.assertEqual(Grade.worst([]), Grade.SKIP)


class TestCheckResult(unittest.TestCase):
    def test_create(self) -> None:
        result = CheckResult(
            check_name="test_check",
            grade=Grade.PASS,
            score=0.85,
            findings=["all good"],
            metrics={"sharpe": 7.5},
            suggestions=[],
        )
        self.assertEqual(result.check_name, "test_check")
        self.assertEqual(result.grade, Grade.PASS)
        self.assertAlmostEqual(result.score, 0.85)

    def test_to_dict(self) -> None:
        result = CheckResult(
            check_name="test_check",
            grade=Grade.WARN,
            score=0.5,
            findings=["needs attention"],
            metrics={"n_trades": 20},
            suggestions=["increase sample size"],
        )
        d = result.to_dict()
        self.assertEqual(d["check_name"], "test_check")
        self.assertEqual(d["grade"], "warn")
        self.assertIsInstance(d["metrics"], dict)


class TestEvalContext(unittest.TestCase):
    def test_create_minimal(self) -> None:
        ctx = EvalContext(
            backtest_history_tail="",
            daemon_strategies=[],
            daemon_config_path=None,
            research_state=None,
            market_scan_state=None,
            checkpoint=None,
            journal_trades=[],
            prev_report=None,
        )
        self.assertEqual(ctx.daemon_strategies, [])
        self.assertIsNone(ctx.checkpoint)


class TestEvaluationReport(unittest.TestCase):
    def test_create(self) -> None:
        cr = CheckResult(
            check_name="test",
            grade=Grade.PASS,
            score=0.9,
            findings=[],
            metrics={},
            suggestions=[],
        )
        report = EvaluationReport(
            eval_id="eval-test",
            timestamp="2026-04-13T00:00:00+00:00",
            overall_grade=Grade.PASS,
            overall_score=0.9,
            check_results=[cr],
            data_sources_used=["backtest_history.md"],
            trigger_reason="manual",
        )
        self.assertEqual(report.eval_id, "eval-test")
        self.assertEqual(len(report.check_results), 1)

    def test_to_dict(self) -> None:
        cr = CheckResult(
            check_name="test",
            grade=Grade.WARN,
            score=0.5,
            findings=["f1"],
            metrics={"k": 1},
            suggestions=[],
        )
        report = EvaluationReport(
            eval_id="eval-abc",
            timestamp="2026-04-13T00:00:00+00:00",
            overall_grade=Grade.WARN,
            overall_score=0.5,
            check_results=[cr],
            data_sources_used=["test"],
            trigger_reason="scheduled",
        )
        d = report.to_dict()
        self.assertEqual(d["schema_version"], 2)
        self.assertEqual(d["overall_grade"], "warn")
        self.assertIsInstance(d["check_results"], list)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'crypto_trader.evaluator'`

- [ ] **Step 4: Implement models**

Create `src/crypto_trader/evaluator/__init__.py`:

```python
```

Create `src/crypto_trader/evaluator/models.py`:

```python
"""Data models for the strategy evaluator v2 pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Grade(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

    @staticmethod
    def worst(grades: list[Grade]) -> Grade:
        """Return the worst grade from a list. FAIL > WARN > SKIP > PASS."""
        if not grades:
            return Grade.SKIP
        priority = {Grade.FAIL: 3, Grade.WARN: 2, Grade.SKIP: 1, Grade.PASS: 0}
        return max(grades, key=lambda g: priority[g])


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    grade: Grade
    score: float  # 0.0 ~ 1.0
    findings: list[str]
    metrics: dict[str, Any]
    suggestions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "grade": self.grade.value,
            "score": self.score,
            "findings": list(self.findings),
            "metrics": dict(self.metrics),
            "suggestions": list(self.suggestions),
        }


@dataclass
class EvalContext:
    backtest_history_tail: str
    daemon_strategies: list[str]
    daemon_config_path: Path | None
    research_state: dict[str, Any] | None
    market_scan_state: dict[str, Any] | None
    checkpoint: dict[str, Any] | None
    journal_trades: list[dict[str, Any]]
    prev_report: EvaluationReport | None


@dataclass
class EvaluationReport:
    eval_id: str
    timestamp: str
    overall_grade: Grade
    overall_score: float
    check_results: list[CheckResult]
    data_sources_used: list[str]
    trigger_reason: str
    summary_for_human: str = ""
    telegram_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "generated_at": self.timestamp,
            "eval_id": self.eval_id,
            "trigger_reason": self.trigger_reason,
            "overall_grade": self.overall_grade.value,
            "overall_score": self.overall_score,
            "check_results": [cr.to_dict() for cr in self.check_results],
            "data_sources_used": self.data_sources_used,
            "summary_for_human": self.summary_for_human,
            "telegram_summary": self.telegram_summary,
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_models.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Type check**

Run: `cd /home/wdsr88/workspace/crypto-trader && mypy src/crypto_trader/evaluator/models.py --strict`
Expected: Success

- [ ] **Step 7: Commit**

```bash
git add src/crypto_trader/evaluator/__init__.py src/crypto_trader/evaluator/models.py tests/test_evaluator_models.py
git commit -m "feat(evaluator): add v2 data models — Grade, CheckResult, EvalContext, EvaluationReport"
```

---

### Task 2: BaseCheck ABC + check discovery

**Files:**
- Create: `src/crypto_trader/evaluator/checks/__init__.py`
- Create: `src/crypto_trader/evaluator/checks/base.py`
- Create: `src/crypto_trader/evaluator/engine.py`
- Create: `tests/test_evaluator_engine.py`

- [ ] **Step 1: Write failing tests for BaseCheck and engine**

Create `tests/test_evaluator_engine.py`:

```python
"""Tests for evaluator engine: check discovery, pipeline execution, aggregation."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.engine import discover_checks, run_evaluation
from crypto_trader.evaluator.models import (
    CheckResult,
    EvalContext,
    EvaluationReport,
    Grade,
)


class _PassCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "always_pass"

    def run(self, ctx: EvalContext) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            grade=Grade.PASS,
            score=1.0,
            findings=["all good"],
            metrics={},
            suggestions=[],
        )


class _WarnCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "always_warn"

    @property
    def weight(self) -> float:
        return 2.0

    def run(self, ctx: EvalContext) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            grade=Grade.WARN,
            score=0.5,
            findings=["needs attention"],
            metrics={},
            suggestions=[],
        )


class _FailCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "always_fail"

    def run(self, ctx: EvalContext) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            grade=Grade.FAIL,
            score=0.0,
            findings=["critical issue"],
            metrics={},
            suggestions=["fix it"],
        )


class _SkipCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "always_skip"

    def run(self, ctx: EvalContext) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            grade=Grade.SKIP,
            score=0.0,
            findings=["no data"],
            metrics={},
            suggestions=[],
        )


def _make_ctx() -> EvalContext:
    return EvalContext(
        backtest_history_tail="",
        daemon_strategies=[],
        daemon_config_path=None,
        research_state=None,
        market_scan_state=None,
        checkpoint=None,
        journal_trades=[],
        prev_report=None,
    )


class TestDiscoverChecks(unittest.TestCase):
    def test_discovers_at_least_one_check(self) -> None:
        # After all checks are implemented, this should find them
        checks = discover_checks()
        self.assertIsInstance(checks, list)
        for check in checks:
            self.assertIsInstance(check, BaseCheck)


class TestRunEvaluation(unittest.TestCase):
    def test_all_pass(self) -> None:
        report = run_evaluation(
            checks=[_PassCheck()],
            ctx=_make_ctx(),
            trigger_reason="test",
        )
        self.assertIsInstance(report, EvaluationReport)
        self.assertEqual(report.overall_grade, Grade.PASS)
        self.assertAlmostEqual(report.overall_score, 1.0)
        self.assertEqual(len(report.check_results), 1)

    def test_worst_grade_wins(self) -> None:
        report = run_evaluation(
            checks=[_PassCheck(), _WarnCheck(), _FailCheck()],
            ctx=_make_ctx(),
            trigger_reason="test",
        )
        self.assertEqual(report.overall_grade, Grade.FAIL)

    def test_weighted_score(self) -> None:
        # _PassCheck weight=1.0 score=1.0, _WarnCheck weight=2.0 score=0.5
        # weighted avg = (1.0*1.0 + 2.0*0.5) / (1.0 + 2.0) = 2.0/3.0 ≈ 0.667
        report = run_evaluation(
            checks=[_PassCheck(), _WarnCheck()],
            ctx=_make_ctx(),
            trigger_reason="test",
        )
        self.assertAlmostEqual(report.overall_score, 2.0 / 3.0, places=3)

    def test_skip_excluded_from_score(self) -> None:
        # SKIP checks should not contribute to score
        report = run_evaluation(
            checks=[_PassCheck(), _SkipCheck()],
            ctx=_make_ctx(),
            trigger_reason="test",
        )
        self.assertAlmostEqual(report.overall_score, 1.0)

    def test_empty_checks(self) -> None:
        report = run_evaluation(checks=[], ctx=_make_ctx(), trigger_reason="test")
        self.assertEqual(report.overall_grade, Grade.SKIP)
        self.assertAlmostEqual(report.overall_score, 0.0)

    def test_report_has_eval_id_and_timestamp(self) -> None:
        report = run_evaluation(
            checks=[_PassCheck()],
            ctx=_make_ctx(),
            trigger_reason="manual",
        )
        self.assertTrue(report.eval_id.startswith("eval-"))
        self.assertIn("T", report.timestamp)
        self.assertEqual(report.trigger_reason, "manual")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement BaseCheck ABC**

Create `src/crypto_trader/evaluator/checks/__init__.py`:

```python
```

Create `src/crypto_trader/evaluator/checks/base.py`:

```python
"""Base class for all evaluator check plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod

from crypto_trader.evaluator.models import CheckResult, EvalContext


class BaseCheck(ABC):
    """All check plugins must inherit from this class."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique check identifier, e.g. 'backtest_quality'."""

    @property
    def weight(self) -> float:
        """Weight for overall_score calculation. Default 1.0."""
        return 1.0

    @abstractmethod
    def run(self, ctx: EvalContext) -> CheckResult:
        """Execute the check. Return Grade.SKIP if data is insufficient."""
```

- [ ] **Step 4: Implement engine**

Create `src/crypto_trader/evaluator/engine.py`:

```python
"""Evaluator v2 pipeline engine: discover checks, run, aggregate."""

from __future__ import annotations

import importlib
import pkgutil
import uuid
from datetime import UTC, datetime

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import (
    EvalContext,
    EvaluationReport,
    Grade,
)


def discover_checks() -> list[BaseCheck]:
    """Auto-discover BaseCheck subclasses in the checks package."""
    from crypto_trader.evaluator import checks as checks_pkg

    found: list[BaseCheck] = []
    for info in pkgutil.iter_modules(checks_pkg.__path__):
        if info.name == "base":
            continue
        mod = importlib.import_module(f"crypto_trader.evaluator.checks.{info.name}")
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseCheck)
                and attr is not BaseCheck
            ):
                found.append(attr())
    return found


def run_evaluation(
    *,
    checks: list[BaseCheck],
    ctx: EvalContext,
    trigger_reason: str,
) -> EvaluationReport:
    """Run all checks and aggregate into an EvaluationReport."""
    results = [check.run(ctx) for check in checks]

    if not results:
        return EvaluationReport(
            eval_id=f"eval-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(UTC).isoformat(),
            overall_grade=Grade.SKIP,
            overall_score=0.0,
            check_results=[],
            data_sources_used=[],
            trigger_reason=trigger_reason,
        )

    overall_grade = Grade.worst([r.grade for r in results])

    # Weighted average score, excluding SKIP
    scored = [(r, c.weight) for r, c in zip(results, checks) if r.grade != Grade.SKIP]
    if scored:
        total_weight = sum(w for _, w in scored)
        overall_score = sum(r.score * w for r, w in scored) / total_weight
    else:
        overall_score = 0.0

    data_sources: list[str] = []
    for r in results:
        for key in r.metrics:
            if key not in data_sources:
                data_sources.append(key)

    return EvaluationReport(
        eval_id=f"eval-{uuid.uuid4().hex[:8]}",
        timestamp=datetime.now(UTC).isoformat(),
        overall_grade=overall_grade,
        overall_score=round(overall_score, 4),
        check_results=results,
        data_sources_used=data_sources,
        trigger_reason=trigger_reason,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_engine.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Type check**

Run: `cd /home/wdsr88/workspace/crypto-trader && mypy src/crypto_trader/evaluator/engine.py src/crypto_trader/evaluator/checks/base.py --strict`
Expected: Success

- [ ] **Step 7: Commit**

```bash
git add src/crypto_trader/evaluator/checks/__init__.py src/crypto_trader/evaluator/checks/base.py src/crypto_trader/evaluator/engine.py tests/test_evaluator_engine.py
git commit -m "feat(evaluator): add BaseCheck ABC + engine with auto-discovery and weighted aggregation"
```

---

### Task 3: backtest_quality check

**Files:**
- Create: `src/crypto_trader/evaluator/checks/backtest_quality.py`
- Create: `tests/test_evaluator_checks.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_evaluator_checks.py`:

```python
"""Tests for evaluator check plugins."""

from __future__ import annotations

import unittest

from crypto_trader.evaluator.checks.backtest_quality import BacktestQualityCheck
from crypto_trader.evaluator.models import EvalContext, Grade


def _make_ctx(history_tail: str = "") -> EvalContext:
    return EvalContext(
        backtest_history_tail=history_tail,
        daemon_strategies=[],
        daemon_config_path=None,
        research_state=None,
        market_scan_state=None,
        checkpoint=None,
        journal_trades=[],
        prev_report=None,
    )


class TestBacktestQualityCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.check = BacktestQualityCheck()

    def test_name(self) -> None:
        self.assertEqual(self.check.name, "backtest_quality")

    def test_skip_when_no_data(self) -> None:
        result = self.check.run(_make_ctx(""))
        self.assertEqual(result.grade, Grade.SKIP)

    def test_pass_sufficient_trades_and_sharpe(self) -> None:
        # n=86, Sharpe=+7.15 → statistically significant, PASS
        lines = [
            "| 2026-04-10 | c250 | bb_squeeze | n=86 | WR=55% | Sharpe=+7.15 | OOS효율=0.65 | 유효 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertEqual(result.grade, Grade.PASS)
        self.assertGreater(result.score, 0.7)

    def test_warn_low_n_trades(self) -> None:
        # n=20 → below 30, WARN
        lines = [
            "| 2026-04-10 | c251 | momentum | n=20 | WR=60% | Sharpe=+5.0 | OOS효율=0.50 | 통계부족 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertIn(result.grade, (Grade.WARN, Grade.FAIL))

    def test_fail_very_low_n_trades(self) -> None:
        # n=5 → below 10, FAIL
        lines = [
            "| 2026-04-10 | c252 | vpin | n=5 | WR=80% | Sharpe=+20.0 | OOS효율=0.40 | 부족 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertEqual(result.grade, Grade.FAIL)

    def test_warn_low_oos_efficiency(self) -> None:
        # OOS효율=0.20 → below 0.3, should flag
        lines = [
            "| 2026-04-10 | c253 | stealth | n=50 | WR=45% | Sharpe=+3.0 | OOS효율=0.20 | 낮음 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        self.assertIn(result.grade, (Grade.WARN, Grade.FAIL))

    def test_multiple_entries_uses_worst(self) -> None:
        lines = [
            "| 2026-04-10 | c250 | bb_squeeze | n=86 | WR=55% | Sharpe=+7.15 | OOS효율=0.65 | 유효 |",
            "| 2026-04-10 | c251 | momentum | n=5 | WR=60% | Sharpe=+5.0 | OOS효율=0.50 | 부족 |",
        ]
        result = self.check.run(_make_ctx("\n".join(lines)))
        # At least one entry has n=5 → overall should be WARN or FAIL
        self.assertNotEqual(result.grade, Grade.PASS)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_checks.py::TestBacktestQualityCheck -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement backtest_quality check**

Create `src/crypto_trader/evaluator/checks/backtest_quality.py`:

```python
"""Backtest quality check: n_trades, Sharpe significance, OOS efficiency."""

from __future__ import annotations

import math
import re
from typing import Any

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import CheckResult, EvalContext, Grade

# Thresholds
MIN_TRADES_FAIL = 10
MIN_TRADES_WARN = 30
MIN_OOS_EFFICIENCY = 0.3
MIN_SHARPE_SIGNIFICANCE = 0.5  # Sharpe / sqrt(n)


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

            # n_trades check
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

            # Sharpe significance: Sharpe / sqrt(n) threshold
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

            # OOS efficiency
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
            findings.append(
                f"최근 백테스트 {len(entries)}건 — 품질 기준 충족"
            )

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_checks.py::TestBacktestQualityCheck -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Type check + lint**

Run: `cd /home/wdsr88/workspace/crypto-trader && mypy src/crypto_trader/evaluator/checks/backtest_quality.py --strict && ruff check src/crypto_trader/evaluator/`
Expected: Success

- [ ] **Step 6: Commit**

```bash
git add src/crypto_trader/evaluator/checks/backtest_quality.py tests/test_evaluator_checks.py
git commit -m "feat(evaluator): add backtest_quality check — n_trades, Sharpe significance, OOS efficiency"
```

---

### Task 4: strategy_health check

**Files:**
- Create: `src/crypto_trader/evaluator/checks/strategy_health.py`
- Modify: `tests/test_evaluator_checks.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_evaluator_checks.py`:

```python
from crypto_trader.evaluator.checks.strategy_health import StrategyHealthCheck


class TestStrategyHealthCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.check = StrategyHealthCheck()

    def test_name(self) -> None:
        self.assertEqual(self.check.name, "strategy_health")

    def test_skip_when_no_checkpoint(self) -> None:
        ctx = _make_ctx()
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.SKIP)

    def test_pass_healthy_wallets(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {
                    "equity": 1_100_000,
                    "initial_capital": 1_000_000,
                    "realized_pnl": 100_000,
                    "trade_count": 15,
                    "strategy_type": "vpin",
                },
            },
        }
        ctx.daemon_strategies = ["vpin"]
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.PASS)

    def test_warn_high_drawdown(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {
                    "equity": 850_000,
                    "initial_capital": 1_000_000,
                    "realized_pnl": -150_000,
                    "trade_count": 20,
                    "strategy_type": "momentum",
                },
            },
        }
        ctx.daemon_strategies = ["momentum"]
        result = self.check.run(ctx)
        # 15% drawdown → WARN
        self.assertIn(result.grade, (Grade.WARN, Grade.FAIL))

    def test_fail_extreme_drawdown(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {
                    "equity": 700_000,
                    "initial_capital": 1_000_000,
                    "realized_pnl": -300_000,
                    "trade_count": 30,
                    "strategy_type": "stealth",
                },
            },
        }
        ctx.daemon_strategies = ["stealth"]
        result = self.check.run(ctx)
        # 30% drawdown → FAIL
        self.assertEqual(result.grade, Grade.FAIL)

    def test_warn_idle_strategy(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {
                    "equity": 1_000_000,
                    "initial_capital": 1_000_000,
                    "realized_pnl": 0,
                    "trade_count": 0,
                    "strategy_type": "vpin",
                },
            },
        }
        ctx.daemon_strategies = ["vpin"]
        result = self.check.run(ctx)
        # 0 trades → idle → WARN
        self.assertEqual(result.grade, Grade.WARN)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_checks.py::TestStrategyHealthCheck -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement strategy_health check**

Create `src/crypto_trader/evaluator/checks/strategy_health.py`:

```python
"""Strategy health check: per-wallet drawdown, idle detection."""

from __future__ import annotations

from typing import Any

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import CheckResult, EvalContext, Grade

MDD_WARN = 0.10
MDD_FAIL = 0.20
MIN_TRADES_FOR_ACTIVE = 1


class StrategyHealthCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "strategy_health"

    def run(self, ctx: EvalContext) -> CheckResult:
        if not ctx.checkpoint:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["runtime-checkpoint 없음"],
                metrics={},
                suggestions=["daemon 실행 후 체크포인트 생성 필요"],
            )

        wallet_states: dict[str, Any] = ctx.checkpoint.get("wallet_states", {})
        if not wallet_states:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["체크포인트에 wallet_states 없음"],
                metrics={},
                suggestions=[],
            )

        findings: list[str] = []
        suggestions: list[str] = []
        worst_grade = Grade.PASS
        scores: list[float] = []

        for wallet_name, ws in wallet_states.items():
            initial = float(ws.get("initial_capital") or ws.get("equity", 1_000_000))
            equity = float(ws.get("equity", initial))
            trades = int(ws.get("trade_count", 0))
            strategy = ws.get("strategy_type", "unknown")

            # Drawdown
            if initial > 0:
                drawdown = max(0.0, (initial - equity) / initial)
            else:
                drawdown = 0.0

            if drawdown >= MDD_FAIL:
                worst_grade = Grade.worst([worst_grade, Grade.FAIL])
                findings.append(
                    f"{wallet_name}({strategy}): MDD {drawdown:.1%} >= {MDD_FAIL:.0%}"
                )
                suggestions.append(f"{wallet_name}: 전략 중단 또는 파라미터 재검토")
                scores.append(0.0)
            elif drawdown >= MDD_WARN:
                worst_grade = Grade.worst([worst_grade, Grade.WARN])
                findings.append(
                    f"{wallet_name}({strategy}): MDD {drawdown:.1%} >= {MDD_WARN:.0%}"
                )
                scores.append(0.3)
            else:
                scores.append(1.0 - drawdown)

            # Idle detection
            if trades < MIN_TRADES_FOR_ACTIVE:
                worst_grade = Grade.worst([worst_grade, Grade.WARN])
                findings.append(
                    f"{wallet_name}({strategy}): 거래 {trades}건 — 유휴 상태"
                )
                suggestions.append(f"{wallet_name}: 시그널 생성 조건 점검 또는 자본 재배분")
                scores.append(0.2)

        if not findings:
            findings.append(f"활성 지갑 {len(wallet_states)}개 — 건강 상태 양호")

        avg_score = sum(scores) / len(scores) if scores else 0.0

        metrics: dict[str, Any] = {
            "wallet_count": len(wallet_states),
            "active_strategies": list({
                ws.get("strategy_type", "unknown") for ws in wallet_states.values()
            }),
        }

        return CheckResult(
            check_name=self.name,
            grade=worst_grade,
            score=round(min(avg_score, 1.0), 4),
            findings=findings,
            metrics=metrics,
            suggestions=suggestions,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_checks.py::TestStrategyHealthCheck -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Type check + lint**

Run: `cd /home/wdsr88/workspace/crypto-trader && mypy src/crypto_trader/evaluator/checks/strategy_health.py --strict && ruff check src/crypto_trader/evaluator/`
Expected: Success

- [ ] **Step 6: Commit**

```bash
git add src/crypto_trader/evaluator/checks/strategy_health.py tests/test_evaluator_checks.py
git commit -m "feat(evaluator): add strategy_health check — drawdown, idle detection"
```

---

### Task 5: portfolio_risk check

**Files:**
- Create: `src/crypto_trader/evaluator/checks/portfolio_risk.py`
- Modify: `tests/test_evaluator_checks.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_evaluator_checks.py`:

```python
from crypto_trader.evaluator.checks.portfolio_risk import PortfolioRiskCheck


class TestPortfolioRiskCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.check = PortfolioRiskCheck()

    def test_name(self) -> None:
        self.assertEqual(self.check.name, "portfolio_risk")

    def test_skip_when_no_checkpoint(self) -> None:
        result = self.check.run(_make_ctx())
        self.assertEqual(result.grade, Grade.SKIP)

    def test_pass_diversified(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {"equity": 300_000, "strategy_type": "vpin"},
                "w2": {"equity": 300_000, "strategy_type": "momentum"},
                "w3": {"equity": 400_000, "strategy_type": "stealth_3gate"},
            },
        }
        ctx.daemon_strategies = ["vpin", "momentum", "stealth_3gate"]
        result = self.check.run(ctx)
        self.assertEqual(result.grade, Grade.PASS)

    def test_warn_concentrated(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {"equity": 900_000, "strategy_type": "vpin"},
                "w2": {"equity": 100_000, "strategy_type": "momentum"},
            },
        }
        ctx.daemon_strategies = ["vpin", "momentum"]
        result = self.check.run(ctx)
        # 90% in one strategy → WARN
        self.assertEqual(result.grade, Grade.WARN)

    def test_warn_single_strategy(self) -> None:
        ctx = _make_ctx()
        ctx.checkpoint = {
            "wallet_states": {
                "w1": {"equity": 1_000_000, "strategy_type": "vpin"},
            },
        }
        ctx.daemon_strategies = ["vpin"]
        result = self.check.run(ctx)
        # Only 1 active strategy → WARN (low regime coverage)
        self.assertEqual(result.grade, Grade.WARN)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_checks.py::TestPortfolioRiskCheck -v`
Expected: FAIL

- [ ] **Step 3: Implement portfolio_risk check**

Create `src/crypto_trader/evaluator/checks/portfolio_risk.py`:

```python
"""Portfolio risk check: concentration, regime coverage."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import CheckResult, EvalContext, Grade

MAX_SINGLE_STRATEGY_PCT = 0.40
MIN_ACTIVE_STRATEGIES = 2


class PortfolioRiskCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "portfolio_risk"

    def run(self, ctx: EvalContext) -> CheckResult:
        if not ctx.checkpoint:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["runtime-checkpoint 없음"],
                metrics={},
                suggestions=[],
            )

        wallet_states: dict[str, Any] = ctx.checkpoint.get("wallet_states", {})
        if not wallet_states:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["wallet_states 없음"],
                metrics={},
                suggestions=[],
            )

        findings: list[str] = []
        suggestions: list[str] = []
        worst_grade = Grade.PASS
        scores: list[float] = []

        # Strategy concentration
        strategy_equity: dict[str, float] = defaultdict(float)
        total_equity = 0.0
        for ws in wallet_states.values():
            equity = float(ws.get("equity", 0.0))
            strategy = ws.get("strategy_type", "unknown")
            strategy_equity[strategy] += equity
            total_equity += equity

        if total_equity > 0:
            for strategy, equity in strategy_equity.items():
                pct = equity / total_equity
                if pct > MAX_SINGLE_STRATEGY_PCT:
                    worst_grade = Grade.worst([worst_grade, Grade.WARN])
                    findings.append(
                        f"{strategy}: 자본 비중 {pct:.0%} > {MAX_SINGLE_STRATEGY_PCT:.0%}"
                    )
                    suggestions.append(f"{strategy} 비중 축소 또는 타 전략 자본 확대")
                    scores.append(0.4)
                else:
                    scores.append(1.0)

        # Regime coverage: need at least MIN_ACTIVE_STRATEGIES unique strategies
        unique_strategies = len(strategy_equity)
        if unique_strategies < MIN_ACTIVE_STRATEGIES:
            worst_grade = Grade.worst([worst_grade, Grade.WARN])
            findings.append(
                f"활성 전략 {unique_strategies}개 < {MIN_ACTIVE_STRATEGIES}개"
                " — 레짐 커버리지 부족"
            )
            suggestions.append("다양한 레짐에서 작동하는 전략 추가 필요")
            scores.append(0.3)
        else:
            scores.append(1.0)

        if not findings:
            findings.append(
                f"포트폴리오 {unique_strategies}개 전략 — 집중도 양호"
            )

        avg_score = sum(scores) / len(scores) if scores else 0.0

        metrics: dict[str, Any] = {
            "unique_strategies": unique_strategies,
            "total_equity": total_equity,
            "concentration": {
                s: round(e / total_equity, 3) if total_equity > 0 else 0.0
                for s, e in strategy_equity.items()
            },
        }

        return CheckResult(
            check_name=self.name,
            grade=worst_grade,
            score=round(min(avg_score, 1.0), 4),
            findings=findings,
            metrics=metrics,
            suggestions=suggestions,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_checks.py::TestPortfolioRiskCheck -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/crypto_trader/evaluator/checks/portfolio_risk.py tests/test_evaluator_checks.py
git commit -m "feat(evaluator): add portfolio_risk check — concentration, regime coverage"
```

---

### Task 6: research_progress check

**Files:**
- Create: `src/crypto_trader/evaluator/checks/research_progress.py`
- Modify: `tests/test_evaluator_checks.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_evaluator_checks.py`:

```python
from crypto_trader.evaluator.checks.research_progress import ResearchProgressCheck


class TestResearchProgressCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.check = ResearchProgressCheck()

    def test_name(self) -> None:
        self.assertEqual(self.check.name, "research_progress")

    def test_skip_when_no_state(self) -> None:
        result = self.check.run(_make_ctx())
        self.assertEqual(result.grade, Grade.SKIP)

    def test_pass_with_active_research(self) -> None:
        ctx = _make_ctx()
        ctx.research_state = {
            "cycle": 366,
            "done": [
                "c250_test",
                "c251_test",
                "c252_test",
            ],
        }
        result = self.check.run(ctx)
        self.assertIn(result.grade, (Grade.PASS, Grade.WARN))
        self.assertIn("entries_completed", result.metrics)

    def test_pass_with_market_scan(self) -> None:
        ctx = _make_ctx()
        ctx.research_state = {"cycle": 10, "done": ["a"]}
        ctx.market_scan_state = {"current_cycle": 233}
        result = self.check.run(ctx)
        self.assertIn("market_scan_cycle", result.metrics)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_checks.py::TestResearchProgressCheck -v`
Expected: FAIL

- [ ] **Step 3: Implement research_progress check**

Create `src/crypto_trader/evaluator/checks/research_progress.py`:

```python
"""Research progress check: research loop and market scan activity."""

from __future__ import annotations

from typing import Any

from crypto_trader.evaluator.checks.base import BaseCheck
from crypto_trader.evaluator.models import CheckResult, EvalContext, Grade


class ResearchProgressCheck(BaseCheck):
    @property
    def name(self) -> str:
        return "research_progress"

    @property
    def weight(self) -> float:
        return 0.5  # informational, lower weight

    def run(self, ctx: EvalContext) -> CheckResult:
        if not ctx.research_state and not ctx.market_scan_state:
            return CheckResult(
                check_name=self.name,
                grade=Grade.SKIP,
                score=0.0,
                findings=["research_state 및 market_scan_state 없음"],
                metrics={},
                suggestions=[],
            )

        findings: list[str] = []
        metrics: dict[str, Any] = {}
        grade = Grade.PASS
        scores: list[float] = []

        # Research loop
        if ctx.research_state:
            cycle = ctx.research_state.get("cycle", 0)
            done = ctx.research_state.get("done", [])
            metrics["research_cycle"] = cycle
            metrics["entries_completed"] = len(done)
            if done:
                findings.append(f"research 사이클 {cycle}, 완료 항목 {len(done)}개")
                scores.append(0.8)
            else:
                findings.append(f"research 사이클 {cycle} — 완료 항목 없음")
                scores.append(0.3)

        # Market scan
        if ctx.market_scan_state:
            scan_cycle = ctx.market_scan_state.get("current_cycle", 0)
            metrics["market_scan_cycle"] = scan_cycle
            findings.append(f"market scan 사이클 {scan_cycle}")
            scores.append(0.8)

        avg_score = sum(scores) / len(scores) if scores else 0.0

        return CheckResult(
            check_name=self.name,
            grade=grade,
            score=round(min(avg_score, 1.0), 4),
            findings=findings,
            metrics=metrics,
            suggestions=[],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_checks.py::TestResearchProgressCheck -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/crypto_trader/evaluator/checks/research_progress.py tests/test_evaluator_checks.py
git commit -m "feat(evaluator): add research_progress check — research loop and market scan activity"
```

---

### Task 7: Formatter — Opus call + fallback

**Files:**
- Create: `src/crypto_trader/evaluator/formatter.py`
- Create: `tests/test_evaluator_formatter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_evaluator_formatter.py`:

```python
"""Tests for evaluator formatter (Opus + fallback)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from crypto_trader.evaluator.formatter import fallback_format, format_report
from crypto_trader.evaluator.models import CheckResult, EvaluationReport, Grade


def _make_report() -> EvaluationReport:
    return EvaluationReport(
        eval_id="eval-test123",
        timestamp="2026-04-13T12:00:00+00:00",
        overall_grade=Grade.WARN,
        overall_score=0.65,
        check_results=[
            CheckResult(
                check_name="backtest_quality",
                grade=Grade.PASS,
                score=0.82,
                findings=["n=86, Sharpe 유의"],
                metrics={"avg_n_trades": 86},
                suggestions=[],
            ),
            CheckResult(
                check_name="strategy_health",
                grade=Grade.WARN,
                score=0.5,
                findings=["w1(momentum): MDD 12%"],
                metrics={},
                suggestions=["파라미터 재검토"],
            ),
        ],
        data_sources_used=["backtest_history.md", "checkpoint"],
        trigger_reason="file_change:strategy_research.state.json",
    )


class TestFallbackFormat(unittest.TestCase):
    def test_contains_eval_id(self) -> None:
        report = _make_report()
        text = fallback_format(report)
        self.assertIn("eval-test123", text)

    def test_contains_grade(self) -> None:
        report = _make_report()
        text = fallback_format(report)
        self.assertIn("warn", text)

    def test_contains_check_names(self) -> None:
        report = _make_report()
        text = fallback_format(report)
        self.assertIn("backtest_quality", text)
        self.assertIn("strategy_health", text)


class TestFormatReport(unittest.TestCase):
    @patch("crypto_trader.evaluator.formatter._call_opus")
    def test_uses_opus_when_available(self, mock_opus: unittest.mock.MagicMock) -> None:
        mock_opus.return_value = (
            '```json\n{"telegram_summary": "test summary", '
            '"detailed_summary": "detailed"}\n```'
        )
        report = _make_report()
        result = format_report(report)
        self.assertEqual(result.telegram_summary, "test summary")
        mock_opus.assert_called_once()

    @patch("crypto_trader.evaluator.formatter._call_opus")
    def test_falls_back_on_opus_failure(
        self, mock_opus: unittest.mock.MagicMock
    ) -> None:
        mock_opus.return_value = None
        report = _make_report()
        result = format_report(report)
        # Should still have a telegram_summary from fallback
        self.assertIn("eval-test123", result.telegram_summary)

    def test_format_report_dry_run(self) -> None:
        report = _make_report()
        result = format_report(report, dry_run=True)
        # dry_run skips Opus, uses fallback
        self.assertIn("eval-test123", result.telegram_summary)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_formatter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement formatter**

Create `src/crypto_trader/evaluator/formatter.py`:

```python
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
- 반드시 아래 JSON을 마크다운 코드블록(```json ... ```)으로 출력하세요:

```json
{{
  "telegram_summary": "5-8줄, 이모지 포함, 한국어 요약",
  "detailed_summary": "섹션별 분석, 마크다운 포맷"
}}
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

    Returns a new report with summary fields populated.
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

    # Fallback
    fb = fallback_format(report)
    report.telegram_summary = fb
    report.summary_for_human = fb
    return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_formatter.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Type check + lint**

Run: `cd /home/wdsr88/workspace/crypto-trader && mypy src/crypto_trader/evaluator/formatter.py --strict && ruff check src/crypto_trader/evaluator/`
Expected: Success

- [ ] **Step 6: Commit**

```bash
git add src/crypto_trader/evaluator/formatter.py tests/test_evaluator_formatter.py
git commit -m "feat(evaluator): add Opus formatter with template fallback"
```

---

### Task 8: Entry point script — trigger loop

**Files:**
- Create: `scripts/strategy_evaluator_v2.py`
- Modify: `scripts/strategy_evaluator_loop.py:1-3`

- [ ] **Step 1: Write the entry point script**

Create `scripts/strategy_evaluator_v2.py`:

```python
#!/usr/bin/env python3
"""
strategy_evaluator_v2.py — 플러그인 기반 정량 평가 파이프라인

실행:
  .venv/bin/python scripts/strategy_evaluator_v2.py          # 루프 모드
  .venv/bin/python scripts/strategy_evaluator_v2.py --once   # 1회 실행
  .venv/bin/python scripts/strategy_evaluator_v2.py --dry-run  # Opus 미호출
  .venv/bin/python scripts/strategy_evaluator_v2.py --force  # 간격 무시
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crypto_trader.evaluator.engine import discover_checks, run_evaluation  # noqa: E402
from crypto_trader.evaluator.formatter import format_report  # noqa: E402
from crypto_trader.evaluator.models import EvalContext, EvaluationReport  # noqa: E402

REPORT_FILE = ROOT / "state" / "evaluator_report.json"
HISTORY_FILE = ROOT / "state" / "evaluator_history_v2.json"
THROTTLE_FILE = ROOT / "config" / "loop_throttle.toml"

TRIGGER_FILES = [
    ROOT / "state" / "strategy_research.state.json",
    ROOT / "state" / "market_scan.state.json",
    ROOT / "docs" / "backtest_history.md",
    ROOT / "artifacts" / "runtime-checkpoint.json",
]

DEFAULT_MIN_INTERVAL = 1800  # 30 minutes
DEFAULT_POLL_SECONDS = 60


def _read_config() -> tuple[int, int]:
    """Read min_interval and poll_seconds from loop_throttle.toml."""
    try:
        import tomllib
        data = tomllib.loads(THROTTLE_FILE.read_text())
        section = data.get("evaluator_v2", {})
        return (
            int(section.get("min_interval_seconds", DEFAULT_MIN_INTERVAL)),
            int(section.get("poll_seconds", DEFAULT_POLL_SECONDS)),
        )
    except Exception:
        return DEFAULT_MIN_INTERVAL, DEFAULT_POLL_SECONDS


def _load_prev_report() -> EvaluationReport | None:
    """Load the previous evaluation report for change detection."""
    try:
        data = json.loads(REPORT_FILE.read_text())
        if data.get("schema_version") != 2:
            return None
        from crypto_trader.evaluator.models import CheckResult, Grade
        check_results = [
            CheckResult(
                check_name=cr["check_name"],
                grade=Grade(cr["grade"]),
                score=cr["score"],
                findings=cr["findings"],
                metrics=cr["metrics"],
                suggestions=cr.get("suggestions", []),
            )
            for cr in data.get("check_results", [])
        ]
        return EvaluationReport(
            eval_id=data["eval_id"],
            timestamp=data["generated_at"],
            overall_grade=Grade(data["overall_grade"]),
            overall_score=data["overall_score"],
            check_results=check_results,
            data_sources_used=data.get("data_sources_used", []),
            trigger_reason=data.get("trigger_reason", ""),
            summary_for_human=data.get("summary_for_human", ""),
            telegram_summary=data.get("telegram_summary", ""),
        )
    except Exception:
        return None


def _build_context() -> EvalContext:
    """Collect data from all sources into EvalContext."""
    import re

    # Backtest history tail
    bt_path = ROOT / "docs" / "backtest_history.md"
    try:
        lines = bt_path.read_text().splitlines()
        backtest_tail = "\n".join(lines[-120:])
    except Exception:
        backtest_tail = ""

    # Daemon strategies
    daemon_path = ROOT / "config" / "daemon.toml"
    daemon_strategies: list[str] = []
    try:
        text = daemon_path.read_text()
        daemon_strategies = list(set(re.findall(r'strategy\s*=\s*"([^"]+)"', text)))
    except Exception:
        pass

    # Research state
    research_state = None
    try:
        research_state = json.loads(
            (ROOT / "state" / "strategy_research.state.json").read_text()
        )
    except Exception:
        pass

    # Market scan state
    market_scan_state = None
    try:
        market_scan_state = json.loads(
            (ROOT / "state" / "market_scan.state.json").read_text()
        )
    except Exception:
        pass

    # Runtime checkpoint
    checkpoint = None
    cp_path = ROOT / "artifacts" / "runtime-checkpoint.json"
    try:
        checkpoint = json.loads(cp_path.read_text())
    except Exception:
        pass

    # Journal trades
    journal_trades: list[dict] = []
    journal_path = ROOT / "artifacts" / "journal.jsonl"
    try:
        for line in journal_path.read_text().splitlines():
            line = line.strip()
            if line:
                journal_trades.append(json.loads(line))
    except Exception:
        pass

    return EvalContext(
        backtest_history_tail=backtest_tail,
        daemon_strategies=daemon_strategies,
        daemon_config_path=daemon_path,
        research_state=research_state,
        market_scan_state=market_scan_state,
        checkpoint=checkpoint,
        journal_trades=journal_trades,
        prev_report=_load_prev_report(),
    )


def _check_trigger(last_eval_time: float) -> str | None:
    """Check if any trigger file changed since last evaluation.

    Returns the trigger reason string or None.
    """
    for path in TRIGGER_FILES:
        try:
            if path.stat().st_mtime > last_eval_time:
                return f"file_change:{path.name}"
        except FileNotFoundError:
            continue
    return None


def _save_report(report: EvaluationReport) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    tmp.replace(REPORT_FILE)


def _save_history(report: EvaluationReport) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        history = json.loads(HISTORY_FILE.read_text())
    except Exception:
        history = {"schema_version": 2, "evaluations": []}

    entry = {
        "eval_id": report.eval_id,
        "timestamp": report.timestamp,
        "overall_grade": report.overall_grade.value,
        "overall_score": report.overall_score,
        "trigger_reason": report.trigger_reason,
        "check_summary": {
            cr.check_name: cr.grade.value for cr in report.check_results
        },
    }
    history["evaluations"].append(entry)
    history["evaluations"] = history["evaluations"][-100:]

    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    tmp.replace(HISTORY_FILE)


def _notify(msg: str) -> None:
    print(f"\n{'=' * 60}\n[evaluator-v2] {msg}\n{'=' * 60}\n")
    token = os.environ.get("CT_TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("CT_TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        try:
            payload = json.dumps(
                {"chat_id": chat_id, "text": f"[평가자v2] {msg}"}
            ).encode()
            req = request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"[evaluator-v2] 텔레그램 전송 실패: {e}")


def run_once(*, dry_run: bool = False) -> bool:
    """Run one evaluation cycle. Returns True if evaluation was executed."""
    checks = discover_checks()
    if not checks:
        print("[evaluator-v2] 등록된 check 없음")
        return False

    ctx = _build_context()
    report = run_evaluation(
        checks=checks,
        ctx=ctx,
        trigger_reason="manual",
    )
    report = format_report(report, dry_run=dry_run)
    _save_report(report)
    _save_history(report)
    _notify(report.telegram_summary)

    print(
        f"[evaluator-v2] ✅ 평가 완료 — {report.eval_id}"
        f" | grade={report.overall_grade.value}"
        f" | score={report.overall_score:.2f}"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy Evaluator v2")
    parser.add_argument("--once", action="store_true", help="1회 실행 후 종료")
    parser.add_argument("--dry-run", action="store_true", help="Opus 미호출")
    parser.add_argument("--force", action="store_true", help="간격 무시 강제 실행")
    args = parser.parse_args()

    print("[evaluator-v2] Strategy Evaluator v2 시작")

    if args.once or args.force:
        run_once(dry_run=args.dry_run)
        return

    min_interval, poll_seconds = _read_config()
    last_eval_time = 0.0

    while True:
        try:
            now = time.time()
            trigger = _check_trigger(last_eval_time)
            elapsed = now - last_eval_time

            if trigger and elapsed >= min_interval:
                print(f"[evaluator-v2] 트리거 감지: {trigger}")
                ctx = _build_context()
                checks = discover_checks()
                report = run_evaluation(
                    checks=checks, ctx=ctx, trigger_reason=trigger
                )
                report = format_report(report, dry_run=args.dry_run)
                _save_report(report)
                _save_history(report)
                _notify(report.telegram_summary)
                last_eval_time = time.time()
                print(
                    f"[evaluator-v2] ✅ {report.eval_id}"
                    f" | grade={report.overall_grade.value}"
                    f" | score={report.overall_score:.2f}"
                )
            elif trigger:
                remaining = int(min_interval - elapsed)
                print(
                    f"[evaluator-v2] 변경 감지 but 간격 미달"
                    f" ({remaining}s 남음)"
                )
        except Exception as e:
            print(f"[evaluator-v2] 루프 에러: {e}")

        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Deprecate v1 script**

Add to top of `scripts/strategy_evaluator_loop.py` (after shebang, before docstring):

```python
# DEPRECATED: Use strategy_evaluator_v2.py instead.
# This script is kept for reference only.
```

- [ ] **Step 3: Test the entry point**

Run: `cd /home/wdsr88/workspace/crypto-trader && python scripts/strategy_evaluator_v2.py --once --dry-run`
Expected: Prints evaluation results, creates `state/evaluator_report.json` with `schema_version: 2`

- [ ] **Step 4: Verify report output**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -c "import json; r=json.load(open('state/evaluator_report.json')); print(r['schema_version'], r['overall_grade'])"`
Expected: `2 <some_grade>`

- [ ] **Step 5: Full test suite**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_models.py tests/test_evaluator_engine.py tests/test_evaluator_checks.py tests/test_evaluator_formatter.py -v`
Expected: All tests PASS

- [ ] **Step 6: Type check entire evaluator package**

Run: `cd /home/wdsr88/workspace/crypto-trader && mypy src/crypto_trader/evaluator/ --strict`
Expected: Success

- [ ] **Step 7: Lint check**

Run: `cd /home/wdsr88/workspace/crypto-trader && ruff check src/crypto_trader/evaluator/ scripts/strategy_evaluator_v2.py`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add scripts/strategy_evaluator_v2.py scripts/strategy_evaluator_loop.py
git commit -m "feat(evaluator): add v2 entry point script with trigger loop, deprecate v1"
```

---

### Task 9: Integration test — full pipeline dry run

**Files:**
- No new files

- [ ] **Step 1: Run full pipeline integration test**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest tests/test_evaluator_models.py tests/test_evaluator_engine.py tests/test_evaluator_checks.py tests/test_evaluator_formatter.py -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Dry-run end-to-end**

Run: `cd /home/wdsr88/workspace/crypto-trader && python scripts/strategy_evaluator_v2.py --once --dry-run`
Expected: Report generated, no Opus call, fallback formatting used

- [ ] **Step 3: Verify discover_checks finds all 4 checks**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -c "from crypto_trader.evaluator.engine import discover_checks; checks = discover_checks(); print(f'{len(checks)} checks: {[c.name for c in checks]}')" 2>&1`
Expected: `4 checks: ['backtest_quality', 'portfolio_risk', 'research_progress', 'strategy_health']` (order may vary)

- [ ] **Step 4: Full project test suite**

Run: `cd /home/wdsr88/workspace/crypto-trader && python -m pytest -x -q`
Expected: All existing + new tests PASS

- [ ] **Step 5: Final commit with all tests green**

```bash
git add -A
git commit -m "feat(evaluator): complete v2 pipeline — 4 checks, engine, formatter, trigger loop"
```
