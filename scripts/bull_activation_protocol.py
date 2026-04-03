"""
BULL 레짐 전환 프로토콜 — 자동화 스크립트 (사이클 83→86 업데이트)

목적:
  - BTC BULL 레짐 전환 시 pre-staged wallet 활성화 계획 출력
  - XRP/TRX(이중통과★) → ETH/SOL(조건부) 순서로 단계적 paper → live 활성화 가이드
  - --apply 플래그 없이는 dry-run (실제 변경 없음)

사용법:
  .venv/bin/python scripts/bull_activation_protocol.py          # 현재 상태 + 계획
  .venv/bin/python scripts/bull_activation_protocol.py --apply  # daemon.toml 실제 업데이트

Pre-staged 파라미터 (백테스트 확정 — 사이클 84~85):
  XRP: lb=8,  adx=25, vol=2.0, TP=12%, SL=4%  ← C8, WF+슬라이딩 3/3 이중 통과★
  TRX: lb=12, adx=25, vol=2.0, TP=12%, SL=3%  ← WF+슬라이딩 3/3 이중 통과★ (사이클 84~85 확정)
  ETH: lb=12, adx=25, vol=2.0, TP=10%, SL=3%  ← C0_base, 슬라이딩 2/3 통과 (조건부)
  SOL: lb=12, adx=25, vol=2.0, TP=12%, SL=4%  ← 슬라이딩 2/3 통과 (조건부, W3 T=4 데이터 부족)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    import pyupbit  # type: ignore
    _PYUPBIT_OK = True
except ImportError:
    _PYUPBIT_OK = False

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

STATE_FILE  = ROOT / "state" / "market_scan.state.json"
DAEMON_TOML = ROOT / "config" / "daemon.toml"

RECENT_WINDOW = 10  # market_scan_loop.py 와 동일

# ── 활성화 임계값 ────────────────────────────────────────────────────────────
BULL_THRESHOLD_PRE_BULL = 0.60   # pre_bull_score_adj 기준 (secondary)
# primary: btc_bull_regime = True

# ── Pre-staged wallet 정의 (확정 등급 순 — 사이클 86 업데이트) ───────────────
# Phase 1~2: 이중 통과★ (WF + 슬라이딩 3/3) — BULL 전환 즉시 활성화
# Phase 3~4: 조건부 (슬라이딩 2/3) — 이중통과 심볼 안정 확인 후 활성화
STAGED_WALLETS = [
    {
        "name":        "momentum_xrp_wallet",
        "symbol":      "KRW-XRP",
        "phase":       1,
        "status":      "disabled",       # PRE-STAGED (주석처리)
        "action":      "enable_paper",   # BULL 시 주석 해제 + paper 활성화
        "params":      "lb=8, adx=25, vol=2.0, TP=12%, SL=4%",
        "validation":  "C8 WF ✅ | sliding 3/3 ✅★ (이중 통과 확정)",
        "capital_krw": 800_000,
    },
    {
        "name":        "momentum_trx_wallet",
        "symbol":      "KRW-TRX",
        "phase":       2,
        "status":      "disabled",       # PRE-STAGED (주석처리)
        "action":      "enable_paper",   # BULL 시 주석 해제 + paper 활성화
        "params":      "lb=12, adx=25, vol=2.0, TP=12%, SL=3%",
        "validation":  "WF ✅ | sliding 3/3 ✅★ (이중 통과 확정 — 사이클 84~85)",
        "capital_krw": 800_000,
    },
    {
        "name":        "momentum_eth_wallet",
        "symbol":      "KRW-ETH",
        "phase":       3,
        "status":      "disabled",       # DISABLED (주석처리)
        "action":      "enable_paper",   # 이중통과 심볼 24h 안정 후 활성화
        "params":      "lb=12, adx=25, vol=2.0, TP=10%, SL=3%",
        "validation":  "C0_base WF ✅ | sliding 2/3 ✅ (조건부 확정)",
        "capital_krw": 1_000_000,
    },
    {
        "name":        "momentum_sol_wallet",
        "symbol":      "KRW-SOL",
        "phase":       4,
        "status":      "paper_active",   # 이미 paper 실행 중
        "action":      "live_switch",    # 이중통과 심볼 48h 안정 후 live 전환 검토
        "params":      "lb=12, adx=25, vol=2.0, TP=12%, SL=4%",
        "validation":  "WF ✅ | sliding 2/3 ✅ (조건부 — W3 T=4 데이터 부족)",
        "capital_krw": 1_200_000,
    },
]


def fetch_btc_regime() -> dict:
    """BTC 일봉 기반 레짐 실시간 계산 (SMA20 기준)."""
    if not _PYUPBIT_OK:
        return {"btc_bull_regime": False, "btc_raw_ret": 0.0, "btc_acc": 0.0,
                "btc_cvd_slope": 0.0, "error": "pyupbit not available"}
    try:
        df = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=60)
        if df is None or len(df) < 22:
            return {"btc_bull_regime": False, "error": "데이터 부족"}
        c = df["close"].values
        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
        v = df["volume"].values

        raw_ret   = float(c[-1]) / max(float(c[0]), 1e-9) - 1.0
        rng       = np.clip(h - l, 1e-9, None)
        vpin      = np.abs(c - o) / rng
        acc       = vpin[-RECENT_WINDOW:].mean() / max(vpin[:-RECENT_WINDOW].mean(), 1e-9)
        direction = np.where(c >= o, 1.0, -1.0)
        cvd       = np.cumsum(v * direction)
        cvd_slope = (cvd[-1] - cvd[-RECENT_WINDOW]) / max(v.mean(), 1e-9)
        btc_bull  = bool(len(c) >= 20 and c[-1] > c[-20:].mean())

        return {
            "btc_bull_regime": btc_bull,
            "btc_raw_ret":     round(raw_ret, 4),
            "btc_acc":         round(float(acc), 4),
            "btc_cvd_slope":   round(float(cvd_slope), 4),
        }
    except Exception as e:
        return {"btc_bull_regime": False, "error": str(e)}


def read_latest_state() -> dict:
    """BTC 레짐 실시간 계산 + state 파일 fallback."""
    return fetch_btc_regime()


def check_bull_conditions(state: dict) -> tuple[bool, list[str]]:
    """BULL 전환 조건 체크. (is_bull, reasons) 반환."""
    reasons = []
    is_bull = False

    btc_bull = state.get("btc_bull_regime", False)
    pre_bull_adj = state.get("pre_bull_score_adj", 0.0)
    pre_bull_raw = state.get("pre_bull_score", 0.0)
    stealth_count = state.get("stealth_acc_count", 0)
    total_coins = state.get("total_coins_scanned", 1)
    ret = state.get("btc_raw_ret", 0.0)
    acc = state.get("btc_acc", 0.0)
    cvd = state.get("btc_cvd_slope", 0.0)

    if btc_bull:
        reasons.append(f"  ✅ BTC BULL 레짐 활성 (primary gate 통과)")
        is_bull = True
    else:
        reasons.append(f"  ❌ BTC BEAR 레짐 — primary gate 미통과 (SMA20 이탈)")

    if pre_bull_adj >= BULL_THRESHOLD_PRE_BULL:
        reasons.append(f"  ✅ pre_bull_score_adj = {pre_bull_adj:+.3f} (≥ {BULL_THRESHOLD_PRE_BULL})")
    else:
        reasons.append(f"  ⚠️  pre_bull_score_adj = {pre_bull_adj:+.3f} (< {BULL_THRESHOLD_PRE_BULL}, secondary 미충족)")

    reasons.append(f"  📊 BTC 시그널: ret={ret:+.4f} | acc={acc:.3f} | cvd={cvd:+.3f}")
    reasons.append(f"  🔍 Stealth: {stealth_count}/{total_coins} 코인 acc 양전")

    return is_bull, reasons


def print_activation_plan(is_bull: bool, state: dict) -> None:
    """단계적 활성화 계획 출력."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*70}")
    print(f"  BULL 레짐 전환 프로토콜 — {now}")
    print(f"{'='*70}")

    is_bull_str = "🟢 BULL" if is_bull else "🔴 BEAR"
    print(f"\n  현재 BTC 레짐: {is_bull_str}")

    pre_bull_adj = state.get("pre_bull_score_adj", None)
    if pre_bull_adj is not None:
        print(f"  pre_bull_score_adj: {pre_bull_adj:+.3f} (임계값: {BULL_THRESHOLD_PRE_BULL})")

    print(f"\n{'─'*70}")
    print(f"  Pre-staged Wallet 활성화 계획")
    print(f"{'─'*70}")

    for w in STAGED_WALLETS:
        phase_str = f"Phase {w['phase']}"
        status = w["status"]
        action = w["action"]

        if is_bull:
            if action == "live_switch":
                action_str = "▶️  [BULL 활성] paper → live 전환 검토"
            else:
                action_str = "▶️  [BULL 활성] 주석 해제 + paper 활성화"
        else:
            action_str = "⏸️  [BEAR 대기] 비활성 유지"

        print(f"\n  [{phase_str}] {w['name']}")
        print(f"    심볼: {w['symbol']}")
        print(f"    현황: {status}")
        print(f"    파라미터: {w['params']}")
        print(f"    검증: {w['validation']}")
        print(f"    자본: ₩{w['capital_krw']:,}")
        print(f"    → {action_str}")

    print(f"\n{'─'*70}")

    if is_bull:
        print("\n  🚀 BULL 레짐 감지 — 단계적 활성화 실행 가이드:")
        print()
        print("  ── Phase 1 (이중통과★ 즉시 활성화) ──")
        print("  1. XRP (Phase 1) — daemon.toml 주석 해제")
        print("     # name = \"momentum_xrp_wallet\" → name = \"momentum_xrp_wallet\"")
        print("     lb=8, adx=25, vol_mult=2.0, tp=0.12, sl=0.04")
        print()
        print("  2. TRX (Phase 2) — daemon.toml 주석 해제")
        print("     # name = \"momentum_trx_wallet\" → name = \"momentum_trx_wallet\"")
        print("     lb=12, adx=25, vol_mult=2.0, tp=0.12, sl=0.03")
        print()
        print("  ── Phase 2 (조건부 — 이중통과 심볼 24h 모니터링 후) ──")
        print("  3. ETH (Phase 3) — daemon.toml 주석 해제")
        print("     # name = \"momentum_eth_wallet\" → name = \"momentum_eth_wallet\"")
        print("     lb=12, adx=25, vol_mult=2.0, tp=0.10, sl=0.03")
        print()
        print("  4. SOL (Phase 4) — 이미 paper 실행 중")
        print("     daemon.toml: momentum_sol_wallet 섹션 확인")
        print("     lb=12, adx=25, vol_mult=2.0, tp=0.12, sl=0.04")
        print("     → 48h paper 모니터링 후 live 전환 검토")
        print()
        print("  ⚠️  주의:")
        print("     - XRP/TRX 이중통과★ → 즉시 paper 활성화 우선")
        print("     - ETH/SOL 조건부 → XRP/TRX 24h 이상 안정 확인 후 순차 활성화")
        print("     - SOL W3 슬라이딩 T=4 (데이터 부족) — 4월 데이터 충족 후 재검증 예정")
        print("     - --apply 플래그로 XRP/TRX/ETH daemon.toml 자동 업데이트 가능")
    else:
        pre_bull_adj = state.get("pre_bull_score_adj", 0.0)
        gap = BULL_THRESHOLD_PRE_BULL - pre_bull_adj
        print(f"\n  ⏳ BEAR 레짐 유지 — BULL 전환 대기 중")
        print(f"     pre_bull_score_adj: {pre_bull_adj:+.3f} (임계값 {BULL_THRESHOLD_PRE_BULL} 까지 {gap:+.3f})")
        print(f"     btc_bull_regime = True 가 primary 전환 트리거")
        print(f"     현재 모든 momentum wallet paper 대기 상태 유지")

    print(f"\n{'='*70}\n")


def apply_bull_activation(dry_run: bool = True) -> None:
    """XRP/TRX/ETH wallet 주석 해제 (--apply 시). SOL은 이미 paper 실행 중."""
    if dry_run:
        print("  [DRY-RUN] --apply 없이 실행 중 — 변경 없음")
        return

    toml_text = DAEMON_TOML.read_text()
    changes = []

    # XRP 활성화 (주석 해제) — Phase 1 이중통과★
    xrp_disabled = "# name = \"momentum_xrp_wallet\""
    xrp_enabled  = "name = \"momentum_xrp_wallet\""
    if xrp_disabled in toml_text:
        toml_text = toml_text.replace(xrp_disabled, xrp_enabled, 1)
        changes.append("momentum_xrp_wallet 활성화")

    # TRX 활성화 (주석 해제) — Phase 2 이중통과★
    trx_disabled = "# name = \"momentum_trx_wallet\""
    trx_enabled  = "name = \"momentum_trx_wallet\""
    if trx_disabled in toml_text:
        toml_text = toml_text.replace(trx_disabled, trx_enabled, 1)
        changes.append("momentum_trx_wallet 활성화")

    # ETH 활성화 (주석 해제) — Phase 3 조건부
    eth_disabled = "# name = \"momentum_eth_wallet\""
    eth_enabled  = "name = \"momentum_eth_wallet\""
    if eth_disabled in toml_text:
        toml_text = toml_text.replace(eth_disabled, eth_enabled, 1)
        changes.append("momentum_eth_wallet 활성화")

    if changes:
        DAEMON_TOML.write_text(toml_text)
        print(f"  ✅ daemon.toml 업데이트: {', '.join(changes)}")
    else:
        print("  ℹ️  변경 사항 없음 (이미 활성화 상태 또는 섹션 없음)")


def main() -> None:
    apply = "--apply" in sys.argv

    state = read_latest_state()
    is_bull, condition_reasons = check_bull_conditions(state)

    print("\n  BTC 레짐 전환 조건 체크:")
    for r in condition_reasons:
        print(r)

    print_activation_plan(is_bull, state)

    if apply:
        if is_bull:
            print("  [--apply] BULL 레짐 확인 — daemon.toml XRP/TRX/ETH 활성화 실행")
            apply_bull_activation(dry_run=False)
        else:
            print("  [--apply] BEAR 레짐 — BULL 전환 후 재실행 필요")
    else:
        print("  팁: BULL 전환 시 --apply 플래그로 XRP/TRX/ETH 자동 활성화 가능")


if __name__ == "__main__":
    main()
