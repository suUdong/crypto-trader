"""
BTC 급락+acc≈1.0 이후 알트 진입 전략 백테스트

Signal:
  - BTC ret(4h) <= -2% AND acc∈[0.9, 1.1]
  → 다음 4h봉 시작에서 stealth_score 상위 알트 진입
  → 48h(12봉) 후 청산

현재 시장이 이 조건에 해당 → 어떤 알트에 진입해야 할지 파악
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOLS = [
    "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-AVAX",
    "KRW-DOT", "KRW-LINK", "KRW-MATIC", "KRW-ATOM", "KRW-NEAR",
    "KRW-ARB", "KRW-OP", "KRW-SUI", "KRW-APT", "KRW-TIA",
    "KRW-INJ", "KRW-STX", "KRW-MANA", "KRW-SAND", "KRW-AXS",
]
BTC_SYMBOL = "KRW-BTC"
START = "2022-01-01"
END   = "2026-04-03"
FWD   = 12  # 48h
FEE   = 0.0005
W     = 36  # stealth lookback (최적값)


def compute_vpin(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    direction = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy_vols = np.where(direction > 0, volumes[1:], 0.0)
    vpin = buy_vols / (volumes[1:] + 1e-9)
    return np.concatenate([[np.nan], vpin])


def compute_btc_acc(closes, volumes, w=36):
    vpin = compute_vpin(closes, volumes)
    n = len(closes)
    acc = np.full(n, np.nan)
    for i in range(w * 2, n):
        recent = np.nanmean(vpin[i-w:i])
        older  = np.nanmean(vpin[i-w*2:i-w])
        acc[i] = recent / (older + 1e-9)
    return acc


def compute_stealth_score(closes, volumes, w=36):
    """Alt stealth score: acc>1.0 AND price_ret<0 AND cvd_slope>0."""
    n = len(closes)
    vpin = compute_vpin(closes, volumes)
    scores = np.full(n, 0.0)
    for i in range(w * 2, n):
        recent_vpin = np.nanmean(vpin[i-w:i])
        older_vpin  = np.nanmean(vpin[i-w*2:i-w])
        acc = recent_vpin / (older_vpin + 1e-9)

        cvd = np.cumsum(np.where(closes[1:] >= closes[:-1], volumes[1:], -volumes[1:]))
        if len(cvd) < w:
            continue
        cvd_slope = (cvd[-1] - cvd[-w]) / (np.mean(volumes[-w:]) + 1e-9)

        price_ret = closes[i] / closes[i-w] - 1.0

        s = 0.0
        if acc > 1.0:     s += 0.35
        if cvd_slope > 0: s += 0.35
        if price_ret < 0: s += 0.30  # 아직 안 오름
        scores[i] = s
    return scores


def main():
    print("=== BTC 급락+acc 이후 알트 진입 전략 백테스트 ===")
    print(f"기간: {START}~{END}  FWD={FWD}봉(48h)")

    # BTC 데이터
    btc = load_historical(BTC_SYMBOL, "240m", START, END)
    if btc.empty:
        print("BTC 데이터 없음")
        return

    btc_c = btc["close"].values
    btc_v = btc["volume"].values
    btc_ret1 = np.full(len(btc_c), np.nan)
    btc_ret1[1:] = btc_c[1:] / btc_c[:-1] - 1.0
    btc_acc = compute_btc_acc(btc_c, btc_v, W)
    btc_dates = pd.to_datetime(btc.index) if isinstance(btc.index[0], str) else btc.index

    # BTC 신호 발생 시점
    btc_signal_bars = []
    for i in range(W*2, len(btc_c) - FWD):
        if (not np.isnan(btc_ret1[i]) and btc_ret1[i] <= -0.02
                and not np.isnan(btc_acc[i]) and 0.9 <= btc_acc[i] <= 1.1):
            btc_signal_bars.append(i)

    print(f"\nBTC 신호 발생: {len(btc_signal_bars)}회")
    if not btc_signal_bars:
        return

    # 각 알트 성과
    alt_results = []
    loaded = {}
    for sym in SYMBOLS:
        df = load_historical(sym, "240m", START, END)
        if df.empty or len(df) < W * 2 + FWD:
            continue
        loaded[sym] = df

    for sym, df in loaded.items():
        c = df["close"].values
        v = df["volume"].values
        scores = compute_stealth_score(c, v, W)

        # BTC 신호 시점과 날짜 매칭
        alt_dates = pd.to_datetime(df.index) if isinstance(df.index[0], str) else df.index

        fwd_rets = []
        stealth_rets = []  # 스텔스 점수 높은 시점만

        for btc_i in btc_signal_bars:
            if btc_i >= len(btc_dates) or btc_i >= len(alt_dates):
                continue
            btc_ts = btc_dates[btc_i]
            # alt에서 같은 시점 찾기
            try:
                alt_i = alt_dates.get_loc(btc_ts) if hasattr(alt_dates, 'get_loc') else None
                if alt_i is None:
                    diffs = np.abs((alt_dates - btc_ts).total_seconds())
                    alt_i = diffs.argmin()
                    if diffs[alt_i] > 4 * 3600:
                        continue
            except Exception:
                continue

            if alt_i + FWD >= len(c):
                continue

            entry = c[alt_i + 1] * (1 + FEE)
            exit_ = c[alt_i + FWD]
            r = exit_ / entry - 1 - FEE
            fwd_rets.append(r)

            if scores[alt_i] >= 0.7:
                stealth_rets.append(r)

        if len(fwd_rets) < 5:
            continue

        arr = np.array(fwd_rets)
        alt_results.append({
            "symbol": sym,
            "n": len(arr),
            "avg": arr.mean(),
            "wr": (arr > 0).mean(),
            "n_stealth": len(stealth_rets),
            "stealth_avg": np.mean(stealth_rets) if stealth_rets else np.nan,
            "stealth_wr": np.mean(np.array(stealth_rets) > 0) if stealth_rets else np.nan,
        })

    if not alt_results:
        print("알트 결과 없음")
        return

    alt_results.sort(key=lambda x: x["avg"], reverse=True)

    print(f"\n{'심볼':<14} {'N':>4} {'avg 48h':>9} {'WR':>7} | {'N(st)':>6} {'st avg':>9} {'st WR':>7}")
    print("-" * 70)
    for r in alt_results:
        st_avg = f"{r['stealth_avg']*100:+.2f}%" if not np.isnan(r["stealth_avg"]) else "  n/a"
        st_wr  = f"{r['stealth_wr']:.1%}" if not np.isnan(r["stealth_wr"]) else "  n/a"
        print(f"{r['symbol']:<14} {r['n']:>4} {r['avg']*100:>+8.2f}% {r['wr']:>6.1%} | "
              f"{r['n_stealth']:>6} {st_avg:>9} {st_wr:>7}")

    best = alt_results[0]
    print(f"\n★ 최고 성과 알트: {best['symbol']}  avg={best['avg']*100:+.2f}%  WR={best['wr']:.1%}  n={best['n']}")

    # stealth 필터 효과
    stealth_improved = [r for r in alt_results
                        if r["n_stealth"] >= 3 and not np.isnan(r["stealth_avg"])
                        and r["stealth_avg"] > r["avg"]]
    print(f"\nStealth 필터 개선 심볼: {len(stealth_improved)}/{len(alt_results)}")
    if stealth_improved:
        stealth_improved.sort(key=lambda x: x["stealth_avg"], reverse=True)
        s = stealth_improved[0]
        print(f"  Best: {s['symbol']}  stealth_avg={s['stealth_avg']*100:+.2f}%  WR={s['stealth_wr']:.1%}  n={s['n_stealth']}")


if __name__ == "__main__":
    main()
