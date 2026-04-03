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
]


# ── 상태 관리 ─────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            data.setdefault("cycle", 0)
            data.setdefault("done", [])
            data.setdefault("last_run", None)
            return data
        except Exception:
            pass
    return {"cycle": 0, "done": [], "last_run": None}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "cycle": state["cycle"],
        "done": state["done"],
        "last_run": state["last_run"],
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


# ── 히스토리 기록 ─────────────────────────────────────────────────────────────

def record_history(task: dict, result: dict, note: str = "") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sharpe_str = f"{result['best_sharpe']:+.3f}" if result["best_sharpe"] is not None else "N/A"
    wr_str = f"{result['best_wr']:.1f}%" if result["best_wr"] is not None else "N/A"
    trades_str = str(result["total_trades"]) if result["total_trades"] else "N/A"

    entry = f"""
## {ts} — {task['desc']} [ralph:{task['id']}]

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
    print(f"[research] history 기록: {task['id']} Sharpe={sharpe_str}")


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

def ask_claude_hypothesis() -> str:
    """Claude CLI로 신규 전략 가설 생성. 실패 시 빈 문자열."""
    history_tail = ""
    if HISTORY_FILE.exists():
        history_tail = HISTORY_FILE.read_text()[-3000:]  # 최근 3000자

    prompt = f"""crypto-trader 프로젝트의 백테스트 히스토리를 보고 다음에 탐색할 전략 아이디어를 1개만 제안해.

현재까지 완료된 실험 (최근):
{history_tail}

형식:
전략명: <이름>
가설: <한 줄 설명>
탐색 파라미터: <핵심 파라미터 3개 이내>
예상 스크립트: <scripts/ 디렉토리에 만들 파일명>
근거: <왜 이게 다음 탐색 대상인지>

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

def pick_next_task(state: dict) -> dict | None:
    done = set(state["done"])
    for task in PIPELINE:
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
            record_history(task, result)
            sharpe = result["best_sharpe"]
            should_notify = task.get("notify_on_significant") and sharpe and sharpe >= NOTIFY_SHARPE
            if should_notify:
                notify(
                    f"유의미한 결과 발견!\n전략: {task['desc']}\n"
                    f"Sharpe: {sharpe:+.3f} | WR: {result['best_wr']}% | trades: {result['total_trades']}"
                )
        state["done"].append(task["id"])

    elif task["type"] == "hypothesis":
        notify(f"[신규 전략 탐색 시작] Claude 가설 생성 중...")
        hypothesis = ask_claude_hypothesis()
        if hypothesis:
            print(f"\n[research] Claude 가설:\n{hypothesis}\n")
            notify(f"신규 전략 가설 생성 완료:\n\n{hypothesis}")
            # 가설을 history에 기록
            fake_result = {"best_sharpe": None, "best_wr": None, "total_trades": None, "avg_pct": None, "raw_tail": hypothesis}
            record_history(task, fake_result, note="Claude 가설 (미검증)")
        state["done"].append(task["id"])

    save_state(state)
    return state


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
