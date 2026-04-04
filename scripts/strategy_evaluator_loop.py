#!/usr/bin/env python3
"""
strategy_evaluator_loop.py — 자율 전략 평가자 v1.0

Ralph/Codex 작업자 결과를 주기적으로 수집 → Trait 번들 구성 → Opus 심사 →
state/evaluator_report.json (작업자용) + Telegram (사용자용) 이중 출력.
자기 평가 이력으로 개입 threshold를 자동 조정.

실행:
  .venv/bin/python scripts/strategy_evaluator_loop.py          # 포그라운드 루프
  .venv/bin/python scripts/strategy_evaluator_loop.py --once   # 1회만
  .venv/bin/python scripts/strategy_evaluator_loop.py --dry-run  # Opus 미호출, 로직만
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = ROOT / "state" / "evaluator_history.json"
REPORT_FILE  = ROOT / "state" / "evaluator_report.json"
RALPH_STATE  = ROOT / "ralph-loop.state.json"
RESEARCH_STATE = ROOT / "state" / "strategy_research.state.json"
BACKTEST_HISTORY = ROOT / "docs" / "backtest_history.md"
DAEMON_CONFIG = ROOT / "config" / "daemon.toml"

POLL_INTERVAL = 120   # 준비도 체크 주기 (초)
ADJUSTMENT_AFTER_N = 10  # N회 평가 후 threshold 자기조정

THRESHOLD_BOUNDS = {
    "min_cycles":   (3, 20),
    "min_backtests": (1, 10),
}

# ── 상태 I/O ──────────────────────────────────────────────────────────────────

def load_history() -> dict:
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return {
            "schema_version": 1,
            "threshold": {"min_cycles": 5, "min_backtests": 2, "min_interval_minutes": 30, "last_adjusted": None},
            "evaluations": [],
            "self_review": {"total_evaluations": 0, "actionable_rate": None, "last_threshold_adjustment": None},
        }


def save_history(history: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    tmp.replace(HISTORY_FILE)


def save_report(report: dict) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    tmp.replace(REPORT_FILE)


# ── 데이터 수집 ───────────────────────────────────────────────────────────────

def collect_data(last_eval_cycle: int | None) -> dict:
    """Ralph/daemon 상태 수집. last_eval_cycle 이후 신규 데이터만 추출."""
    data: dict = {
        "ralph_cycle": 0,
        "ralph_cycles_since_last": 0,
        "ralph_recent_summaries": [],
        "new_backtests": [],
        "new_backtests_count": 0,
        "daemon_strategies": [],
        "backtest_history_tail": "",
        "minutes_since_last": 9999,
    }

    # Ralph state
    try:
        ralph = json.loads(RALPH_STATE.read_text())
        data["ralph_cycle"] = ralph.get("current_cycle", 0)
        done = ralph.get("ralph_done", [])
        since = [d for d in done if d.get("cycle", 0) > (last_eval_cycle or 0)]
        data["ralph_cycles_since_last"] = len(since)
        # backtest count: ralph cycles that mention backtest work
        backtest_keywords = ("백테스트", "Sharpe", "backtest", "W1=", "W2=")
        bt_cycles = [
            d for d in since
            if any(kw in d.get("summary", "") for kw in backtest_keywords)
        ]
        data["new_backtests_count"] = len(bt_cycles)
        data["ralph_recent_summaries"] = [
            {"cycle": d["cycle"], "summary": d.get("summary", "")} for d in done[-5:]
        ]
    except Exception:
        pass

    # Backtest history — 마지막 120줄
    try:
        lines = BACKTEST_HISTORY.read_text().splitlines()
        tail = lines[-120:]
        data["backtest_history_tail"] = "\n".join(tail)
        # 슬리피지 구간별 결과 파싱 (간단 휴리스틱)
        bt_entries: list[dict] = []
        for line in tail:
            m = re.search(r"슬리피지\s*([\d.]+)%.*Sharpe[:\s]+([\d.+-]+)", line)
            if m:
                bt_entries.append({"slippage": float(m.group(1)), "sharpe": float(m.group(2))})
        data["new_backtests"] = bt_entries
    except Exception:
        pass

    # Daemon 활성 전략
    try:
        daemon_text = DAEMON_CONFIG.read_text()
        strategies = re.findall(r'strategy\s*=\s*"([^"]+)"', daemon_text)
        data["daemon_strategies"] = list(set(strategies))
    except Exception:
        pass

    return data


# ── Trait 번들 ────────────────────────────────────────────────────────────────

TRAIT_DESCRIPTIONS = {
    "statistical_auditor":    "Statistical Auditor — n_trades 충분성, Sharpe 통계적 유의성, OOS 윈도우 중복 여부 검사",
    "slippage_stress_tester": "Slippage Stress Tester — 슬리피지-Sharpe 곡선 분석, 실전 적용 가능성 판정",
    "regime_specialist":      "Regime Specialist — 레짐별(BULL/BEAR) 엣지 실재 여부, Gate 효과성, 조건부 배포 타당성",
    "comparative_analyst":    "Comparative Analyst — 전략 간 순위, buy-and-hold 대비, 잉여 전략 식별",
    "live_monitor":           "Live Monitor — 백테스트 vs 실제 성과 괴리, daemon 교체 트리거 판단",
    "opportunity_scout":      "Opportunity Scout — 히스토리 공백 분석, 다음 유망 방향 3개 제안",
}


def decide_traits(data: dict) -> list[str]:
    """데이터 특징에 따라 Trait 번들 자동 구성. statistical_auditor는 항상 포함."""
    traits = ["statistical_auditor"]

    bt = data.get("new_backtests", [])
    slippage_values = {round(b["slippage"], 3) for b in bt if "slippage" in b}
    if len(slippage_values) >= 2:
        traits.append("slippage_stress_tester")

    if len(data.get("daemon_strategies", [])) >= 2:
        traits.append("comparative_analyst")

    if data.get("daemon_strategies"):
        traits.append("live_monitor")

    # regime_specialist: 히스토리에 BULL/BEAR 키워드 있으면
    history_tail = data.get("backtest_history_tail", "")
    if "BULL" in history_tail or "BEAR" in history_tail:
        traits.append("regime_specialist")

    # opportunity_scout: 기본 포함 (항상 다음 방향 필요)
    traits.append("opportunity_scout")

    return traits


# ── 준비도 판단 ───────────────────────────────────────────────────────────────

def should_evaluate(data: dict, threshold: dict) -> bool:
    """세 조건 모두 충족 시 True: cycles, backtests, interval."""
    cycles_ok = data.get("ralph_cycles_since_last", 0) >= threshold["min_cycles"]
    backtests_ok = data.get("new_backtests_count", 0) >= threshold["min_backtests"]
    interval_ok = data.get("minutes_since_last", 0) >= threshold["min_interval_minutes"]
    return cycles_ok and backtests_ok and interval_ok


# ── Opus 프롬프트 빌드 ────────────────────────────────────────────────────────

def build_opus_prompt(traits: list[str], data: dict) -> str:
    trait_block = "\n".join(f"- {TRAIT_DESCRIPTIONS[t]}" for t in traits if t in TRAIT_DESCRIPTIONS)
    summaries_block = "\n".join(
        f"  사이클 {s['cycle']}: {s['summary']}" for s in data.get("ralph_recent_summaries", [])
    )

    return f"""당신은 crypto-trader 전략 평가 전문가입니다. 아래 데이터를 분석하고 구조화된 평가를 수행하세요.

## 활성 평가 Trait
{trait_block}

## Ralph 최근 사이클 요약 (최근 5개)
{summaries_block or "(없음)"}

## 백테스트 히스토리 (최근 120줄)
{data.get("backtest_history_tail", "(없음)")}

## 현재 Daemon 활성 전략
{", ".join(data.get("daemon_strategies", [])) or "(없음)"}

## 현재 Ralph 사이클
{data.get("ralph_cycle", 0)}

---

## 심사 지침

각 활성 Trait의 전문가 렌즈로 데이터를 검토하세요:
- Statistical Auditor: n<30인 결과는 "통계 불충분"으로 명시. Sharpe 유의성 평가.
- Slippage Stress Tester: 슬리피지 구간별 성과 곡선 분석. 0.10%→0.20% 낙차가 크면 실전 부적합.
- Regime Specialist: BULL vs BEAR 구간 성과 분리. Gate 필터 효과성 평가.
- Comparative Analyst: 전략 간 Sharpe/WR/슬리피지 내성 비교. buy-and-hold 대비 우위 여부.
- Live Monitor: daemon 전략의 실제 vs 백테스트 성과 괴리 추정.
- Opportunity Scout: 미탐색 영역 식별. 다음 유망 방향 최소 3개 제안.

## 출력 형식

반드시 아래 JSON을 마크다운 코드블록(```json ... ```)으로 출력하세요:

```json
{{
  "overall_grade": "poor | promising | deploy_ready | investigate",
  "key_findings": ["핵심 발견 1", "핵심 발견 2"],
  "direction": "다음 작업자에게 전달할 구체적 방향 (한국어, 2-3문장)",
  "directives": [
    {{
      "type": "explore | avoid | deploy | monitor | investigate",
      "target": "대상 전략/파라미터",
      "reason": "이유",
      "suggested_action": "구체적 행동"
    }}
  ],
  "blockers": ["daemon 반영 전 해결 필요 사항 (없으면 빈 배열)"],
  "actionable": true,
  "telegram_summary": "사용자용 한국어 요약 (5-8줄, 이모지 포함)"
}}
```
"""


# ── 출력 파싱 ─────────────────────────────────────────────────────────────────

def parse_evaluation_output(raw: str) -> dict:
    """Opus 출력에서 JSON 블록 추출. 실패 시 fallback dict 반환."""
    fallback = {
        "overall_grade": "unknown",
        "key_findings": [],
        "direction": "파싱 실패 — 원본 출력 확인 필요",
        "directives": [],
        "blockers": [],
        "actionable": False,
        "telegram_summary": "평가자 응답 파싱 실패",
    }
    m = re.search(r"```json\s*([\s\S]+?)\s*```", raw)
    if not m:
        return fallback
    try:
        parsed = json.loads(m.group(1))
        # 필수 키 보장
        for key, default in fallback.items():
            parsed.setdefault(key, default)
        return parsed
    except json.JSONDecodeError:
        return fallback


# ── Claude Opus 호출 ──────────────────────────────────────────────────────────

def call_opus(prompt: str, timeout: int = 300) -> str | None:
    """Claude CLI로 Opus 호출. 실패 시 빈 문자열."""
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p", prompt],
            capture_output=True, text=True, timeout=timeout, cwd=ROOT,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"[evaluator] Opus 호출 실패: {e}")
        return None


# ── Telegram ──────────────────────────────────────────────────────────────────

def _telegram_creds() -> tuple[str, str] | None:
    token = os.environ.get("CT_TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("CT_TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        return token, chat_id
    return None


def notify(msg: str) -> None:
    print(f"\n{'='*60}\n🔔 [evaluator] {msg}\n{'='*60}\n")
    creds = _telegram_creds()
    if creds:
        token, chat_id = creds
        try:
            payload = json.dumps({"chat_id": chat_id, "text": f"[평가자] {msg}"}).encode()
            req = request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"[evaluator] 텔레그램 전송 실패: {e}")


# ── Threshold 자기조정 ────────────────────────────────────────────────────────

def adjust_threshold(threshold: dict, self_review: dict) -> dict:
    """
    actionable_rate 기반 threshold 조정.
    - < 0.5: 너무 일찍 개입 → 상향
    - > 0.8: 너무 늦게 개입 → 하향
    - 그 외: 유지
    """
    rate = self_review.get("actionable_rate")
    if rate is None:
        return threshold

    new = dict(threshold)
    min_c_lo, min_c_hi = THRESHOLD_BOUNDS["min_cycles"]
    min_b_lo, min_b_hi = THRESHOLD_BOUNDS["min_backtests"]

    if rate < 0.5:
        new["min_cycles"]    = min(new["min_cycles"] + 2, min_c_hi)
        new["min_backtests"] = min(new["min_backtests"] + 1, min_b_hi)
        new["last_adjusted"] = datetime.now(timezone.utc).isoformat()
        print(f"[evaluator] threshold 상향: min_cycles={new['min_cycles']}, min_backtests={new['min_backtests']} (actionable_rate={rate:.2f})")
    elif rate > 0.8:
        new["min_cycles"]    = max(new["min_cycles"] - 1, min_c_lo)
        new["min_backtests"] = max(new["min_backtests"] - 1, min_b_lo)
        new["last_adjusted"] = datetime.now(timezone.utc).isoformat()
        print(f"[evaluator] threshold 하향: min_cycles={new['min_cycles']}, min_backtests={new['min_backtests']} (actionable_rate={rate:.2f})")

    return new


def update_self_review(history: dict) -> dict:
    """evaluations 이력에서 actionable_rate 재계산."""
    evals = history.get("evaluations", [])
    if not evals:
        return history
    actionable_count = sum(1 for e in evals if e.get("verdict", {}).get("actionable", False))
    history["self_review"]["total_evaluations"] = len(evals)
    history["self_review"]["actionable_rate"] = round(actionable_count / len(evals), 3)
    return history


# ── 메인 평가 루프 ────────────────────────────────────────────────────────────

def run_once(dry_run: bool = False) -> bool:
    """
    1회 평가 시도. 준비 안 됐으면 False, 평가 완료 시 True 반환.
    """
    history = load_history()
    threshold = history["threshold"]

    # 마지막 평가 이후 경과 시간
    last_eval = history["evaluations"][-1] if history["evaluations"] else None
    last_eval_cycle = last_eval["input_summary"]["ralph_cycle_at_eval"] if last_eval else None
    if last_eval:
        try:
            last_ts = datetime.fromisoformat(last_eval["timestamp"])
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            minutes_since = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60
        except Exception:
            minutes_since = 9999.0
    else:
        minutes_since = 9999.0

    data = collect_data(last_eval_cycle)
    data["minutes_since_last"] = minutes_since

    if not should_evaluate(data, threshold):
        print(
            f"[evaluator] 준비 미달 — "
            f"cycles={data['ralph_cycles_since_last']}/{threshold['min_cycles']}, "
            f"backtests={data['new_backtests_count']}/{threshold['min_backtests']}, "
            f"interval={int(minutes_since)}m/{threshold['min_interval_minutes']}m"
        )
        return False

    traits = decide_traits(data)
    print(f"[evaluator] 평가 시작 — Traits: {traits}")

    if dry_run:
        print("[evaluator] --dry-run: Opus 호출 스킵")
        verdict = {
            "overall_grade": "dry_run",
            "key_findings": ["dry-run 모드"],
            "direction": "dry-run",
            "directives": [],
            "blockers": [],
            "actionable": False,
            "telegram_summary": "dry-run",
        }
    else:
        prompt = build_opus_prompt(traits, data)
        raw = call_opus(prompt)
        if not raw:
            print("[evaluator] Opus 응답 없음 — 이번 평가 스킵")
            return False
        verdict = parse_evaluation_output(raw)

    eval_id = f"eval-{uuid.uuid4().hex[:8]}"
    ts = datetime.now(timezone.utc).isoformat()

    # 히스토리 기록
    entry = {
        "id": eval_id,
        "timestamp": ts,
        "input_summary": {
            "ralph_cycle_at_eval": data["ralph_cycle"],
            "new_backtests_since_last": data["new_backtests_count"],
            "cycles_since_last": data["ralph_cycles_since_last"],
            "strategies_in_daemon": data["daemon_strategies"],
            "traits_activated": traits,
        },
        "verdict": verdict,
        "adopted_by_ralph": None,
    }
    history["evaluations"].append(entry)
    history["evaluations"] = history["evaluations"][-100:]  # 최대 100개 유지
    history = update_self_review(history)

    # threshold 자기조정 (N회마다)
    total = history["self_review"]["total_evaluations"]
    if total > 0 and total % ADJUSTMENT_AFTER_N == 0:
        history["threshold"] = adjust_threshold(history["threshold"], history["self_review"])

    save_history(history)

    # 작업자용 report 저장
    report = {
        "generated_at": ts,
        "eval_id": eval_id,
        "for_ralph_cycle": data["ralph_cycle"] + 1,
        "priority": "high" if verdict["overall_grade"] == "deploy_ready" else "normal",
        "traits_used": traits,
        "directives": verdict.get("directives", []),
        "key_findings": verdict.get("key_findings", []),
        "direction": verdict.get("direction", ""),
        "blockers": verdict.get("blockers", []),
        "summary_for_human": verdict.get("telegram_summary", ""),
        "expires_after_cycles": threshold["min_cycles"],
    }
    save_report(report)

    # Telegram 알림
    notify(verdict.get("telegram_summary", "평가 완료"))

    print(f"[evaluator] ✅ 평가 완료 — {eval_id} | grade={verdict['overall_grade']} | actionable={verdict['actionable']}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy Evaluator Loop")
    parser.add_argument("--once", action="store_true", help="1회 평가 후 종료")
    parser.add_argument("--dry-run", action="store_true", help="Opus 미호출, 로직만 실행")
    args = parser.parse_args()

    print("[evaluator] 🔍 Strategy Evaluator 시작")

    if args.once:
        run_once(dry_run=args.dry_run)
        return

    while True:
        try:
            run_once(dry_run=args.dry_run)
        except Exception as e:
            print(f"[evaluator] 루프 에러: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
