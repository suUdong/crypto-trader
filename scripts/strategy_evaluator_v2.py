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
import re
import sys
import time
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

DEFAULT_MIN_INTERVAL = 1800
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
    """Check if any trigger file changed since last evaluation."""
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
