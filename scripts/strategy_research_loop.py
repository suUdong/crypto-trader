#!/usr/bin/env python3
"""
strategy_research_loop.py — Crypto-Trader 전략 연구 루프 v1.0

토큰 최소화 원칙:
  - 루틴(실행·파싱·기록)은 순수 Python (토큰 0)
  - Claude 호출: 신규 전략 가설 생성 시만
  - 알림: 신규 전략 개발 OR Sharpe > NOTIFY_SHARPE 시만

실행:
  python scripts/crypto_ralph.py            # 포그라운드
  python scripts/crypto_ralph.py --once     # 1사이클만
  python scripts/crypto_ralph.py --dry-run  # 실행 없이 태스크 목록만
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crypto_trader.operator.research_io import (  # noqa: E402
    notify_research,
    run_claude_cli,
)
from crypto_trader.operator.research_prompts import (  # noqa: E402
    build_followup_prompt,
    build_hypothesis_prompt,
    build_quality_review_prompt,
    build_replenish_prompt,
)
from crypto_trader.operator.research_quality import (  # noqa: E402
    format_history_entry,
    grade_emoji,
    parse_research_result,
    quality_check_backtest,
    quality_check_hypothesis,
)
from crypto_trader.operator.research_state import (  # noqa: E402
    load_research_state,
    save_research_state,
)
from crypto_trader.operator.research_summary import (  # noqa: E402
    build_poor_ids,
    build_promising_summary,
    build_quality_review_lines,
    build_quality_summary,
)
from crypto_trader.operator.research_tasks import (  # noqa: E402
    DEFAULT_RESEARCH_PIPELINE,
    parse_new_task_markers,
    pick_next_research_task,
)


# venv Python 기준으로 torch 가용성 체크
def _check_torch(python: str) -> bool:
    try:
        r = subprocess.run([python, "-c", "import torch"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False

STATE_FILE = ROOT / "state" / "strategy_research.state.json"
HISTORY_FILE = ROOT / "docs" / "backtest_history.md"
SCRIPTS = ROOT / "scripts"

# 프로젝트 venv Python 우선 사용 (torch/CUDA 포함)
_VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable
_TORCH_AVAILABLE = _check_torch(PYTHON)

NOTIFY_SHARPE = 3.0   # 이 이상 Sharpe면 알림
CYCLE_SLEEP = 600     # 사이클 간 대기 (초) — loop_throttle.toml로 오버라이드 가능
THROTTLE_FILE = ROOT / "config" / "loop_throttle.toml"


def _read_throttle_sleep() -> int:
    """config/loop_throttle.toml에서 research.cycle_sleep_seconds 읽기."""
    try:
        import tomllib
        data = tomllib.loads(THROTTLE_FILE.read_text())
        return int(data.get("research", {}).get("cycle_sleep_seconds", CYCLE_SLEEP))
    except Exception:
        return CYCLE_SLEEP

# ── 품질 기준 ─────────────────────────────────────────────────────────────────
MIN_MEANINGFUL_TRADES = 30   # 통계적 의미를 갖기 위한 최소 거래 수 (Opus/Codex 리뷰: n<30 불충분)
MIN_PROMISING_SHARPE  = 3.0  # promising 등급 기준
MIN_MARGINAL_SHARPE   = 0.5  # marginal 등급 기준 (이하는 poor)

PIPELINE = DEFAULT_RESEARCH_PIPELINE


# ── 상태 관리 ─────────────────────────────────────────────────────────────────

def load_state() -> dict:
    return load_research_state(STATE_FILE)


def save_state(state: dict) -> None:
    save_research_state(STATE_FILE, state)

# ── 히스토리 기록 ─────────────────────────────────────────────────────────────

def record_history(task: dict, result: dict, note: str = "", grade: str = "") -> None:
    entry = format_history_entry(task, result, note=note, grade=grade)
    with HISTORY_FILE.open("a") as f:
        f.write(entry)
    sharpe_str = (
        f"{result['best_sharpe']:+.3f}" if result["best_sharpe"] is not None else "N/A"
    )
    print(f"[research] history 기록: {task['id']} Sharpe={sharpe_str} {grade}".rstrip())


def notify(msg: str, *, always: bool = False) -> None:
    """사용자 알림 — 텔레그램 + stdout."""
    notify_research(msg, env=os.environ, print_fn=print)


# ── Claude 가설 생성 ──────────────────────────────────────────────────────────

def _run_claude_cli(prompt: str, timeout: int = 120) -> str:
    """Claude CLI 호출 (--dangerously-skip-permissions). 실패 시 빈 문자열."""
    return run_claude_cli(prompt, cwd=ROOT, timeout=timeout)


def ask_claude_hypothesis(quality_log: list | None = None) -> str:
    """Claude CLI로 신규 전략 가설 생성. 실패 시 빈 문자열."""
    history_tail = ""
    if HISTORY_FILE.exists():
        history_tail = HISTORY_FILE.read_text()[-3000:]
    quality_summary = build_quality_summary(quality_log or [])
    prompt = build_hypothesis_prompt(quality_summary, history_tail)

    return _run_claude_cli(prompt, timeout=120)


# ── 유망 결과 → 즉시 후속 태스크 생성 ───────────────────────────────────────────

def generate_followup_task(task: dict, result: dict, state: dict) -> dict | None:
    """promising 결과가 나오면 즉시 후속 스크립트 작성 요청.

    Claude가 직접 scripts/에 파일 작성 + NEW_TASK 마커 출력하면 반환.
    """
    history_tail = HISTORY_FILE.read_text()[-2000:] if HISTORY_FILE.exists() else ""
    sharpe = result.get("best_sharpe", 0)
    raw = result.get("raw_tail", "")[-1500:]

    prompt = build_followup_prompt(
        task_desc=task["desc"],
        sharpe=sharpe,
        raw_tail=raw,
        history_tail=history_tail,
        python_path=PYTHON,
    )

    print("[research] 🔥 promising 결과 → 후속 태스크 즉시 생성 중...")
    output = _run_claude_cli(prompt, timeout=900)
    if not output:
        return None

    for candidate in parse_new_task_markers(output):
        script = candidate["script"]
        if (SCRIPTS / script).exists():
            print(f"[research] ✅ 후속 태스크: [{candidate['id']}] {script}")
            return candidate
        print(f"[research] ⚠️  스크립트 없음: {script}")
    return None


# ── 파이프라인 소진 시 신규 태스크 생성 ─────────────────────────────────────────

def replenish_pipeline(state: dict) -> list[dict]:
    """파이프라인 소진 시 Opus(Claude)에게 새 백테스트 스크립트 작성 + 태스크 정의 요청.

    Claude가 직접 scripts/ 디렉토리에 파일을 작성하고,
    NEW_TASK 마커로 태스크 정의를 출력하면 파싱해서 반환.
    """
    history_tail = HISTORY_FILE.read_text()[-4000:] if HISTORY_FILE.exists() else "(없음)"
    quality_log = state.get("quality_log", [])
    done_ids = state.get("done", [])
    poor_ids = build_poor_ids(quality_log)
    promising_summary = build_promising_summary(quality_log)

    prompt = build_replenish_prompt(
        promising_summary=promising_summary,
        done_ids=done_ids,
        poor_ids=poor_ids,
        history_tail=history_tail,
        python_path=PYTHON,
    )

    print("[research] 🔄 파이프라인 소진 — Opus(Claude)에게 신규 태스크 요청 중...")
    notify("파이프라인 소진 — Claude에게 신규 백테스트 스크립트 요청 중...")

    output = _run_claude_cli(prompt, timeout=1800)
    if not output:
        print("[research] ⚠️  신규 태스크 생성 실패")
        return []

    # NEW_TASK 마커 파싱
    new_tasks = []
    for candidate in parse_new_task_markers(output):
        script = candidate["script"]
        script_path = SCRIPTS / script
        if script_path.exists():
            new_tasks.append(candidate)
            print(f"[research] ✅ 신규 태스크 추가: [{candidate['id']}] {script}")
        else:
            print(f"[research] ⚠️  스크립트 없음 (작성 실패?): {script}")

    if new_tasks:
        notify(f"신규 태스크 {len(new_tasks)}개 추가:\n" + "\n".join(
            f"  - {t['id']}: {t['desc']}" for t in new_tasks
        ))
    return new_tasks


# ── 백테스트 실행 ─────────────────────────────────────────────────────────────

def run_backtest(task: dict, dry_run: bool = False) -> dict | None:
    script = SCRIPTS / task["script"]
    if not script.exists():
        print(f"[research] 스크립트 없음: {script} — 건너뜀")
        return None

    print(f"[research] 실행: {task['script']} ({task['desc']})")
    if dry_run:
        return {
            "best_sharpe": None,
            "best_wr": None,
            "total_trades": None,
            "avg_pct": None,
            "raw_tail": "(dry-run)",
        }

    try:
        proc = subprocess.run(
            [PYTHON, str(script)],
            capture_output=True, text=True, timeout=3600, cwd=ROOT,
        )
        output = proc.stdout + proc.stderr
        return parse_research_result(output)
    except subprocess.TimeoutExpired:
        print(f"[research] 타임아웃: {task['script']}")
        return None
    except Exception as e:
        print(f"[research] 실행 오류: {e}")
        return None


# ── 메인 루프 ─────────────────────────────────────────────────────────────────

def pick_next_task(state: dict) -> dict | None:
    all_tasks = PIPELINE + state.get("dynamic_tasks", [])
    return pick_next_research_task(
        all_tasks,
        done_ids=set(state["done"]),
        torch_available=_TORCH_AVAILABLE,
        interval_last_run=state.get("interval_last_run", {}),
        now=datetime.now(UTC),
    )


def run_cycle(state: dict, dry_run: bool = False) -> dict:
    state["cycle"] += 1
    state["last_run"] = datetime.now(UTC).isoformat()
    cycle = state["cycle"]
    print(f"\n[research] === Cycle {cycle} ({datetime.now(UTC).strftime('%H:%M UTC')}) ===")

    task = pick_next_task(state)
    if task is None:
        print("[research] 파이프라인 완료 — Claude에게 신규 태스크 요청")
        new_tasks = replenish_pipeline(state)
        if new_tasks:
            state.setdefault("dynamic_tasks", []).extend(new_tasks)
            # 새 태스크 done 목록에서 제거 (재실행 가능하게)
            new_ids = {t["id"] for t in new_tasks}
            state["done"] = [d for d in state["done"] if d not in new_ids]
        else:
            # 생성 실패 시 1시간 대기 후 재시도
            print("[research] 신규 태스크 없음 — 1시간 후 재시도")
            time.sleep(3600)
        return state

    print(f"[research] 태스크: [{task['id']}] {task['desc']}")

    if task["type"] == "backtest":
        result = run_backtest(task, dry_run=dry_run)
        if result:
            qc = quality_check_backtest(
                result,
                min_meaningful_trades=MIN_MEANINGFUL_TRADES,
                min_promising_sharpe=MIN_PROMISING_SHARPE,
                min_marginal_sharpe=MIN_MARGINAL_SHARPE,
            )
            grade = qc["grade"]
            print(f"[research] 품질 체크: {grade_emoji(grade)}[{grade}] — {qc['reason']}")

            if grade == "error":
                print(f"[research] ❌ 기록 스킵 — 에러 결과: {qc['reason']}")
            else:
                record_history(task, result, grade=grade)
                # 품질 로그 누적
                state.setdefault("quality_log", []).append({
                    "id": task["id"],
                    "grade": grade,
                    "sharpe": result["best_sharpe"],
                    "reason": qc["reason"],
                    "cycle": state["cycle"],
                })

            sharpe = result["best_sharpe"]
            should_notify = task.get("notify_on_significant") and sharpe and sharpe >= NOTIFY_SHARPE
            if should_notify:
                notify(
                    f"유의미한 결과 발견!\n전략: {task['desc']}\n"
                    f"Sharpe: {sharpe:+.3f} | WR: {result['best_wr']}% | "
                    f"trades: {result['total_trades']}"
                )
            # promising이면 즉시 후속 태스크 생성 (자기개선 핵심)
            if grade == "promising":
                followup = generate_followup_task(task, result, state)
                if followup and followup["id"] not in set(state["done"]):
                    state.setdefault("dynamic_tasks", []).append(followup)
                    print(f"[research] ➡️  후속 태스크 파이프라인에 추가: {followup['id']}")
            # ── 자동 파라미터 적용 ────────────────────────────────────────────
            if sharpe and not dry_run and grade != "error":
                try:
                    from wallet_auto_updater import apply_param_update
                    trigger = f"{task['id']} Sharpe={sharpe:+.3f} cycle={state['cycle']}"
                    applied = apply_param_update(
                        strategy_id=task["id"],
                        output=result["raw_tail"],
                        best_sharpe=sharpe,
                        trigger=trigger,
                        restart=True,
                        n_trades=result.get("total_trades"),
                    )
                    if applied:
                        notify(
                            f"파라미터 자동 적용!\n전략: {task['desc']}\n"
                            f"Sharpe: {sharpe:+.3f} → daemon 재시작 완료"
                        )
                except Exception as _e:
                    print(f"[research] 파라미터 자동 적용 실패: {_e}")
        state["done"].append(task["id"])

    elif task["type"] == "hypothesis":
        notify("[신규 전략 탐색 시작] Claude 가설 생성 중...")
        hypothesis = ask_claude_hypothesis(quality_log=state.get("quality_log"))
        if hypothesis:
            qc = quality_check_hypothesis(hypothesis)
            if qc["grade"] == "error":
                print(f"[research] ❌ 가설 기록 스킵 — {qc['reason']}")
                # Credit 부족 등 API 에러: done에 추가해 1사이클 쉬고 다음 파이프라인으로 이동
                # (파이프라인 소진 시 자동으로 done에서 제거되어 재시도됨)
                state["done"].append(task["id"])
                return state
            print(f"\n[research] Claude 가설:\n{hypothesis}\n")
            notify(f"신규 전략 가설 생성 완료:\n\n{hypothesis}")
            fake_result = {
                "best_sharpe": None, "best_wr": None,
                "total_trades": None, "avg_pct": None, "raw_tail": hypothesis,
            }
            record_history(task, fake_result, note="Claude 가설 (미검증)", grade="ok")
        state["done"].append(task["id"])

    elif task["type"] == "quality_review":
        _run_quality_review(task, state)
        # interval 태스크: done에 추가하지 않고 last_run만 갱신
        state.setdefault("interval_last_run", {})[task["id"]] = (
            datetime.now(UTC).isoformat()
        )

    save_state(state)
    return state


def _run_quality_review(task: dict, state: dict) -> None:
    """Claude에게 최근 품질 로그와 히스토리를 보여주고 방향성 리뷰를 받는다."""
    quality_log = state.get("quality_log", [])
    history_tail = ""
    if HISTORY_FILE.exists():
        history_tail = HISTORY_FILE.read_text()[-4000:]

    # 품질 통계 요약
    grades = [q.get("grade", "") for q in quality_log]
    stats = {g: grades.count(g) for g in ("promising", "marginal", "poor", "error")}
    promising_lines = build_quality_review_lines(quality_log)
    prompt = build_quality_review_prompt(
        stats=stats,
        promising_lines=promising_lines,
        history_tail=history_tail,
    )

    print("\n[research] 🔍 일일 품질 리뷰 시작...")
    try:
        review = _run_claude_cli(prompt, timeout=120)
    except Exception as e:
        print(f"[research] 품질 리뷰 실패: {e}")
        return

    qc = quality_check_hypothesis(review)
    if qc["grade"] == "error":
        print(f"[research] ❌ 품질 리뷰 스킵 — {qc['reason']}")
        return

    print(f"\n[research] 📋 품질 리뷰 결과:\n{review}\n")
    notify(f"📋 일일 품질 리뷰:\n\n{review}")

    # history에 기록
    fake_result = {
        "best_sharpe": None, "best_wr": None,
        "total_trades": None, "avg_pct": None, "raw_tail": review,
    }
    record_history(task, fake_result, note="LLM 품질/방향성 리뷰", grade="ok")


def main() -> None:
    parser = argparse.ArgumentParser(description="crypto-ralph 자율 랩 루프")
    parser.add_argument("--once", action="store_true", help="1사이클만 실행")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="스크립트 실행 없이 태스크 목록 확인",
    )
    parser.add_argument("--reset", action="store_true", help="done 목록 초기화")
    args = parser.parse_args()

    state = load_state()

    if args.reset:
        state["done"] = []
        save_state(state)
        print("[research] done 목록 초기화 완료")
        return

    if args.dry_run:
        print("[research] 파이프라인 태스크 목록:")
        done = set(state["done"])
        for t in PIPELINE:
            status = "✅ 완료" if t["id"] in done else "⏳ 대기"
            print(f"  {status} [{t['id']}] {t['desc']}")
        return

    print(f"[research] 시작 — 파이프라인 {len(PIPELINE)}개 태스크 | 완료: {len(state['done'])}개")
    print(f"[research] 알림 임계값: Sharpe >= {NOTIFY_SHARPE}")

    while True:
        state = run_cycle(state, dry_run=args.dry_run)
        if args.once:
            break
        sleep_secs = _read_throttle_sleep()
        print(f"[research] 다음 사이클까지 {sleep_secs}초 대기...")
        time.sleep(sleep_secs)


if __name__ == "__main__":
    main()
