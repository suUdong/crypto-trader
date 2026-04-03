#!/usr/bin/env python3
"""
N=12 + btc_trend_pos Walk-Forward 검증 (사이클 95)

목적:
  사이클 94에서 최우수로 확인된 N=12 + btc_trend_pos 필터가
  OOS(Out-Of-Sample)에서도 유효한지 검증.

방법:
  슬라이딩 윈도우 Walk-Forward
  - 윈도우: IS=24개월, OOS=6개월, 슬라이드=6개월
  - 분할: 2022-01 ~ 2025-10 커버 (7개 OOS 구간)

비교 대상:
  A) N=12 단독 (사이클93 기준선)
  B) N=12 + btc_trend_pos (사이클94 최우수)

Usage:
    .venv/bin/python3 scripts/backtest_n12_trend_walkforward.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))

from historical_loader import load_historical  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────
CTYPE = "240m"
FULL_START = "2022-01-01"
FULL_END   = "2026-04-03"

SMA_WINDOW = 20
LOOKBACK   = 12
RECENT_W   = 4
TREND_W    = 10
VOL_SHORT  = 20
VOL_LONG   = 40

ALT_SYMBOLS = ["KRW-SOL", "KRW-ETH", "KRW-XRP", "KRW-TRX"]
TP_SL = {
    "KRW-SOL": (0.12, 0.04),
    "KRW-ETH": (0.10, 0.03),
    "KRW-XRP": (0.12, 0.04),
    "KRW-TRX": (0.12, 0.03),
}
FORWARD_BARS = 24  # 최대 보유봉 (96h)

# Walk-Forward 파라미터
IS_MONTHS  = 24   # In-Sample 기간 (개월)
OOS_MONTHS = 6    # Out-Of-Sample 기간 (개월)
SLIDE_MONTHS = 6  # 슬라이드 간격


# ── Macro Proxy ───────────────────────────────────────────────────────────────

def compute_macro_proxy(btc: pd.DataFrame) -> pd.DataFrame:
    close = btc["close"]
    log_ret = np.log(close / close.shift(1))

    vol_short = log_ret.rolling(VOL_SHORT).std()
    vol_long  = log_ret.rolling(VOL_LONG).std()
    btc["vix_falling"]   = (vol_short < vol_long).astype(float)

    trend_ret = close / close.shift(TREND_W) - 1.0
    btc["btc_trend_pos"] = (trend_ret > 0).astype(float)
    return btc


# ── Stealth Signal ────────────────────────────────────────────────────────────

def compute_alt_stealth(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    btc_idx: int,
    lb: int = LOOKBACK,
    rw: int = RECENT_W,
    rs_window: int = 20,
) -> bool:
    if btc_idx < max(lb + rw, rs_window):
        return False
    btc_ts = btc_df.index[btc_idx]
    if btc_ts not in alt_df.index:
        return False
    alt_idx = alt_df.index.get_loc(btc_ts)
    if not isinstance(alt_idx, int):
        alt_idx = int(alt_idx)
    if alt_idx < max(lb + rw, rs_window):
        return False

    win     = alt_df.iloc[alt_idx - lb: alt_idx]
    btc_win = btc_df.iloc[btc_idx - lb: btc_idx]
    if len(win) < lb or len(btc_win) < lb:
        return False

    c  = win["close"].values
    o  = win["open"].values
    h  = win["high"].values
    lv = win["low"].values
    v  = win["volume"].values

    raw_ret  = float(c[-1]) / max(float(c[0]), 1e-9) - 1.0
    rng      = np.clip(h - lv, 1e-9, None)
    vpin     = np.abs(c - o) / rng
    acc      = vpin[-rw:].mean() / max(vpin[:-rw].mean(), 1e-9)
    sign_vol = np.where(c >= o, v, -v)
    cvd_slope = float(np.sum(sign_vol[-rw:])) / max(abs(float(np.sum(sign_vol))), 1e-9)

    rs_win_alt = alt_df.iloc[alt_idx - rs_window: alt_idx]["close"].values
    rs_win_btc = btc_df.iloc[btc_idx - rs_window: btc_idx]["close"].values
    alt_chg = float(rs_win_alt[-1]) / max(float(rs_win_alt[0]), 1e-9) - 1.0
    btc_chg = float(rs_win_btc[-1]) / max(float(rs_win_btc[0]), 1e-9) - 1.0
    rs = (1.0 + alt_chg) / max(1.0 + btc_chg, 1e-9) if btc_chg > -1 else 0.0

    return bool(
        (raw_ret < 0.0)
        and (acc > 1.0)
        and (cvd_slope > 0.0)
        and (0.5 <= rs < 1.0)
    )


def sim_tp_sl(
    df: pd.DataFrame,
    entry_idx: int,
    tp: float,
    sl: float,
    max_bars: int = FORWARD_BARS,
) -> tuple[float, str]:
    if entry_idx >= len(df) - 1:
        return 0.0, "expired"
    entry_price = df["close"].iloc[entry_idx]
    tp_price = entry_price * (1 + tp)
    sl_price = entry_price * (1 - sl)
    for i in range(entry_idx + 1, min(entry_idx + max_bars + 1, len(df))):
        if df["low"].iloc[i] <= sl_price:
            return -sl, "sl"
        if df["high"].iloc[i] >= tp_price:
            return tp, "tp"
    final_price = df["close"].iloc[min(entry_idx + max_bars, len(df) - 1)]
    return final_price / entry_price - 1.0, "expired"


# ── Backtest Engine ───────────────────────────────────────────────────────────

def run_backtest_on_events(
    btc: pd.DataFrame,
    alt_data: dict[str, pd.DataFrame],
    events: list[int],
) -> dict:
    """이벤트 목록에 대해 stealth 백테스트 실행."""
    results: dict[str, list[float]] = {sym: [] for sym in ALT_SYMBOLS}

    for trans_idx in events:
        entered_syms: set[str] = set()
        for fwd in range(0, 7):
            check_idx = trans_idx + fwd
            if check_idx >= len(btc):
                break
            if len(entered_syms) == len(ALT_SYMBOLS):
                break
            for sym in ALT_SYMBOLS:
                if sym in entered_syms:
                    continue
                adf = alt_data[sym]
                btc_ts = btc.index[check_idx]
                if btc_ts not in adf.index:
                    continue
                alt_idx = adf.index.get_loc(btc_ts)
                if not isinstance(alt_idx, int):
                    alt_idx = int(alt_idx)
                if not compute_alt_stealth(adf, btc, check_idx):
                    continue
                tp, sl = TP_SL[sym]
                ret, _ = sim_tp_sl(adf, alt_idx, tp=tp, sl=sl)
                results[sym].append(ret)
                entered_syms.add(sym)

    all_rets: list[float] = []
    for sym in ALT_SYMBOLS:
        all_rets.extend(results[sym])

    if not all_rets:
        return {"n": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0, "events": len(events)}

    wr  = sum(1 for r in all_rets if r > 0) / len(all_rets)
    avg = float(np.mean(all_rets))
    std = float(np.std(all_rets)) if len(all_rets) > 1 else 0.0
    sh  = avg / std if std > 0 else 0.0

    return {"n": len(all_rets), "wr": wr, "avg": avg, "sharpe": sh, "events": len(events)}


# ── Event Extraction ──────────────────────────────────────────────────────────

MIN_IDX = max(SMA_WINDOW, VOL_LONG, TREND_W) + LOOKBACK + RECENT_W + 12 + 5


def extract_events(
    btc: pd.DataFrame,
    n_filter: int,
    use_trend: bool,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> list[int]:
    """주어진 기간 내 이벤트 인덱스(글로벌 btc 기준) 반환."""
    events: list[int] = []
    for i in range(MIN_IDX, len(btc) - n_filter - FORWARD_BARS - 5):
        ts = btc.index[i]
        if ts < start_ts or ts >= end_ts:
            continue
        # SMA20 최초 돌파
        if btc["above_sma"].iloc[i - 1] or not btc["above_sma"].iloc[i]:
            continue
        # N봉 연속 유지
        if not all(btc["above_sma"].iloc[i + k] for k in range(1, n_filter + 1)):
            continue
        # btc_trend_pos 필터
        if use_trend and btc["btc_trend_pos"].iloc[i] < 0.5:
            continue
        events.append(i)
    return events


# ── Walk-Forward 분할 생성 ────────────────────────────────────────────────────

def generate_wf_splits(
    full_start: str,
    full_end: str,
    is_months: int,
    oos_months: int,
    slide_months: int,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """(is_start, is_end, oos_start, oos_end) 리스트 반환."""
    splits = []
    is_start = pd.Timestamp(full_start)
    data_end = pd.Timestamp(full_end)

    while True:
        is_end   = is_start + pd.DateOffset(months=is_months)
        oos_end  = is_end   + pd.DateOffset(months=oos_months)
        if oos_end > data_end:
            break
        splits.append((is_start, is_end, is_end, oos_end))
        is_start = is_start + pd.DateOffset(months=slide_months)

    return splits


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 75)
    print("[사이클 95] N=12 + btc_trend_pos Walk-Forward 검증")
    print(f"IS={IS_MONTHS}개월, OOS={OOS_MONTHS}개월, Slide={SLIDE_MONTHS}개월")
    print("=" * 75)

    print(f"\nLoading BTC {CTYPE} ({FULL_START}~{FULL_END})...")
    btc = load_historical("KRW-BTC", CTYPE, FULL_START, FULL_END)
    btc = compute_macro_proxy(btc)
    btc["sma20"]     = btc["close"].rolling(SMA_WINDOW).mean()
    btc["above_sma"] = btc["close"] > btc["sma20"]
    print(f"BTC rows: {len(btc)}")

    print("Loading alt data...")
    alt_data: dict[str, pd.DataFrame] = {}
    for sym in ALT_SYMBOLS:
        df = load_historical(sym, CTYPE, FULL_START, FULL_END)
        alt_data[sym] = df
        print(f"  {sym}: {len(df)} rows")

    splits = generate_wf_splits(FULL_START, FULL_END, IS_MONTHS, OOS_MONTHS, SLIDE_MONTHS)
    print(f"\nWalk-Forward 분할 수: {len(splits)}개")

    # ── IS 결과 누적 ──────────────────────────────────────────────────────────
    print("\n" + "=" * 75)
    print("IS(In-Sample) 결과")
    print("=" * 75)
    print(f"{'기간':28s} {'필터':28s} {'이벤트':>6} {'진입':>5} {'WR%':>6} {'avg%':>7} {'Sharpe':>7}")
    print("-" * 90)

    wf_oos_n12_only:  list[dict] = []
    wf_oos_n12_trend: list[dict] = []
    wf_is_n12_only:   list[dict] = []
    wf_is_n12_trend:  list[dict] = []

    for is_start, is_end, oos_start, oos_end in splits:
        period_label = f"{is_start.strftime('%Y-%m')}~{is_end.strftime('%Y-%m')}"
        oos_label    = f"{oos_start.strftime('%Y-%m')}~{oos_end.strftime('%Y-%m')}"

        # IS 이벤트
        ev_is_n12   = extract_events(btc, 12, False, is_start, is_end)
        ev_is_trend = extract_events(btc, 12, True,  is_start, is_end)

        r_is_n12   = run_backtest_on_events(btc, alt_data, ev_is_n12)
        r_is_trend = run_backtest_on_events(btc, alt_data, ev_is_trend)
        wf_is_n12_only.append(r_is_n12)
        wf_is_n12_trend.append(r_is_trend)

        def fmt(r: dict) -> str:
            if r["n"] == 0:
                return f"{'0':>6} {'0':>5} {'N/A':>6} {'N/A':>7} {'N/A':>7}"
            return (
                f"{r['events']:>6} {r['n']:>5} {r['wr']*100:>5.1f}% "
                f"{r['avg']*100:>+6.2f}% {r['sharpe']:>+7.2f}"
            )

        print(f"{period_label:28s} {'N=12 단독':28s} {fmt(r_is_n12)}")
        print(f"{'':28s} {'N=12 + btc_trend_pos':28s} {fmt(r_is_trend)}")
        print()

    # ── OOS 결과 누적 ─────────────────────────────────────────────────────────
    print("\n" + "=" * 75)
    print("OOS(Out-Of-Sample) 결과 ← 핵심 검증")
    print("=" * 75)
    print(f"{'기간':28s} {'필터':28s} {'이벤트':>6} {'진입':>5} {'WR%':>6} {'avg%':>7} {'Sharpe':>7}")
    print("-" * 90)

    for is_start, is_end, oos_start, oos_end in splits:
        oos_label = f"{oos_start.strftime('%Y-%m')}~{oos_end.strftime('%Y-%m')}"

        ev_oos_n12   = extract_events(btc, 12, False, oos_start, oos_end)
        ev_oos_trend = extract_events(btc, 12, True,  oos_start, oos_end)

        r_oos_n12   = run_backtest_on_events(btc, alt_data, ev_oos_n12)
        r_oos_trend = run_backtest_on_events(btc, alt_data, ev_oos_trend)
        wf_oos_n12_only.append(r_oos_n12)
        wf_oos_n12_trend.append(r_oos_trend)

        def fmt(r: dict) -> str:
            if r["n"] == 0:
                return f"{'0':>6} {'0':>5} {'N/A':>6} {'N/A':>7} {'N/A':>7}"
            return (
                f"{r['events']:>6} {r['n']:>5} {r['wr']*100:>5.1f}% "
                f"{r['avg']*100:>+6.2f}% {r['sharpe']:>+7.2f}"
            )

        print(f"{oos_label:28s} {'N=12 단독':28s} {fmt(r_oos_n12)}")
        print(f"{'':28s} {'N=12 + btc_trend_pos':28s} {fmt(r_oos_trend)}")
        print()

    # ── OOS 통합 요약 ─────────────────────────────────────────────────────────
    def aggregate(results: list[dict]) -> dict:
        all_rets: list[float] = []
        total_ev = 0
        for r in results:
            total_ev += r["events"]
            if r["n"] > 0:
                # avg/wr 재계산을 위해 근사값 사용 (개별 trade ret 없으므로)
                pass
        valid = [r for r in results if r["n"] > 0]
        if not valid:
            return {"n": 0, "events": total_ev, "wr": 0.0, "avg": 0.0, "sharpe": 0.0}

        # 가중 평균 (trade 수 기준)
        total_n  = sum(r["n"]        for r in valid)
        avg_wr   = sum(r["wr"]  * r["n"] for r in valid) / total_n
        avg_ret  = sum(r["avg"] * r["n"] for r in valid) / total_n
        avg_sh   = sum(r["sharpe"] * r["n"] for r in valid) / total_n
        return {"n": total_n, "events": total_ev, "wr": avg_wr, "avg": avg_ret, "sharpe": avg_sh}

    agg_oos_n12   = aggregate(wf_oos_n12_only)
    agg_oos_trend = aggregate(wf_oos_n12_trend)
    agg_is_n12    = aggregate(wf_is_n12_only)
    agg_is_trend  = aggregate(wf_is_n12_trend)

    print("\n" + "=" * 75)
    print("Walk-Forward 집계 요약")
    print("=" * 75)
    print(f"{'세트':10s} {'필터':28s} {'진입':>5} {'WR%':>6} {'avg%':>7} {'Sharpe':>8}")
    print("-" * 70)

    def fmt_agg(r: dict) -> str:
        if r["n"] == 0:
            return f"{'0':>5} {'N/A':>6} {'N/A':>7} {'N/A':>8}"
        return f"{r['n']:>5} {r['wr']*100:>5.1f}% {r['avg']*100:>+6.2f}% {r['sharpe']:>+8.2f}"

    print(f"{'IS 평균':10s} {'N=12 단독':28s} {fmt_agg(agg_is_n12)}")
    print(f"{'IS 평균':10s} {'N=12 + btc_trend_pos':28s} {fmt_agg(agg_is_trend)}")
    print("-" * 70)
    print(f"{'OOS 평균':10s} {'N=12 단독':28s} {fmt_agg(agg_oos_n12)}")
    print(f"{'OOS 평균':10s} {'N=12 + btc_trend_pos':28s} {fmt_agg(agg_oos_trend)}")

    # ── 과적합 비율 ───────────────────────────────────────────────────────────
    print("\n" + "=" * 75)
    print("IS → OOS Sharpe 비율 (1.0 이상 = 과적합 없음)")
    print("=" * 75)
    for label, is_r, oos_r in [
        ("N=12 단독",          agg_is_n12,   agg_oos_n12),
        ("N=12 + btc_trend",   agg_is_trend, agg_oos_trend),
    ]:
        if is_r["sharpe"] != 0 and is_r["n"] > 0 and oos_r["n"] > 0:
            ratio = oos_r["sharpe"] / is_r["sharpe"]
            status = "✅ OK" if ratio >= 0.5 else ("⚠️ 주의" if ratio >= 0.3 else "❌ 과적합 의심")
            print(f"  {label:28s}: IS={is_r['sharpe']:+.2f} → OOS={oos_r['sharpe']:+.2f} "
                  f"(비율={ratio:.2f}) {status}")
        else:
            print(f"  {label:28s}: 데이터 부족")

    print("\n[사이클 95] Walk-Forward 검증 완료.")


if __name__ == "__main__":
    main()
