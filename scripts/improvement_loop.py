#!/usr/bin/env python3
"""
improvement_loop.py — 자율 개선 루프 (Ralph Mode 대체)

주기: 4시간 (4h 봉 기준)

사이클 구조:
  1. MONITOR  — 최근 파라미터 변경 후 페이퍼 성과 측정
  2. EVALUATE — 성과 개선 / 악화 판단
  3. ROLLBACK — 악화 시 이전 daemon.toml 복구
  4. RESET    — 파이프라인 완료 시 가설 재생성 트리거
  5. REPORT   — 주기 요약 텔레그램 전송

기존 루프와 역할 분담:
  market_scan_loop      → 시장 스캔 + 심볼 교체 (건드리지 않음)
  strategy_research_loop → 백테스트 + 파라미터 적용 (건드리지 않음)
  improvement_loop      → 성과 감시 + 롤백 + 리포트
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parent.parent
PAPER_TRADES  = ROOT / "artifacts" / "paper-trades.jsonl"
WALLET_CHANGES = ROOT / "artifacts" / "wallet_changes.jsonl"
BACKUP_DIR    = ROOT / "artifacts" / "daemon-backups"
STATE_FILE    = ROOT / "state" / "improvement_loop.state.json"
HISTORY_MD    = ROOT / "docs" / "backtest_history.md"
RESEARCH_STATE = ROOT / "state" / "strategy_research.state.json"

CYCLE_HOURS   = 4        # 메인 루프 주기
MONITOR_HOURS = 48       # 파라미터 변경 후 성과 관측 기간
ROLLBACK_THRESHOLD = -0.05  # 누적 수익률 -5% 시 롤백
REPORT_INTERVAL_CYCLES = 6  # 24시간마다 리포트 (6사이클 × 4h)


# ── 상태 관리 ─────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "cycle": 0,
        "last_change_ts": None,     # 마지막 파라미터/심볼 변경 시각
        "last_change_type": None,
        "baseline_pnl": None,       # 변경 직전 누적 PnL
        "monitoring": False,        # 성과 관측 중 여부
        "last_report_cycle": 0,
        "rollback_count": 0,
    }


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── 페이퍼 트레이드 성과 측정 ─────────────────────────────────────────────────

def get_recent_pnl(since_ts: str | None = None, hours: int = 48) -> dict:
    """최근 N시간 페이퍼 트레이드 성과 집계."""
    if not PAPER_TRADES.exists():
        return {"total_pnl": 0.0, "trades": 0, "win_rate": 0.0}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    if since_ts:
        try:
            cutoff = datetime.fromisoformat(since_ts)
        except Exception:
            pass

    trades = []
    with PAPER_TRADES.open() as f:
        for line in f:
            try:
                t = json.loads(line)
                exit_time = t.get("exit_time") or t.get("entry_time", "")
                if exit_time:
                    ts = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                    if ts >= cutoff:
                        trades.append(t)
            except Exception:
                pass

    if not trades:
        return {"total_pnl": 0.0, "trades": 0, "win_rate": 0.0}

    total_pnl = sum(t.get("pnl", 0) for t in trades)
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return {
        "total_pnl": round(total_pnl, 0),
        "trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0.0,
        "pnl_pct": round(sum(t.get("pnl_pct", 0) for t in trades) * 100, 3),
    }


def get_latest_wallet_change() -> dict | None:
    """wallet_changes.jsonl에서 가장 최근 변경 이벤트 반환."""
    if not WALLET_CHANGES.exists():
        return None
    lines = WALLET_CHANGES.read_text().strip().splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except Exception:
            pass
    return None


# ── 롤백 ─────────────────────────────────────────────────────────────────────

def get_latest_backup() -> Path | None:
    if not BACKUP_DIR.exists():
        return None
    backups = sorted(BACKUP_DIR.glob("daemon_*.toml"))
    return backups[-2] if len(backups) >= 2 else (backups[-1] if backups else None)


def rollback_daemon() -> bool:
    """이전 daemon.toml 백업으로 복구 + daemon 재시작."""
    backup = get_latest_backup()
    if not backup:
        print("[improve] 롤백 실패: 백업 없음")
        return False

    daemon_toml = ROOT / "config" / "daemon.toml"
    shutil.copy2(backup, daemon_toml)
    print(f"[improve] 롤백: {backup.name} → daemon.toml")

    # daemon 재시작
    import subprocess, signal
    try:
        result = subprocess.run(["pgrep", "-f", "crypto_trader.cli"], capture_output=True, text=True)
        for pid in result.stdout.strip().splitlines():
            try:
                os.kill(int(pid), signal.SIGTERM)
            except Exception:
                pass
        time.sleep(3)
    except Exception:
        pass

    venv_python = ROOT / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else "python3"
    log_path = ROOT / "artifacts" / "daemon.log"
    subprocess.Popen(
        [python, "-m", "crypto_trader.cli", "run-multi", "--config", str(daemon_toml)],
        stdout=open(log_path, "a"), stderr=subprocess.STDOUT,
        cwd=ROOT, start_new_session=True,
    )
    return True


# ── 알림 ─────────────────────────────────────────────────────────────────────

def notify(msg: str) -> None:
    full = f"[improvement-loop] {msg}"
    print(f"\n{'='*55}\n🔔 {full}\n{'='*55}\n")

    token  = os.environ.get("CT_TELEGRAM_BOT_TOKEN", "")
    chat   = os.environ.get("CT_TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        return
    try:
        payload = json.dumps({"chat_id": chat, "text": full}).encode()
        req = request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[improve] 텔레그램 실패: {e}")


# ── 연구 파이프라인 리셋 ──────────────────────────────────────────────────────

def reset_research_pipeline() -> None:
    """strategy_research_loop의 done 목록 초기화 → 다음 사이클에 재실행."""
    if not RESEARCH_STATE.exists():
        return
    try:
        state = json.loads(RESEARCH_STATE.read_text())
        state["done"] = []
        RESEARCH_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        print("[improve] 연구 파이프라인 리셋 완료 — 다음 사이클부터 재실행")
    except Exception as e:
        print(f"[improve] 파이프라인 리셋 실패: {e}")


def is_pipeline_exhausted() -> bool:
    """strategy_research_loop의 모든 태스크가 완료됐는지 확인."""
    if not RESEARCH_STATE.exists():
        return False
    try:
        state = json.loads(RESEARCH_STATE.read_text())
        done = set(state.get("done", []))
        # PIPELINE 태스크 ID 목록 (strategy_research_loop.py와 동기화)
        pipeline_ids = {
            "stealth_sol_sweep", "truth_seeker_sweep", "vpin_eth_grid",
            "momentum_sol_grid", "regime_stealth", "alpha_backtest",
            "strategy_tournament", "new_strategy_hypothesis",
        }
        return pipeline_ids.issubset(done)
    except Exception:
        return False


# ── 주기 리포트 ───────────────────────────────────────────────────────────────

def send_periodic_report(state: dict) -> None:
    pnl_48h = get_recent_pnl(hours=48)
    pnl_7d  = get_recent_pnl(hours=168)

    # market_scan 최신 신호
    scan_signal = ""
    prebull_path = ROOT / "artifacts" / "pre-bull-signals.json"
    if prebull_path.exists():
        try:
            data = json.loads(prebull_path.read_text())
            latest = data.get("latest", {})
            score = latest.get("pre_bull_score_adj", 0)
            regime = "BULL" if latest.get("btc_bull_regime") else "BEAR"
            stealth = latest.get("stealth_acc_count", 0)
            scan_signal = f"Pre-Bull {score:+.3f} | BTC {regime} | Stealth {stealth}/50"
        except Exception:
            pass

    changes = get_latest_wallet_change()
    last_change = f"{changes['type']} → {changes['wallet']}" if changes else "없음"

    msg = (
        f"📊 주기 리포트 (Cycle {state['cycle']})\n"
        f"48h PnL: ₩{pnl_48h['total_pnl']:+,.0f} | {pnl_48h['trades']}건 | WR {pnl_48h['win_rate']:.0f}%\n"
        f"7d  PnL: ₩{pnl_7d['total_pnl']:+,.0f} | {pnl_7d['trades']}건\n"
        f"시장: {scan_signal}\n"
        f"마지막 변경: {last_change}\n"
        f"롤백 횟수: {state['rollback_count']}회"
    )
    notify(msg)


# ── 메인 사이클 ───────────────────────────────────────────────────────────────

def run_cycle(state: dict) -> dict:
    state["cycle"] += 1
    cycle = state["cycle"]
    now = datetime.now(timezone.utc)
    print(f"\n[improve] === Cycle {cycle} ({now.strftime('%Y-%m-%d %H:%M UTC')}) ===")

    # 1. 최근 파라미터 변경 감지
    latest_change = get_latest_wallet_change()
    if latest_change:
        change_ts = latest_change.get("ts")
        if change_ts != state.get("last_change_ts"):
            # 새 변경 발생 → 모니터링 시작
            state["last_change_ts"] = change_ts
            state["last_change_type"] = latest_change.get("type")
            state["monitoring"] = True
            state["baseline_pnl"] = get_recent_pnl(hours=1)["total_pnl"]
            print(f"[improve] 새 변경 감지: {latest_change.get('type')} / {latest_change.get('wallet')}")
            print(f"[improve] 모니터링 시작 — {MONITOR_HOURS}h 관측 예정")

    # 2. 성과 모니터링 + 롤백 판단
    if state.get("monitoring") and state.get("last_change_ts"):
        change_time = datetime.fromisoformat(state["last_change_ts"])
        elapsed_hours = (now - change_time).total_seconds() / 3600

        if elapsed_hours >= MONITOR_HOURS:
            # 관측 기간 종료 → 성과 평가
            pnl = get_recent_pnl(since_ts=state["last_change_ts"])
            print(f"[improve] {MONITOR_HOURS}h 관측 완료: PnL={pnl['total_pnl']:+,.0f} trades={pnl['trades']}")

            if pnl["trades"] > 0 and pnl["pnl_pct"] < ROLLBACK_THRESHOLD * 100:
                # 성과 악화 → 롤백
                print(f"[improve] 성과 악화 ({pnl['pnl_pct']:+.2f}%) → 롤백")
                success = rollback_daemon()
                if success:
                    state["rollback_count"] += 1
                    notify(
                        f"⚠️ 롤백 실행!\n"
                        f"변경({state['last_change_type']}) 후 {MONITOR_HOURS}h PnL: {pnl['pnl_pct']:+.2f}%\n"
                        f"이전 설정으로 복구 완료."
                    )
            elif pnl["trades"] > 0:
                notify(
                    f"✅ 파라미터 변경 성과 확인\n"
                    f"{MONITOR_HOURS}h PnL: ₩{pnl['total_pnl']:+,.0f} ({pnl['pnl_pct']:+.2f}%)\n"
                    f"거래: {pnl['trades']}건 WR {pnl['win_rate']:.0f}%"
                )
            else:
                print(f"[improve] {MONITOR_HOURS}h 내 거래 없음 — 시장 조건 대기 중")

            state["monitoring"] = False

    # 3. 연구 파이프라인 완료 시 리셋
    if is_pipeline_exhausted():
        print("[improve] 연구 파이프라인 소진 → 리셋")
        reset_research_pipeline()
        notify("🔄 연구 파이프라인 리셋 — 전략 재탐색 시작")

    # 4. 주기 리포트 (24h마다)
    if cycle - state.get("last_report_cycle", 0) >= REPORT_INTERVAL_CYCLES:
        send_periodic_report(state)
        state["last_report_cycle"] = cycle

    save_state(state)
    return state


# ── 엔트리포인트 ──────────────────────────────────────────────────────────────

def main() -> None:
    print("♾️  Improvement Loop 시작 — 자율 개선 주기 가동")
    print(f"   주기: {CYCLE_HOURS}h | 모니터링: {MONITOR_HOURS}h | 롤백 임계값: {ROLLBACK_THRESHOLD*100:.0f}%")

    state = load_state()
    notify(f"Improvement Loop 시작 (Cycle {state['cycle']+1}~)")

    while True:
        try:
            state = run_cycle(state)
        except Exception as e:
            print(f"[improve] 사이클 오류: {e}")

        print(f"[improve] 다음 사이클까지 {CYCLE_HOURS}h 대기...")
        time.sleep(CYCLE_HOURS * 3600)


if __name__ == "__main__":
    main()
