"""
BTC 급락(-2%+) + acc>=1.0 + pre_bull>0.6 → 48h 회복 패턴 검증

현재 시장: BTC -2.4%, acc=1.000, pre_bull=0.75
이 조합이 바닥 신호인지 역사 데이터로 확인.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL_BTC = "KRW-BTC"
START = "2022-01-01"
END   = "2026-04-03"
FWD_BARS = 12  # 48h (4h봉 × 12)


def compute_vpin(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """VPIN proxy: buy_vol / total_vol per bar."""
    direction = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy_vols = np.where(direction > 0, volumes[1:], 0.0)
    vpin = buy_vols / (volumes[1:] + 1e-9)
    return np.concatenate([[np.nan], vpin])


def compute_acc(closes: np.ndarray, volumes: np.ndarray, w: int = 36) -> np.ndarray:
    """acc = recent VPIN(W봉) / older VPIN(나머지) — market_scan_loop 동일 방식."""
    vpin = compute_vpin(closes, volumes)
    n = len(closes)
    acc = np.full(n, np.nan)
    for i in range(w * 2, n):
        recent_vpin = np.nanmean(vpin[i-w:i])
        older_vpin  = np.nanmean(vpin[i-w*2:i-w])
        acc[i] = recent_vpin / (older_vpin + 1e-9)
    return acc


def compute_ret(closes: np.ndarray, lookback: int = 6) -> np.ndarray:
    """현봉 기준 lookback봉 수익률."""
    ret = np.full(len(closes), np.nan)
    ret[lookback:] = closes[lookback:] / closes[:len(closes)-lookback] - 1.0
    return ret


def compute_sma(closes: np.ndarray, period: int) -> np.ndarray:
    return pd.Series(closes).rolling(period, min_periods=period).mean().values


def main() -> None:
    print("=== BTC 급락 + acc≥1.0 → 48h 회복 패턴 검증 ===")
    df = load_historical(SYMBOL_BTC, "240m", START, END)
    if df.empty:
        print("데이터 없음")
        return

    print(f"데이터: {len(df)}봉 ({START}~{END})")

    c = df["close"].values
    v = df["volume"].values
    n = len(c)

    ret1 = compute_ret(c, 1)   # 1봉 수익률 (4h)
    ret6 = compute_ret(c, 6)   # 6봉 수익률 (24h)
    acc  = compute_acc(c, v, 36)
    sma20_daily = compute_sma(c, 120)  # 일봉 SMA20 ≈ 4h × 120

    # 진입 조건 그리드
    conditions = [
        # (이름, ret1 임계, acc 임계, sma_gate)
        ("ret1<-1% acc≥1.0",          -0.01, 1.0, False),
        ("ret1<-2% acc≥1.0",          -0.02, 1.0, False),
        ("ret6<-3% acc≥1.0",          -0.03, 1.0, True),
        ("ret6<-5% acc≥1.0 below SMA",-0.05, 1.0, True),
        ("ret1<-2% acc≥0.98",         -0.02, 0.98, False),
        ("base (all bars)",            -9.9, 0.0, False),  # baseline
    ]

    print(f"\n{'조건':<32} {'N':>5} {'fwd48h avg':>11} {'WR':>7} {'best 1%':>9}")
    print("-" * 70)

    for name, ret_thresh, acc_thresh, below_sma in conditions:
        signals = []
        fwd_rets = []
        for i in range(140, n - FWD_BARS):
            r = ret1[i] if "ret1" in name else ret6[i]
            if np.isnan(r) or np.isnan(acc[i]):
                continue
            if r > ret_thresh:
                continue
            if acc[i] < acc_thresh:
                continue
            if below_sma and not np.isnan(sma20_daily[i]) and c[i] > sma20_daily[i]:
                continue
            fwd = c[i + FWD_BARS] / c[i] - 1.0
            signals.append(i)
            fwd_rets.append(fwd)

        if not fwd_rets:
            print(f"{name:<32} {'0':>5}")
            continue

        arr = np.array(fwd_rets)
        wr = (arr > 0).mean()
        avg = arr.mean()
        p99 = np.percentile(arr, 99)
        print(f"{name:<32} {len(arr):>5} {avg*100:>+10.2f}% {wr:>6.1%} {p99*100:>+8.1f}%")

    # 현재 시나리오: ret≈-2.4%, acc≈1.0
    print("\n=== 현재 시나리오 분석: ret1≤-2% AND acc∈[0.95,1.05] ===")
    scenario = []
    for i in range(140, n - FWD_BARS):
        if np.isnan(ret1[i]) or np.isnan(acc[i]):
            continue
        if ret1[i] <= -0.02 and 0.95 <= acc[i] <= 1.05:
            fwd = c[i + FWD_BARS] / c[i] - 1.0
            fwd24 = c[i + 6] / c[i] - 1.0
            scenario.append((i, fwd24, fwd))

    if scenario:
        fwd24s = [x[1] for x in scenario]
        fwd48s = [x[2] for x in scenario]
        print(f"발생 횟수: {len(scenario)}")
        print(f"24h 이후: avg={np.mean(fwd24s)*100:+.2f}%  WR={np.mean(np.array(fwd24s)>0):.1%}")
        print(f"48h 이후: avg={np.mean(fwd48s)*100:+.2f}%  WR={np.mean(np.array(fwd48s)>0):.1%}")
        print(f"48h 최악: {np.percentile(fwd48s, 5)*100:+.2f}%  최선: {np.percentile(fwd48s, 95)*100:+.2f}%")
    else:
        print("해당 시나리오 발생 없음")


if __name__ == "__main__":
    main()
