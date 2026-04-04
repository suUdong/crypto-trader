"""Tests for strategy_evaluator_loop — core logic only (no I/O, no LLM calls)."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# scripts/ 디렉토리를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import strategy_evaluator_loop as ev


# ── decide_traits ─────────────────────────────────────────────────────────────

def test_statistical_auditor_always_present():
    data = {"new_backtests": [], "ralph_cycles_since_last": 5, "daemon_strategies": []}
    traits = ev.decide_traits(data)
    assert "statistical_auditor" in traits


def test_slippage_stress_tester_requires_two_slippage_results():
    data = {
        "new_backtests": [
            {"slippage": 0.10, "sharpe": 5.0},
            {"slippage": 0.20, "sharpe": 3.0},
        ],
        "ralph_cycles_since_last": 5,
        "daemon_strategies": [],
    }
    traits = ev.decide_traits(data)
    assert "slippage_stress_tester" in traits


def test_slippage_stress_tester_absent_when_single_result():
    data = {
        "new_backtests": [{"slippage": 0.10, "sharpe": 5.0}],
        "ralph_cycles_since_last": 5,
        "daemon_strategies": [],
    }
    traits = ev.decide_traits(data)
    assert "slippage_stress_tester" not in traits


def test_live_monitor_requires_daemon_strategies():
    data = {
        "new_backtests": [],
        "ralph_cycles_since_last": 5,
        "daemon_strategies": ["momentum_sol", "vpin_eth"],
    }
    traits = ev.decide_traits(data)
    assert "live_monitor" in traits


def test_live_monitor_absent_when_no_daemon_strategies():
    data = {"new_backtests": [], "ralph_cycles_since_last": 5, "daemon_strategies": []}
    traits = ev.decide_traits(data)
    assert "live_monitor" not in traits


def test_comparative_analyst_requires_two_similar_strategies():
    data = {
        "new_backtests": [
            {"strategy": "vpin_eth", "sharpe": 5.0},
            {"strategy": "vpin_ondo", "sharpe": 4.0},
        ],
        "ralph_cycles_since_last": 5,
        "daemon_strategies": [],
    }
    traits = ev.decide_traits(data)
    assert "comparative_analyst" in traits


# ── should_evaluate ───────────────────────────────────────────────────────────

def test_should_evaluate_true_when_both_conditions_met():
    threshold = {"min_cycles": 5, "min_backtests": 2, "min_interval_minutes": 0}
    data = {"ralph_cycles_since_last": 6, "new_backtests_count": 3, "minutes_since_last": 60}
    assert ev.should_evaluate(data, threshold) is True


def test_should_evaluate_false_when_cycles_insufficient():
    threshold = {"min_cycles": 5, "min_backtests": 2, "min_interval_minutes": 0}
    data = {"ralph_cycles_since_last": 3, "new_backtests_count": 3, "minutes_since_last": 60}
    assert ev.should_evaluate(data, threshold) is False


def test_should_evaluate_false_when_backtests_insufficient():
    threshold = {"min_cycles": 5, "min_backtests": 2, "min_interval_minutes": 0}
    data = {"ralph_cycles_since_last": 6, "new_backtests_count": 1, "minutes_since_last": 60}
    assert ev.should_evaluate(data, threshold) is False


def test_should_evaluate_false_when_interval_too_short():
    threshold = {"min_cycles": 5, "min_backtests": 2, "min_interval_minutes": 30}
    data = {"ralph_cycles_since_last": 6, "new_backtests_count": 3, "minutes_since_last": 10}
    assert ev.should_evaluate(data, threshold) is False


# ── adjust_threshold ──────────────────────────────────────────────────────────

def test_threshold_increases_when_actionable_rate_low():
    """actionable < 50% → threshold 상향."""
    threshold = {"min_cycles": 5, "min_backtests": 2, "min_interval_minutes": 30, "last_adjusted": None}
    self_review = {"total_evaluations": 10, "actionable_rate": 0.3, "last_threshold_adjustment": None}
    new_threshold = ev.adjust_threshold(threshold, self_review)
    assert new_threshold["min_cycles"] > 5


def test_threshold_decreases_when_actionable_rate_high():
    """actionable > 80% → threshold 하향."""
    threshold = {"min_cycles": 8, "min_backtests": 4, "min_interval_minutes": 30, "last_adjusted": None}
    self_review = {"total_evaluations": 10, "actionable_rate": 0.9, "last_threshold_adjustment": None}
    new_threshold = ev.adjust_threshold(threshold, self_review)
    assert new_threshold["min_cycles"] < 8


def test_threshold_unchanged_when_actionable_rate_normal():
    """50% <= actionable <= 80% → 유지."""
    threshold = {"min_cycles": 5, "min_backtests": 2, "min_interval_minutes": 30, "last_adjusted": None}
    self_review = {"total_evaluations": 10, "actionable_rate": 0.65, "last_threshold_adjustment": None}
    new_threshold = ev.adjust_threshold(threshold, self_review)
    assert new_threshold["min_cycles"] == 5


def test_threshold_respects_min_bound():
    """min_cycles 하한: 3."""
    threshold = {"min_cycles": 3, "min_backtests": 1, "min_interval_minutes": 30, "last_adjusted": None}
    self_review = {"total_evaluations": 10, "actionable_rate": 0.95, "last_threshold_adjustment": None}
    new_threshold = ev.adjust_threshold(threshold, self_review)
    assert new_threshold["min_cycles"] >= 3


def test_threshold_respects_max_bound():
    """min_cycles 상한: 20."""
    threshold = {"min_cycles": 20, "min_backtests": 10, "min_interval_minutes": 30, "last_adjusted": None}
    self_review = {"total_evaluations": 10, "actionable_rate": 0.1, "last_threshold_adjustment": None}
    new_threshold = ev.adjust_threshold(threshold, self_review)
    assert new_threshold["min_cycles"] <= 20


# ── build_opus_prompt ─────────────────────────────────────────────────────────

def test_build_opus_prompt_contains_all_active_traits():
    traits = ["statistical_auditor", "slippage_stress_tester", "regime_specialist"]
    data = {
        "ralph_cycle": 127,
        "new_backtests": [],
        "daemon_strategies": [],
        "backtest_history_tail": "",
        "ralph_recent_summaries": [],
    }
    prompt = ev.build_opus_prompt(traits, data)
    assert "Statistical Auditor" in prompt
    assert "Slippage Stress Tester" in prompt
    assert "Regime Specialist" in prompt


def test_build_opus_prompt_requests_json_output():
    traits = ["statistical_auditor"]
    data = {
        "ralph_cycle": 100,
        "new_backtests": [],
        "daemon_strategies": [],
        "backtest_history_tail": "",
        "ralph_recent_summaries": [],
    }
    prompt = ev.build_opus_prompt(traits, data)
    assert "JSON" in prompt


# ── parse_evaluation_output ───────────────────────────────────────────────────

def test_parse_evaluation_output_extracts_json_block():
    raw = """분석 완료.

```json
{"overall_grade": "promising", "key_findings": ["BB bounce 슬리피지 취약"], "direction": "TP 축소 재탐색", "blockers": [], "actionable": true, "telegram_summary": "요약"}
```

이상입니다."""
    result = ev.parse_evaluation_output(raw)
    assert result["overall_grade"] == "promising"
    assert result["actionable"] is True


def test_parse_evaluation_output_returns_fallback_on_invalid_json():
    raw = "JSON 없는 응답입니다."
    result = ev.parse_evaluation_output(raw)
    assert result["overall_grade"] == "unknown"
    assert result["actionable"] is False
