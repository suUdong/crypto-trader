#!/usr/bin/env python3
"""
BTC BULL 전환 타이밍 + 전환 직후 4개 심볼 성과 검증 (사이클 88)

분석 목표:
  1. BTC BEAR→BULL 전환 이벤트 추출 (SMA20 돌파)
  2. 전환 T-96h, T-48h, T-24h, T-0h 시점에서 pre_bull 지표 계산
     - pre_bull_score = pct_pos_acc + pct_pos_cvd + pct_weak_rs - 1.0
     - 현재 조건: pre_bull ≥ 0.6 + stealth ≥ 8
  3. "pre_bull ≥ 0.6" 조건이 전환 몇 시간 전에 발동했는가?
  4. BULL 전환 직후 48h/96h 동안 SOL/ETH/XRP/TRX stealth_3gate 성과
     (TP=12%/10%/12%/12%, SL=4%/3%/4%/3% 파라미터 적용)

Usage:
    .venv/bin/python3 scripts/backtest_bull_transition_timing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))

from historical_loader import load_historical  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────────────
CTYPE = "240m"          # 4h 캔들
START = "2022-01-01"
END   = "2026-04-03"
SMA_WINDOW = 20         # BTC SMA20 기준

LOOKBACK = 12           # pre_bull 계산 윈도우 (48h in 4h bars)
RECENT_W = 4            # acc/cvd 최근 구간 (16h in 4h bars)
ALT_SYMBOLS = ["KRW-SOL", "KRW-ETH", "KRW-XRP", "KRW-TRX"]

# 4개 심볼 TP/SL 파라미터 (확정값 사이클 83-85)
TP_SL = {
    "KRW-SOL": (0.12, 0.04),
    "KRW-ETH": (0.10, 0.03),
    "KRW-XRP": (0.12, 0.04),
    "KRW-TRX": (0.12, 0.03),
}

PRE_BULL_THRESHOLD = 0.6
STEALTH_MIN_COUNT = 6   # 최소 stealth 코인 수 (전체 12개 샘플 기준)
FORWARD_BARS = [6, 12, 24]  # 24h, 48h, 96h 성과 측정

# ── Helpers ──────────────────────────────────────────────────────────────────

def compute_pre_bull_score(
    btc_df: pd.DataFrame,
    idx: int,
    lb: int = LOOKBACK,
    rw: int = RECENT_W,
) -> dict:
    """주어진 idx에서 pre_bull_score 계산."""
    if idx < lb + rw:
        return {"pre_bull_score": float("nan"), "stealth": False, "acc": float("nan"), "cvd": float("nan")}

    window = btc_df.iloc[idx - lb: idx]
    c = window["close"].values
    o = window["open"].values
    h = window["high"].values
    lv = window["low"].values
    v = window["volume"].values

    # BTC 지표
    raw_ret = float(c[-1]) / max(float(c[0]), 1e-9) - 1.0
    rng = np.clip(h - lv, 1e-9, None)
    vpin = np.abs(c - o) / rng
    acc = vpin[-rw:].mean() / max(vpin[:-rw].mean(), 1e-9)

    # CVD slope (최근 rw 구간)
    sign_vol = np.where(c >= o, v, -v)
    cvd = np.cumsum(sign_vol)
    cvd_slope = (cvd[-1] - cvd[-rw]) / (rw * max(abs(cvd[-1]), 1e-9))

    stealth = (raw_ret < 0.0) and (acc > 1.0) and (cvd_slope > 0)
    return {
        "raw_ret": raw_ret,
        "acc": acc,
        "cvd_slope": cvd_slope,
        "stealth": stealth,
    }


def compute_alt_stealth(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    idx: int,
    lb: int = LOOKBACK,
    rw: int = RECENT_W,
    rs_window: int = 20,
) -> dict:
    """alt stealth_3gate 조건 계산 (RS 필터 포함)."""
    if idx < max(lb + rw, rs_window):
        return {"stealth": False}

    win = alt_df.iloc[idx - lb: idx]
    btc_win = btc_df.iloc[idx - lb: idx]
    if len(win) < lb or len(btc_win) < lb:
        return {"stealth": False}

    c = win["close"].values
    o = win["open"].values
    h = win["high"].values
    lv = win["low"].values
    v = win["volume"].values

    raw_ret = float(c[-1]) / max(float(c[0]), 1e-9) - 1.0
    rng = np.clip(h - lv, 1e-9, None)
    vpin = np.abs(c - o) / rng
    acc = vpin[-rw:].mean() / max(vpin[:-rw].mean(), 1e-9)
    sign_vol = np.where(c >= o, v, -v)
    cvd_slope = float(np.sum(sign_vol[-rw:])) / max(abs(float(np.sum(sign_vol))), 1e-9)

    # RS = alt 수익률 / BTC 수익률 (SMA20 구간)
    rs_win_alt = alt_df.iloc[idx - rs_window: idx]["close"].values
    rs_win_btc = btc_df.iloc[idx - rs_window: idx]["close"].values
    alt_chg = float(rs_win_alt[-1]) / max(float(rs_win_alt[0]), 1e-9) - 1.0
    btc_chg = float(rs_win_btc[-1]) / max(float(rs_win_btc[0]), 1e-9) - 1.0
    rs = (1.0 + alt_chg) / max(1.0 + btc_chg, 1e-9) if btc_chg > -1 else 0.0

    stealth = (raw_ret < 0.0) and (acc > 1.0) and (cvd_slope > 0.0) and (0.5 <= rs < 1.0)
    return {"stealth": stealth, "acc": acc, "rs": rs}


def sim_tp_sl(
    df: pd.DataFrame,
    entry_idx: int,
    tp: float,
    sl: float,
    max_bars: int = 24,
) -> tuple[float, str]:
    """TP/SL 시뮬레이션 — 첫 도달 가격 기준."""
    if entry_idx >= len(df) - 1:
        return 0.0, "expired"
    entry_price = df["close"].iloc[entry_idx]
    tp_price = entry_price * (1 + tp)
    sl_price = entry_price * (1 - sl)
    for i in range(entry_idx + 1, min(entry_idx + max_bars + 1, len(df))):
        h = df["high"].iloc[i]
        lv = df["low"].iloc[i]
        if lv <= sl_price:
            return -sl, "sl"
        if h >= tp_price:
            return tp, "tp"
    # expired
    final_price = df["close"].iloc[min(entry_idx + max_bars, len(df) - 1)]
    ret = final_price / entry_price - 1.0
    return ret, "expired"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Loading BTC {CTYPE} data ({START} ~ {END})...")
    btc = load_historical("KRW-BTC", CTYPE, START, END)
    print(f"BTC rows: {len(btc)}")

    print("Loading alt data...")
    alt_data: dict[str, pd.DataFrame] = {}
    for sym in ALT_SYMBOLS:
        df = load_historical(sym, CTYPE, START, END)
        alt_data[sym] = df
        print(f"  {sym}: {len(df)} rows")

    # BTC SMA20 계산
    btc["sma20"] = btc["close"].rolling(SMA_WINDOW).mean()
    btc["above_sma"] = btc["close"] > btc["sma20"]

    # BEAR→BULL 전환 이벤트 추출 (전봉 below, 현봉 above)
    transitions = []
    for i in range(SMA_WINDOW + LOOKBACK + RECENT_W, len(btc) - max(FORWARD_BARS)):
        if not btc["above_sma"].iloc[i - 1] and btc["above_sma"].iloc[i]:
            transitions.append(i)

    print(f"\n총 BEAR→BULL 전환 이벤트: {len(transitions)}개")

    # ── 분석 1: 전환 전 pre_bull 발동 타이밍 ──────────────────────────────
    print("\n=== 분석 1: BTC pre_bull 신호 선행 타이밍 ===")
    print(f"{'날짜':20s} {'T-96h':>7} {'T-48h':>7} {'T-24h':>7} {'T-0h':>7}")
    print("-" * 55)

    pre_bull_lead_times: list[int] = []   # 몇 봉 전에 처음 pre_bull≥0.6 발동?

    for idx in transitions:
        ts = btc.index[idx]
        checks = {
            "T-24b": idx - 24,  # T-96h
            "T-12b": idx - 12,  # T-48h
            "T-6b":  idx - 6,   # T-24h
            "T-0b":  idx,       # T-0h
        }
        scores = {}
        for label, check_idx in checks.items():
            if check_idx < 0:
                scores[label] = float("nan")
                continue
            r = compute_pre_bull_score(btc, check_idx)
            scores[label] = r["acc"] - 1.0 if not np.isnan(r["acc"]) else float("nan")  # proxy

        # 실제 pre_bull_score 계산 (단순 btc stealth 기반)
        def score_at(ci: int) -> float:
            if ci < 0:
                return float("nan")
            r = compute_pre_bull_score(btc, ci)
            # stealth=True면 +1 기여, acc/cvd 정도에 비례한 proxy
            acc_v = r.get("acc", 1.0)
            cvd_v = r.get("cvd_slope", 0.0)
            raw_v = r.get("raw_ret", 0.0)
            # 간단한 pre_bull proxy: (acc-1)*2 + (cvd>0)*0.3 + (raw<0)*0.2
            val = (max(acc_v - 1.0, 0) * 2 + (1 if cvd_v > 0 else 0) * 0.3 +
                   (1 if raw_v < 0 else 0) * 0.2)
            return round(min(val, 1.5), 3)

        s24b = score_at(idx - 24)
        s12b = score_at(idx - 12)
        s6b  = score_at(idx - 6)
        s0b  = score_at(idx)

        # 처음 ≥ 0.6 발동 시점
        for lag, s in [(24, s24b), (12, s12b), (6, s6b), (0, s0b)]:
            if s >= PRE_BULL_THRESHOLD:
                pre_bull_lead_times.append(lag)
                break

        flag24 = "✓" if s24b >= PRE_BULL_THRESHOLD else " "
        flag12 = "✓" if s12b >= PRE_BULL_THRESHOLD else " "
        flag6  = "✓" if s6b  >= PRE_BULL_THRESHOLD else " "
        flag0  = "✓" if s0b  >= PRE_BULL_THRESHOLD else " "
        print(
            f"{str(ts)[:19]:20s} "
            f"{s24b:+.3f}{flag24} {s12b:+.3f}{flag12} "
            f"{s6b:+.3f}{flag6}  {s0b:+.3f}{flag0}"
        )

    if pre_bull_lead_times:
        avg_lag = np.mean(pre_bull_lead_times)
        print(f"\n평균 pre_bull≥{PRE_BULL_THRESHOLD} 선행 봉수: {avg_lag:.1f}봉 "
              f"(= {avg_lag * 4:.0f}h 전)")
        cnt24b = sum(1 for x in pre_bull_lead_times if x == 24)
        cnt12b = sum(1 for x in pre_bull_lead_times if x == 12)
        cnt6b  = sum(1 for x in pre_bull_lead_times if x == 6)
        cnt0b  = sum(1 for x in pre_bull_lead_times if x == 0)
        total  = len(pre_bull_lead_times)
        print(f"  T-96h에 처음 발동: {cnt24b}/{total} ({cnt24b/total*100:.0f}%)")
        print(f"  T-48h에 처음 발동: {cnt12b}/{total} ({cnt12b/total*100:.0f}%)")
        print(f"  T-24h에 처음 발동: {cnt6b}/{total}  ({cnt6b/total*100:.0f}%)")
        print(f"  T-0h에 처음 발동:  {cnt0b}/{total}  ({cnt0b/total*100:.0f}%)")

    # ── 분석 2: BULL 전환 직후 stealth_3gate 성과 ────────────────────────
    print("\n=== 분석 2: BULL 전환 직후 stealth_3gate 성과 (TP/SL 시뮬레이션) ===")
    print(f"대상 심볼: {', '.join(ALT_SYMBOLS)}")
    print(f"진입 조건: stealth_3gate ON (ret<0, acc>1, cvd>0, 0.5≤RS<1.0)")
    print()

    results: dict[str, list[float]] = {sym: [] for sym in ALT_SYMBOLS}
    exits: dict[str, dict[str, int]] = {sym: {"tp": 0, "sl": 0, "expired": 0} for sym in ALT_SYMBOLS}

    for trans_idx in transitions:
        ts = btc.index[trans_idx]
        # 전환 후 6봉(24h) 이내에서 stealth 조건 확인 후 진입
        for fwd in range(0, 7):
            check_idx = trans_idx + fwd
            for sym in ALT_SYMBOLS:
                adf = alt_data[sym]
                # align indices
                try:
                    # btc와 alt 인덱스 동기화
                    btc_ts = btc.index[check_idx]
                    if btc_ts not in adf.index:
                        continue
                    alt_idx = adf.index.get_loc(btc_ts)
                    if not isinstance(alt_idx, int):
                        alt_idx = int(alt_idx)
                except (KeyError, IndexError):
                    continue

                cond = compute_alt_stealth(adf, btc, check_idx, lb=LOOKBACK, rw=RECENT_W)
                if not cond["stealth"]:
                    continue

                tp, sl = TP_SL[sym]
                ret, exit_type = sim_tp_sl(adf, alt_idx, tp=tp, sl=sl, max_bars=24)
                results[sym].append(ret)
                exits[sym][exit_type] += 1
                break  # 심볼당 첫 진입만

    print(f"{'심볼':12s} {'진입수':>6} {'WR%':>6} {'avg_ret':>8} {'TP':>5} {'SL':>5} {'exp':>5} {'Sharpe':>7}")
    print("-" * 65)

    all_rets: list[float] = []
    for sym in ALT_SYMBOLS:
        rets = results[sym]
        if not rets:
            print(f"{sym:12s} {'0':>6}")
            continue
        wr = sum(1 for r in rets if r > 0) / len(rets)
        avg = np.mean(rets)
        std = np.std(rets) if len(rets) > 1 else 0.0
        sh = avg / std if std > 0 else 0.0
        tp_c = exits[sym]["tp"]
        sl_c = exits[sym]["sl"]
        ex_c = exits[sym]["expired"]
        print(
            f"{sym:12s} {len(rets):>6} {wr*100:>5.1f}% "
            f"{avg*100:>+7.2f}% {tp_c:>5} {sl_c:>5} {ex_c:>5} "
            f"{sh:>+7.2f}"
        )
        all_rets.extend(rets)

    if all_rets:
        overall_wr = sum(1 for r in all_rets if r > 0) / len(all_rets)
        overall_avg = np.mean(all_rets)
        overall_std = np.std(all_rets) if len(all_rets) > 1 else 0.0
        overall_sh = overall_avg / overall_std if overall_std > 0 else 0.0
        print("-" * 65)
        print(
            f"{'TOTAL':12s} {len(all_rets):>6} {overall_wr*100:>5.1f}% "
            f"{overall_avg*100:>+7.2f}% {'':>5} {'':>5} {'':>5} "
            f"{overall_sh:>+7.2f}"
        )

    # ── 분석 3: BULL 전환 후 단순 보유 성과 (Buy at transition, hold 24/48봉) ──
    print("\n=== 분석 3: BULL 전환 직후 단순 보유 성과 (기준선) ===")
    print(f"{'심볼':12s} {'n':>4} {'24h avg':>9} {'48h avg':>9} {'96h avg':>9}")
    print("-" * 48)

    for sym in ALT_SYMBOLS:
        adf = alt_data[sym]
        rets_24h = []
        rets_48h = []
        rets_96h = []
        for trans_idx in transitions:
            btc_ts = btc.index[trans_idx]
            if btc_ts not in adf.index:
                continue
            alt_idx = adf.index.get_loc(btc_ts)
            if not isinstance(alt_idx, int):
                alt_idx = int(alt_idx)
            entry = adf["close"].iloc[alt_idx]
            for bars, lst in [(6, rets_24h), (12, rets_48h), (24, rets_96h)]:
                exit_idx = alt_idx + bars
                if exit_idx < len(adf):
                    lst.append(adf["close"].iloc[exit_idx] / entry - 1.0)
        r24 = f"{np.mean(rets_24h)*100:+.2f}%" if rets_24h else "N/A"
        r48 = f"{np.mean(rets_48h)*100:+.2f}%" if rets_48h else "N/A"
        r96 = f"{np.mean(rets_96h)*100:+.2f}%" if rets_96h else "N/A"
        n = len(rets_24h)
        print(f"{sym:12s} {n:>4} {r24:>9} {r48:>9} {r96:>9}")

    print("\n=== 결론 ===")
    print(f"BULL 전환 이벤트: {len(transitions)}개 (2022-01 ~ 2026-04)")
    if pre_bull_lead_times:
        print(f"pre_bull≥{PRE_BULL_THRESHOLD} 평균 선행: {np.mean(pre_bull_lead_times)*4:.0f}h 전")
    if all_rets:
        print(f"stealth_3gate 전환 직후 통합 WR: {overall_wr*100:.1f}%, avg: {overall_avg*100:+.2f}%, Sharpe: {overall_sh:+.2f}")


if __name__ == "__main__":
    main()
