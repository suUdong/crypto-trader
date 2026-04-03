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
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import request

# venv Python 기준으로 torch 가용성 체크
def _check_torch(python: str) -> bool:
    try:
        r = subprocess.run([python, "-c", "import torch"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "strategy_research.state.json"
HISTORY_FILE = ROOT / "docs" / "backtest_history.md"
SCRIPTS = ROOT / "scripts"

# 프로젝트 venv Python 우선 사용 (torch/CUDA 포함)
_VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable
_TORCH_AVAILABLE = _check_torch(PYTHON)

NOTIFY_SHARPE = 3.0   # 이 이상 Sharpe면 알림
CYCLE_SLEEP = 600     # 사이클 간 대기 (초)

# ── 품질 기준 ─────────────────────────────────────────────────────────────────
MIN_MEANINGFUL_TRADES = 15   # 통계적 의미를 갖기 위한 최소 거래 수
MIN_PROMISING_SHARPE  = 3.0  # promising 등급 기준
MIN_MARGINAL_SHARPE   = 0.5  # marginal 등급 기준 (이하는 poor)

# 에러/쓰레기 결과 감지 패턴
_ERROR_PATTERNS = [
    "Credit balance is too low",
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "ImportError",
    "ConnectionError",
    "TimeoutError",
    "Error:",
]

# ── 태스크 파이프라인 ──────────────────────────────────────────────────────────
# 완료된 id는 state["done"]에 기록 → 재실행 방지
# type:
#   "backtest"   — script 실행, stdout 파싱, history 기록
#   "hypothesis" — Claude CLI로 신규 전략 아이디어 생성
# notify: True면 결과 품질 무관 사용자 알림

PIPELINE: list[dict] = [
    # GPU 스크립트 우선
    {
        "id": "stealth_sol_sweep",
        "type": "backtest",
        "desc": "stealth_3gate 전체 마켓 스캔 (GPU)",
        "script": "backtest_stealth_deep.py",
        "requires_torch": True,
        "notify_on_significant": True,
    },
    # non-GPU 스크립트
    {
        "id": "truth_seeker_sweep",
        "type": "backtest",
        "desc": "TruthSeeker 전략 파라미터 스윕",
        "script": "backtest_truth_seeker.py",
        "notify_on_significant": True,
    },
    {
        "id": "vpin_eth_grid",
        "type": "backtest",
        "desc": "vpin_eth 파라미터 그리드",
        "script": "backtest_vpin_eth_grid.py",
        "notify_on_significant": True,
    },
    {
        "id": "momentum_sol_grid",
        "type": "backtest",
        "desc": "momentum_sol 파라미터 그리드",
        "script": "backtest_momentum_sol_grid.py",
        "notify_on_significant": True,
    },
    {
        "id": "regime_stealth",
        "type": "backtest",
        "desc": "BTC 레짐 + 스텔스 2-Factor 백테스트",
        "script": "backtest_regime_stealth.py",
        "notify_on_significant": True,
    },
    {
        "id": "alpha_backtest",
        "type": "backtest",
        "desc": "GPU Alpha filter 백테스트",
        "script": "backtest_alpha_filter.py",
        "requires_torch": True,
        "notify_on_significant": True,
    },
    {
        "id": "strategy_tournament",
        "type": "backtest",
        "desc": "GPU Strategy Tournament",
        "script": "gpu_tournament.py",
        "notify_on_significant": True,
    },
    {
        "id": "new_strategy_hypothesis",
        "type": "hypothesis",
        "desc": "Claude 신규 전략 가설 생성",
        "notify": True,
    },
    {
        "id": "daily_quality_review",
        "type": "quality_review",
        "desc": "Claude 품질/방향성 일일 리뷰",
        "notify": True,
        "interval_hours": 24,   # 24시간마다 재실행
    },
]


# ── 상태 관리 ─────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            data.setdefault("cycle", 0)
            data.setdefault("done", [])
            data.setdefault("last_run", None)
            data.setdefault("quality_log", [])
            return data
        except Exception:
            pass
    return {"cycle": 0, "done": [], "last_run": None, "quality_log": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "cycle": state["cycle"],
        "done": state["done"],
        "last_run": state["last_run"],
        "quality_log": state.get("quality_log", [])[-50:],  # 최근 50개만 보존
        "interval_last_run": state.get("interval_last_run", {}),
    }, indent=2, ensure_ascii=False))


# ── 히스토리 파싱 ─────────────────────────────────────────────────────────────

def parse_history_ids() -> set[str]:
    """backtest_history.md에서 실험 ID/키워드 추출 (중복 방지용)."""
    if not HISTORY_FILE.exists():
        return set()
    text = HISTORY_FILE.read_text()
    # 섹션 헤더에서 전략명 추출
    headers = re.findall(r"^##\s+.+", text, re.MULTILINE)
    return {h.lower() for h in headers}


# ── 결과 파싱 ─────────────────────────────────────────────────────────────────

_SHARPE_RE = re.compile(r"[Ss]harpe[:\s=]+([+-]?\d+\.?\d*)")
_WR_RE = re.compile(r"(?:WR|win_rate|wr)[=:\s]+(\d+\.?\d*)%?")
_TRADES_RE = re.compile(r"(?:trades|n)[=:\s]+(\d+)")
_AVG_RE = re.compile(r"(?:avg|mean)[%=:\s]+([+-]?\d+\.?\d*)%?")
_EDGE_RE = re.compile(r"[Ee]dge[:\s=]+([+-]?\d+\.?\d*)%?")


def parse_result(output: str) -> dict:
    """stdout에서 핵심 지표 추출. Sharpe 없으면 Edge/mean으로 대체."""
    sharpes = [float(m) for m in _SHARPE_RE.findall(output)]
    wrs = [float(m) for m in _WR_RE.findall(output)]
    trades = [int(m) for m in _TRADES_RE.findall(output)]
    avgs = [float(m) for m in _AVG_RE.findall(output)]
    edges = [float(m) for m in _EDGE_RE.findall(output)]

    best_sharpe = max(sharpes) if sharpes else (max(edges) if edges else None)
    return {
        "best_sharpe": best_sharpe,   # Sharpe 없으면 best Edge로 대체
        "best_wr": max(wrs) if wrs else None,
        "total_trades": max(trades) if trades else None,
        "avg_pct": max(avgs) if avgs else None,
        "raw_tail": output[-2000:],
    }


# ── 품질 체커 ─────────────────────────────────────────────────────────────────

def quality_check_backtest(result: dict) -> dict:
    """백테스트 결과 품질 등급 판정.

    Returns:
        {"grade": "promising"|"marginal"|"poor"|"error", "reason": str}
    """
    raw = result.get("raw_tail", "")
    for pat in _ERROR_PATTERNS:
        if pat in raw:
            return {"grade": "error", "reason": f"에러 감지: {pat[:40]}"}

    sharpe = result.get("best_sharpe")
    trades = result.get("total_trades")

    if sharpe is None:
        return {"grade": "poor", "reason": "Sharpe 없음 — 스크립트 실패 또는 거래 없음"}
    if trades is not None and trades < MIN_MEANINGFUL_TRADES:
        return {"grade": "poor", "reason": f"거래 수 부족: {trades} < {MIN_MEANINGFUL_TRADES}"}
    if sharpe >= MIN_PROMISING_SHARPE:
        return {"grade": "promising", "reason": f"Sharpe {sharpe:+.3f} — 유의미한 엣지 확인"}
    if sharpe >= MIN_MARGINAL_SHARPE:
        return {"grade": "marginal", "reason": f"Sharpe {sharpe:+.3f} — 추가 검증 필요"}
    return {"grade": "poor", "reason": f"Sharpe {sharpe:+.3f} — 엣지 부족"}


def quality_check_hypothesis(text: str) -> dict:
    """hypothesis 텍스트 품질 판정."""
    for pat in _ERROR_PATTERNS:
        if pat in text:
            return {"grade": "error", "reason": f"에러 응답: {pat[:40]}"}
    if len(text.strip()) < 50:
        return {"grade": "error", "reason": "응답 너무 짧음 (API 오류 의심)"}
    return {"grade": "ok", "reason": "정상 응답"}


def _grade_emoji(grade: str) -> str:
    return {"promising": "🌟", "marginal": "🔶", "poor": "🔻", "error": "❌", "ok": "✅"}.get(grade, "")


# ── 히스토리 기록 ─────────────────────────────────────────────────────────────

def record_history(task: dict, result: dict, note: str = "", grade: str = "") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sharpe_str = f"{result['best_sharpe']:+.3f}" if result["best_sharpe"] is not None else "N/A"
    wr_str = f"{result['best_wr']:.1f}%" if result["best_wr"] is not None else "N/A"
    trades_str = str(result["total_trades"]) if result["total_trades"] else "N/A"

    grade_str = f" {_grade_emoji(grade)}[{grade}]" if grade else ""
    entry = f"""
## {ts} — {task['desc']} [ralph:{task['id']}]{grade_str}

**결과**: Sharpe {sharpe_str} | WR {wr_str} | trades {trades_str}
{f'**메모**: {note}' if note else ''}

<details><summary>raw output</summary>

```
{result['raw_tail']}
```

</details>

---
"""
    with HISTORY_FILE.open("a") as f:
        f.write(entry)
    print(f"[research] history 기록: {task['id']} Sharpe={sharpe_str} {grade_str.strip()}")


# ── 알림 ─────────────────────────────────────────────────────────────────────

def _telegram_token() -> tuple[str, str] | None:
    """환경변수에서 텔레그램 설정 읽기."""
    token = os.environ.get("CT_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("CT_TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        return token, chat_id
    return None


def notify(msg: str, *, always: bool = False) -> None:
    """사용자 알림 — 텔레그램 + stdout."""
    full_msg = f"[crypto-ralph] {msg}"
    print(f"\n{'='*60}\n🔔 {full_msg}\n{'='*60}\n")

    creds = _telegram_token()
    if creds:
        token, chat_id = creds
        try:
            payload = json.dumps({"chat_id": chat_id, "text": full_msg}).encode()
            req = request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"[research] 텔레그램 전송 실패: {e}")


# ── Claude 가설 생성 ──────────────────────────────────────────────────────────

def ask_claude_hypothesis(quality_log: list | None = None) -> str:
    """Claude CLI로 신규 전략 가설 생성. 실패 시 빈 문자열."""
    history_tail = ""
    if HISTORY_FILE.exists():
        history_tail = HISTORY_FILE.read_text()[-3000:]  # 최근 3000자

    # 품질 로그 요약 — promising/marginal만 전략 힌트로 전달
    quality_summary = ""
    if quality_log:
        promising = [q for q in quality_log if q.get("grade") == "promising"]
        marginal  = [q for q in quality_log if q.get("grade") == "marginal"]
        poor      = [q for q in quality_log if q.get("grade") == "poor"]
        lines = []
        if promising:
            lines.append("✅ 유망 결과: " + ", ".join(
                f"{q['id']}(Sharpe{q.get('sharpe', '?'):+.2f})" for q in promising[-5:]
            ))
        if marginal:
            lines.append("🔶 추가검증 필요: " + ", ".join(
                f"{q['id']}(Sharpe{q.get('sharpe', '?'):+.2f})" for q in marginal[-5:]
            ))
        if poor:
            lines.append("🔻 엣지 부족 (재탐색 불필요): " + ", ".join(
                q['id'] for q in poor[-5:]
            ))
        quality_summary = "\n".join(lines)

    prompt = f"""crypto-trader 프로젝트의 백테스트 히스토리와 품질 평가를 보고 다음에 탐색할 전략 아이디어를 1개만 제안해.

== 품질 평가 요약 ==
{quality_summary if quality_summary else '(아직 없음)'}

== 최근 백테스트 히스토리 ==
{history_tail}

형식:
전략명: <이름>
가설: <한 줄 설명>
탐색 파라미터: <핵심 파라미터 3개 이내>
예상 스크립트: <scripts/ 디렉토리에 만들 파일명>
근거: <왜 이게 다음 탐색 대상인지> (유망 결과를 발전시키거나 poor를 피하는 방향으로)

중복 실험 금지. 과거에 없는 새로운 시도만."""

    try:
        result = subprocess.run(
            ["claude", "--print", "--no-session-persistence", "-p", prompt],
            capture_output=True, text=True, timeout=60, cwd=ROOT,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"[research] Claude CLI 호출 실패: {e}")
        return ""


# ── 백테스트 실행 ─────────────────────────────────────────────────────────────

def run_backtest(task: dict, dry_run: bool = False) -> dict | None:
    script = SCRIPTS / task["script"]
    if not script.exists():
        print(f"[research] 스크립트 없음: {script} — 건너뜀")
        return None

    print(f"[research] 실행: {task['script']} ({task['desc']})")
    if dry_run:
        return {"best_sharpe": None, "best_wr": None, "total_trades": None, "avg_pct": None, "raw_tail": "(dry-run)"}

    try:
        proc = subprocess.run(
            [PYTHON, str(script)],
            capture_output=True, text=True, timeout=3600, cwd=ROOT,
        )
        output = proc.stdout + proc.stderr
        return parse_result(output)
    except subprocess.TimeoutExpired:
        print(f"[research] 타임아웃: {task['script']}")
        return None
    except Exception as e:
        print(f"[research] 실행 오류: {e}")
        return None


# ── 메인 루프 ─────────────────────────────────────────────────────────────────

def _is_interval_task_due(task: dict, state: dict) -> bool:
    """interval_hours가 설정된 태스크의 재실행 여부 확인."""
    interval_h = task.get("interval_hours")
    if interval_h is None:
        return False
    last_runs = state.get("interval_last_run", {})
    last = last_runs.get(task["id"])
    if last is None:
        return True
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
    return elapsed >= interval_h


def pick_next_task(state: dict) -> dict | None:
    done = set(state["done"])
    for task in PIPELINE:
        # interval 태스크: 시간이 됐으면 done에 있어도 재실행
        if task.get("interval_hours") and _is_interval_task_due(task, state):
            return task
        if task["id"] in done:
            continue
        if task.get("requires_torch") and not _TORCH_AVAILABLE:
            print(f"[research] torch 없음 — 건너뜀: {task['id']}")
            continue
        return task
    return None  # 파이프라인 전부 완료


def run_cycle(state: dict, dry_run: bool = False) -> dict:
    state["cycle"] += 1
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    cycle = state["cycle"]
    print(f"\n[research] === Cycle {cycle} ({datetime.now(timezone.utc).strftime('%H:%M UTC')}) ===")

    task = pick_next_task(state)
    if task is None:
        print("[research] 파이프라인 완료 — 신규 태스크 생성 대기")
        # 파이프라인 소진 시 hypothesis 재실행 (done에서 제거)
        state["done"] = [d for d in state["done"] if d != "new_strategy_hypothesis"]
        return state

    print(f"[research] 태스크: [{task['id']}] {task['desc']}")

    if task["type"] == "backtest":
        result = run_backtest(task, dry_run=dry_run)
        if result:
            qc = quality_check_backtest(result)
            grade = qc["grade"]
            print(f"[research] 품질 체크: {_grade_emoji(grade)}[{grade}] — {qc['reason']}")

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
                    f"Sharpe: {sharpe:+.3f} | WR: {result['best_wr']}% | trades: {result['total_trades']}"
                )
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
        notify(f"[신규 전략 탐색 시작] Claude 가설 생성 중...")
        hypothesis = ask_claude_hypothesis(quality_log=state.get("quality_log"))
        if hypothesis:
            qc = quality_check_hypothesis(hypothesis)
            if qc["grade"] == "error":
                print(f"[research] ❌ 가설 기록 스킵 — {qc['reason']}")
                # 재시도를 위해 done에 추가하지 않음
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
            datetime.now(timezone.utc).isoformat()
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
    promising_items = [q for q in quality_log if q.get("grade") == "promising"]

    prompt = f"""crypto-trader 자율 전략 연구 루프의 품질 리뷰어 역할이야.
아래 데이터를 보고 간결하게 답해줘.

== 품질 통계 (전체 누적) ==
promising: {stats['promising']}개 | marginal: {stats['marginal']}개 | poor: {stats['poor']}개 | error: {stats['error']}개

== 유망 결과 목록 ==
{chr(10).join(f"- {q['id']}: Sharpe{q.get('sharpe',0):+.2f} ({q['reason']})" for q in promising_items[-10:]) or '없음'}

== 최근 백테스트 히스토리 (최신순) ==
{history_tail}

답해야 할 것:
1. 현재 연구 방향이 올바른가? (유망한 결과가 나오고 있는가)
2. poor/error 비율이 너무 높지 않은가? 원인은?
3. 다음 1주일 탐색 우선순위 3가지
4. 즉시 daemon에 반영 가능한 파라미터 변경이 있는가?

3~5문장으로 핵심만."""

    print(f"\n[research] 🔍 일일 품질 리뷰 시작...")
    try:
        result = subprocess.run(
            ["claude", "--print", "--no-session-persistence", "-p", prompt],
            capture_output=True, text=True, timeout=90, cwd=ROOT,
        )
        review = result.stdout.strip()
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
    parser.add_argument("--dry-run", action="store_true", help="스크립트 실행 없이 태스크 목록 확인")
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
        print(f"[research] 다음 사이클까지 {CYCLE_SLEEP}초 대기...")
        time.sleep(CYCLE_SLEEP)


if __name__ == "__main__":
    main()
