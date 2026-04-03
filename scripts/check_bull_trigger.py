#!/usr/bin/env python3
"""
사이클 127: BTC BULL 전환 조건 실시간 감지 스크립트

트리거 조건 (3개 모두 충족 시 BULL 전환):
  1. pre_bull_score_adj >= PRE_BULL_THRESHOLD (default 0.90)
  2. btc_bull_regime   = BTC 종가 > SMA20 (4시간봉)
  3. btc_30bar_pos     = BTC 종가 > 30봉 전 종가

사용법:
  .venv/bin/python scripts/check_bull_trigger.py
  .venv/bin/python scripts/check_bull_trigger.py --threshold 0.85   # 임계값 변경
  .venv/bin/python scripts/check_bull_trigger.py --watch 300        # 300초마다 반복 감시

설계 원칙:
  - CPU only (GPU 불필요)
  - 전체 시장 스캔: KRW 마켓 전체 조회로 pre_bull_score 계산
  - BTC 단독 계산: btc_bull_regime + btc_30bar_pos
  - 완료 후 EXIT_CODE=0(미달성)/1(트리거 충족)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

try:
    import pyupbit
except ImportError:
    print("[ERROR] pyupbit not installed. Run: pip install pyupbit")
    sys.exit(2)

# ── 설정 ───────────────────────────────────────────────────────────────────────
INTERVAL = "minute240"  # 4시간봉 (market_scan_loop.py와 동일)
COUNT    = 180          # ~30일치
RECENT_WINDOW = 36      # Acc 계산 윈도우 (market_scan_loop.py와 동일)
FETCH_WORKERS = 8

DEFAULT_THRESHOLD = 0.90

# ONDO vpin Gate2 활성화 대기 심볼 (BULL 전환 시 우선 활성화)
STAGED_SYMBOLS = ["KRW-ONDO", "KRW-SOL", "KRW-ETH", "KRW-XRP"]


def fetch_one(symbol: str) -> tuple[str, np.ndarray | None]:
    """단일 심볼 종가 배열 반환."""
    try:
        df = pyupbit.get_ohlcv(symbol, interval=INTERVAL, count=COUNT)
        if df is None or len(df) < 50:
            return symbol, None
        # (close, open, volume) 반환
        return symbol, df[["close", "open", "volume"]].values
    except Exception:
        return symbol, None


def compute_pre_bull_score(symbols: list[str], btc_arr: np.ndarray) -> dict:
    """
    전체 마켓 pre_bull_score 계산 (CPU).

    pre_bull_score = pct_pos_acc + pct_pos_cvd + pct_weak_rs - 1.0
    범위: [-1.0, +2.0] | 강한 불장 전조 = +1.0 이상

    RS < 1.0: 알트 수익률이 BTC 수익률보다 낮음 (BTC 대비 약세, stealth 전조)
    """
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures = {ex.submit(fetch_one, s): s for s in symbols}
        results = {}
        for f in as_completed(futures):
            sym, arr = f.result()
            if arr is not None:
                results[sym] = arr

    if not results:
        return {"error": "no data"}

    n_pos_acc = n_pos_cvd = n_weak_rs = 0
    # BTC 정규화 수익률 (첫 봉 대비 마지막 봉)
    btc_closes = btc_arr[:, 0].astype(float)
    btc_norm = float(btc_closes[-1]) / max(float(btc_closes[0]), 1e-9)
    total = 0

    for sym, arr in results.items():
        closes = arr[:, 0].astype(float)
        opens  = arr[:, 1].astype(float)
        vols   = arr[:, 2].astype(float)

        if len(closes) < RECENT_WINDOW + 10:
            continue
        total += 1

        # Relative Strength vs BTC (market_scan_loop.py와 동일 로직)
        sym_norm = float(closes[-1]) / max(float(closes[0]), 1e-9)
        rs = sym_norm / max(btc_norm, 1e-9)
        if rs < 1.0:
            n_weak_rs += 1

        # Accumulation (VPIN proxy)
        rngs = np.clip(arr[:, 0] - arr[:, 0], 1e-9, None)  # placeholder
        # 실제: close-open 비율
        price_range = np.abs(closes - opens).clip(1e-9)
        vpin = price_range / price_range.clip(1e-9)  # all 1.0 → 단순화
        # 올바른 acc: 최근 RECENT_WINDOW 봉 vpin 평균 / 이전 평균
        recent_vpin = np.abs(closes[-RECENT_WINDOW:] - opens[-RECENT_WINDOW:])
        hist_vpin   = np.abs(closes[:-RECENT_WINDOW] - opens[:-RECENT_WINDOW])
        acc = recent_vpin.mean() / max(hist_vpin.mean(), 1e-9)
        if acc > 1.0:
            n_pos_acc += 1

        # CVD slope
        direction = np.where(closes >= opens, 1.0, -1.0)
        cvd = np.cumsum(vols * direction)
        cvd_slope = (cvd[-1] - cvd[-RECENT_WINDOW]) / max(vols.mean(), 1e-9)
        if cvd_slope > 0:
            n_pos_cvd += 1

    if total == 0:
        return {"error": "insufficient data"}

    pct_pos_acc = round(n_pos_acc / total, 3)
    pct_pos_cvd = round(n_pos_cvd / total, 3)
    pct_weak_rs = round(n_weak_rs / total, 3)
    score = round(pct_pos_acc + pct_pos_cvd + pct_weak_rs - 1.0, 3)

    return {
        "pre_bull_score": score,
        "pct_pos_acc": pct_pos_acc,
        "pct_pos_cvd": pct_pos_cvd,
        "pct_weak_rs": pct_weak_rs,
        "total_scanned": total,
    }


def compute_btc_regime(btc_df) -> dict:
    """BTC regime 계산: btc_bull_regime + btc_30bar_pos."""
    closes = btc_df["close"].values.astype(float)
    opens  = btc_df["open"].values.astype(float)
    vols   = btc_df["volume"].values.astype(float)

    # BTC > SMA20
    btc_bull = bool(len(closes) >= 20 and closes[-1] > closes[-20:].mean())

    # BTC > 30봉 전
    btc_30bar = bool(len(closes) >= 31 and closes[-1] > closes[-31])

    # 30봉 수익률
    ret_30bar = float(closes[-1] / max(closes[-31], 1e-9) - 1.0) if len(closes) >= 31 else 0.0

    # 10봉 수익률
    ret_10bar = float(closes[-1] / max(closes[-11], 1e-9) - 1.0) if len(closes) >= 11 else 0.0

    # BTC Acc
    recent_vpin = np.abs(closes[-RECENT_WINDOW:] - opens[-RECENT_WINDOW:])
    hist_vpin   = np.abs(closes[:-RECENT_WINDOW] - opens[:-RECENT_WINDOW])
    acc = float(recent_vpin.mean() / max(hist_vpin.mean(), 1e-9))

    # CVD slope
    direction = np.where(closes >= opens, 1.0, -1.0)
    cvd = np.cumsum(vols * direction)
    cvd_slope = float((cvd[-1] - cvd[-RECENT_WINDOW]) / max(vols.mean(), 1e-9))

    return {
        "btc_price":       round(float(closes[-1]), 0),
        "btc_sma20":       round(float(closes[-20:].mean()), 0),
        "btc_bull_regime": btc_bull,
        "btc_30bar_pos":   btc_30bar,
        "btc_ret_30bar":   round(ret_30bar, 4),
        "btc_ret_10bar":   round(ret_10bar, 4),
        "btc_acc":         round(acc, 4),
        "btc_cvd_slope":   round(cvd_slope, 4),
    }


def _fetch_macro_bonus() -> float:
    """macro-intelligence 서버에서 macro_bonus 조회 (실패 시 0.0)."""
    try:
        from urllib.request import urlopen
        with urlopen("http://127.0.0.1:8000/regime/current", timeout=3) as resp:
            payload = json.loads(resp.read())
        confidence = float(payload.get("overall_confidence", 0.0))
        if confidence < 0.3:
            return 0.0
        bonus = 0.0
        us_signals = payload["layers"]["us"]["signals"]
        if "falling" in str(us_signals.get("vix_trend", "")).lower():
            bonus += 0.2
        if "falling" in str(us_signals.get("dxy_trend", "")).lower():
            bonus += 0.1
        if payload.get("overall_regime") == "expansionary":
            bonus += 0.3
        return round(bonus, 3)
    except Exception:
        return 0.0


def run_check(threshold: float) -> dict:
    """한 번 체크 실행. 결과 dict 반환."""
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n[{ts}] BTC BULL 전환 조건 체크 (임계값: pre_bull_adj >= {threshold})")

    # BTC 데이터
    print("  BTC 데이터 조회 중...")
    btc_df = pyupbit.get_ohlcv("KRW-BTC", interval=INTERVAL, count=COUNT)
    if btc_df is None or len(btc_df) < 50:
        print("[ERROR] BTC 데이터 조회 실패")
        return {"triggered": False, "error": "btc_data_fail"}

    btc = compute_btc_regime(btc_df)
    btc_close = float(btc_df["close"].iloc[-1])

    # 전체 마켓 조회
    print("  전체 마켓 스캔 중 (CPU)...")
    symbols = [s for s in pyupbit.get_tickers(fiat="KRW") if s != "KRW-BTC"]
    btc_arr = btc_df[["close", "open", "volume"]].values
    pb = compute_pre_bull_score(symbols, btc_arr)

    macro_bonus = _fetch_macro_bonus()
    pre_bull_adj = round(pb.get("pre_bull_score", 0.0) + macro_bonus, 3)

    # 조건 판정
    cond_prebull = pre_bull_adj >= threshold
    cond_sma20   = btc["btc_bull_regime"]
    cond_30bar   = btc["btc_30bar_pos"]
    triggered    = cond_prebull and cond_sma20 and cond_30bar

    # 출력
    print(f"\n  ─── BTC 레짐 ───────────────────────────────")
    print(f"  BTC 가격:       {btc['btc_price']:,.0f} KRW")
    print(f"  BTC SMA20:      {btc['btc_sma20']:,.0f} KRW")
    print(f"  BTC>SMA20:      {'✅ YES' if cond_sma20 else '❌ NO'}")
    print(f"  BTC>30봉전:     {'✅ YES' if cond_30bar else '❌ NO'}  (ret={btc['btc_ret_30bar']:+.1%})")
    print(f"  BTC 10봉 수익:  {btc['btc_ret_10bar']:+.1%}")
    print(f"  BTC Acc:        {btc['btc_acc']:.3f}  (>1.0 = 매집)")
    print(f"  BTC CVD slope:  {btc['btc_cvd_slope']:+.1f}")

    print(f"\n  ─── Pre-Bull Score ─────────────────────────")
    print(f"  pct_pos_acc:    {pb.get('pct_pos_acc', 0):.1%}")
    print(f"  pct_pos_cvd:    {pb.get('pct_pos_cvd', 0):.1%}")
    print(f"  pct_weak_rs:    {pb.get('pct_weak_rs', 0):.1%}")
    print(f"  pre_bull_score: {pb.get('pre_bull_score', 0):.3f}")
    print(f"  macro_bonus:    +{macro_bonus:.3f}")
    print(f"  pre_bull_adj:   {pre_bull_adj:.3f}  (임계={threshold})")
    print(f"  스캔 심볼:      {pb.get('total_scanned', 0)}개")
    print(f"  pre_bull>=임계: {'✅ YES' if cond_prebull else '❌ NO'}")

    print(f"\n  ─── 판정 ────────────────────────────────────")
    if triggered:
        print(f"  🚀 BULL 전환 트리거 충족! 3/3 조건 통과")
        print(f"     활성화 대상: {', '.join(STAGED_SYMBOLS)}")
        print(f"     → bull_activation_protocol.py --apply 실행 검토")
    else:
        passed = sum([cond_prebull, cond_sma20, cond_30bar])
        print(f"  ⏳ 미충족 ({passed}/3) — BULL 전환 대기 중")
        if not cond_prebull:
            gap = threshold - pre_bull_adj
            print(f"     pre_bull_adj 부족: {pre_bull_adj:.3f} / 목표 {threshold} (갭 {gap:.3f})")
        if not cond_sma20:
            gap_pct = (btc['btc_sma20'] - btc['btc_price']) / btc['btc_sma20']
            print(f"     BTC SMA20 미달: {gap_pct:.1%} 더 올라야 함")
        if not cond_30bar:
            print(f"     BTC 30봉 수익률 음수: {btc['btc_ret_30bar']:+.1%}")

    return {
        "triggered":       triggered,
        "pre_bull_adj":    pre_bull_adj,
        "pre_bull_score":  pb.get("pre_bull_score", 0),
        "macro_bonus":     macro_bonus,
        "btc_bull_regime": cond_sma20,
        "btc_30bar_pos":   cond_30bar,
        "btc_price":       btc["btc_price"],
        "btc_ret_30bar":   btc["btc_ret_30bar"],
        "conditions_met":  sum([cond_prebull, cond_sma20, cond_30bar]),
        "timestamp":       ts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC BULL 전환 조건 실시간 감지")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"pre_bull_adj 임계값 (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--watch", type=int, default=0,
                        help="반복 감시 간격(초). 0=단회 실행 (default: 0)")
    args = parser.parse_args()

    if args.watch > 0:
        print(f"[WATCH MODE] {args.watch}초마다 반복. Ctrl+C로 종료.")
        try:
            while True:
                result = run_check(args.threshold)
                if result.get("triggered"):
                    print("\n🚀 TRIGGERED! 종료합니다.")
                    sys.exit(1)  # exit code 1 = triggered
                print(f"  다음 체크: {args.watch}초 후...")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n중단됨.")
            sys.exit(0)
    else:
        result = run_check(args.threshold)
        sys.exit(1 if result.get("triggered") else 0)


if __name__ == "__main__":
    main()
