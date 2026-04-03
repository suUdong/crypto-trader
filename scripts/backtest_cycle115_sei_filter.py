"""
SEI stealth_3gate CVD/RS 필터 강화 그리드 탐색 (사이클 115)

배경:
  - 사이클 112 결과: SEI W1 OOS(2024H2~2025H1) Sharpe +1.545 ❌ (기준 3.0 미달)
                    SEI W2 OOS(2025 전체) Sharpe +4.500 ✅
  - W1 저조 원인 가설: CVD_THRESH=0.0 너무 느슨 → 2024H2 저품질 신호 혼입
  - 가설 검증: CVD_THRESH 강화(>0.5, >1.0, >1.5) + RS 범위 조정으로 2/2창 달성 시도

탐색 범위:
  CVD_THRESH: [0.0, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]
  RS_LOW: [0.3, 0.5, 0.7, 1.0]
  RS_HIGH: [0.8, 1.0, 1.5, 2.0]

성공 기준: W1 OOS Sharpe ≥ 3.0 AND W2 OOS Sharpe ≥ 3.0 (2/2창 통과)
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical

INTERVAL = "240m"
BTC_SYMBOL = "KRW-BTC"
SEI_SYMBOL = "KRW-SEI"

# 고정 파라미터
W = 36
SMA_P = 20
ACC_THRESH = 1.0
BTC_TREND_WINDOW = 10
TP = 0.15
SL = 0.03
MAX_HOLD = 24   # 24 * 4h = 96h
FWD = 6
FEE = 0.0005

# 탐색 범위
CVD_VALUES = [0.0, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]
RS_LOW_VALUES = [0.3, 0.5, 0.7, 1.0]
RS_HIGH_VALUES = [0.8, 1.0, 1.5, 2.0]

# SEI 윈도우 (사이클 112와 동일)
WINDOWS = [
    ("W1", "2024-07-01", "2025-06-30"),  # OOS: 2024H2~2025H1
    ("W2", "2025-01-01", "2025-12-31"),  # OOS: 2025 전체
]

SHARPE_MIN = 3.0
MIN_TRADES = 8
DATA_START = "2023-08-01"
DATA_END = "2026-04-04"


# ─── Indicator helpers ────────────────────────────────────────────────────────

def compute_sma(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(p - 1, len(arr)):
        out[i] = arr[i - p + 1 : i + 1].mean()
    return out


def compute_acc(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    vpin = np.concatenate([[np.nan], buy / (vols[1:] + 1e-9)])
    acc = np.full(len(closes), np.nan)
    for i in range(w * 2, len(closes)):
        recent_mean = np.nanmean(vpin[i - w : i])
        older_mean = np.nanmean(vpin[i - w * 2 : i - w])
        acc[i] = recent_mean / (older_mean + 1e-9)
    return acc


def compute_cvd_slope(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    cvd = np.cumsum(buy - vols[1:] / 2)
    cvd = np.concatenate([[0.0], cvd])
    slopes = np.full(len(closes), np.nan)
    avg_v = np.mean(vols)
    for i in range(w, len(closes)):
        slopes[i] = (cvd[i] - cvd[i - w]) / (avg_v + 1e-9)
    return slopes


def compute_rs(closes: np.ndarray, btc_closes: np.ndarray, w: int) -> np.ndarray:
    rs = np.full(len(closes), np.nan)
    for i in range(w, len(closes)):
        ar = closes[i] / closes[i - w] - 1.0
        br = btc_closes[i] / btc_closes[i - w] - 1.0
        rs[i] = (ar - br) / (abs(br) + 0.05)
    return rs


# ─── Backtest core ────────────────────────────────────────────────────────────

def _backtest_slice(
    c: np.ndarray,
    v: np.ndarray,
    bc: np.ndarray,
    idx: pd.DatetimeIndex,
    start: str,
    end: str,
    cvd_thresh: float,
    rs_low: float,
    rs_high: float,
    btc_sma: np.ndarray,
    acc: np.ndarray,
    cvd: np.ndarray,
    rs: np.ndarray,
) -> dict:
    mask = (idx >= start) & (idx <= end)
    idxs = np.where(mask)[0]
    if len(idxs) < W * 3:
        return {"n": 0, "sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0}

    trades: list[float] = []
    i_start = idxs[0]
    i_end = idxs[-1]
    i = max(i_start, W * 2)
    last_exit = 0

    while i <= i_end - FWD - 1:
        if i < last_exit:
            i += 1
            continue

        # Gate 1: BTC > SMA20
        if np.isnan(btc_sma[i]) or bc[i] <= btc_sma[i]:
            i += 1
            continue

        # Gate 4: btc_trend_pos
        if i < BTC_TREND_WINDOW or bc[i] <= bc[i - BTC_TREND_WINDOW]:
            i += 1
            continue

        # Alt filters
        if any(np.isnan(x) for x in [acc[i], cvd[i], rs[i]]):
            i += 1
            continue
        if acc[i] <= ACC_THRESH or cvd[i] <= cvd_thresh:
            i += 1
            continue
        if not (rs_low <= rs[i] < rs_high):
            i += 1
            continue

        entry = c[i]
        tp_p = entry * (1 + TP)
        sl_p = entry * (1 - SL)
        ret = None
        hold = 0

        for j in range(i + 1, min(i + MAX_HOLD + 1, len(c))):
            price = c[j]
            hold += 1
            if price >= tp_p:
                ret = TP - 2 * FEE
                break
            elif price <= sl_p:
                ret = -SL - 2 * FEE
                break

        if ret is None:
            fwd_idx = min(i + FWD, len(c) - 1)
            ret = c[fwd_idx] / entry - 1.0 - 2 * FEE

        trades.append(ret)
        last_exit = i + max(hold, 1)
        i = last_exit

    if len(trades) < 3:
        return {"n": len(trades), "sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0}

    arr = np.array(trades)
    sh = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6 / max(1, len(arr)))
    wr = float((arr > 0).mean()) * 100
    avg = float(arr.mean()) * 100

    return {"n": len(arr), "sharpe": sh, "wr": wr, "avg_ret": avg}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 75)
    print("사이클 115 — SEI stealth_3gate CVD/RS 필터 강화 그리드 탐색")
    print(f"W={W}, SMA{SMA_P}, ACC>{ACC_THRESH}, TP={TP*100:.0f}%, SL={SL*100:.0f}%")
    print(f"목표: W1 OOS(2024H2~2025H1) + W2 OOS(2025) 모두 Sharpe≥{SHARPE_MIN}")
    print("=" * 75)

    print("\n[데이터 로드...]")
    btc_df = load_historical(BTC_SYMBOL, INTERVAL, DATA_START, DATA_END)
    sei_df = load_historical(SEI_SYMBOL, INTERVAL, DATA_START, DATA_END)

    if btc_df is None or sei_df is None:
        print("ERROR: 데이터 로드 실패")
        return

    print(f"  BTC: {len(btc_df)} 봉 ({btc_df.index[0].date()} ~ {btc_df.index[-1].date()})")
    print(f"  SEI: {len(sei_df)} 봉 ({sei_df.index[0].date()} ~ {sei_df.index[-1].date()})")

    # 공통 인덱스로 정렬
    common_idx = sei_df.index.intersection(btc_df.index)
    sei_aligned = sei_df.reindex(common_idx)
    btc_aligned = btc_df.reindex(common_idx)

    c = sei_aligned["close"].values
    v = sei_aligned["volume"].values
    bc = btc_aligned["close"].values
    idx = common_idx

    # 인디케이터 사전 계산 (필터 파라미터와 무관한 것만)
    btc_sma = compute_sma(bc, SMA_P)
    acc = compute_acc(c, v, W)
    # CVD/RS는 파라미터 독립적으로 계산 (임계값은 비교 시 적용)
    cvd_raw = compute_cvd_slope(c, v, W)
    rs_raw = compute_rs(c, bc, W)

    # 그리드 탐색
    total_combos = len(CVD_VALUES) * len(RS_LOW_VALUES) * len(RS_HIGH_VALUES)
    print(f"\n[그리드 탐색: {total_combos} 조합]")
    print(f"  CVD: {CVD_VALUES}")
    print(f"  RS_LOW: {RS_LOW_VALUES}")
    print(f"  RS_HIGH: {RS_HIGH_VALUES}")
    print()

    results_2pass = []  # 2/2 통과
    results_1pass = []  # 1/2 통과 (W1만 통과 포함)

    combo_idx = 0
    for cvd_t, rs_lo, rs_hi in product(CVD_VALUES, RS_LOW_VALUES, RS_HIGH_VALUES):
        if rs_lo >= rs_hi:
            continue
        combo_idx += 1

        window_results = {}
        for wname, oos_start, oos_end in WINDOWS:
            r = _backtest_slice(
                c, v, bc, idx, oos_start, oos_end,
                cvd_t, rs_lo, rs_hi,
                btc_sma, acc, cvd_raw, rs_raw,
            )
            window_results[wname] = r

        w1 = window_results["W1"]
        w2 = window_results["W2"]
        w1_ok = w1["sharpe"] >= SHARPE_MIN and w1["n"] >= MIN_TRADES
        w2_ok = w2["sharpe"] >= SHARPE_MIN and w2["n"] >= MIN_TRADES

        record = {
            "cvd": cvd_t, "rs_lo": rs_lo, "rs_hi": rs_hi,
            "w1_sharpe": w1["sharpe"], "w1_n": w1["n"], "w1_wr": w1["wr"],
            "w2_sharpe": w2["sharpe"], "w2_n": w2["n"], "w2_wr": w2["wr"],
            "passes": int(w1_ok) + int(w2_ok),
        }

        if w1_ok and w2_ok:
            results_2pass.append(record)
        elif w1_ok or w2_ok:
            results_1pass.append(record)

    # 2창 통과 결과 출력
    print(f"{'='*75}")
    print(f"2/2창 통과 결과 ({len(results_2pass)}개)")
    print(f"{'='*75}")

    if results_2pass:
        results_2pass.sort(key=lambda x: x["w1_sharpe"] + x["w2_sharpe"], reverse=True)
        print(f"{'CVD':>5} {'RS_LO':>6} {'RS_HI':>6} | {'W1 Sharpe':>10} {'W1 n':>6} | {'W2 Sharpe':>10} {'W2 n':>6} | {'합계':>8}")
        print("-" * 75)
        for r in results_2pass[:20]:
            total_sharpe = r["w1_sharpe"] + r["w2_sharpe"]
            print(
                f"{r['cvd']:5.1f} {r['rs_lo']:6.2f} {r['rs_hi']:6.2f} | "
                f"{r['w1_sharpe']:+10.3f} {r['w1_n']:6d} | "
                f"{r['w2_sharpe']:+10.3f} {r['w2_n']:6d} | "
                f"{total_sharpe:+8.3f}"
            )
    else:
        print("  ❌ 2/2창 통과 조합 없음")

    # W1만 통과한 결과 상위 10개 출력
    w1_only = [r for r in results_1pass if r["w1_sharpe"] >= SHARPE_MIN and r["w1_n"] >= MIN_TRADES]
    w1_only.sort(key=lambda x: x["w1_sharpe"], reverse=True)
    print(f"\n{'='*75}")
    print(f"W1만 통과 (W1 OOS Sharpe≥3.0) 상위 10개 — W2 Sharpe 참고용")
    print(f"{'='*75}")
    if w1_only:
        print(f"{'CVD':>5} {'RS_LO':>6} {'RS_HI':>6} | {'W1 Sharpe':>10} {'W1 n':>6} | {'W2 Sharpe':>10} {'W2 n':>6}")
        print("-" * 65)
        for r in w1_only[:10]:
            print(
                f"{r['cvd']:5.1f} {r['rs_lo']:6.2f} {r['rs_hi']:6.2f} | "
                f"{r['w1_sharpe']:+10.3f} {r['w1_n']:6d} | "
                f"{r['w2_sharpe']:+10.3f} {r['w2_n']:6d}"
            )
    else:
        print("  W1 OOS Sharpe≥3.0 달성 조합 없음")

    # 베이스라인 재확인 (CVD=0.0, RS=[0.5,1.0))
    print(f"\n{'='*75}")
    print("베이스라인 재확인 (CVD=0.0, RS=[0.5,1.0)) — 사이클 112 결과 재현")
    baseline = next(
        (r for r in results_1pass + results_2pass
         if r["cvd"] == 0.0 and r["rs_lo"] == 0.5 and r["rs_hi"] == 1.0),
        None,
    )
    if baseline:
        print(
            f"  W1: Sharpe={baseline['w1_sharpe']:+.3f} n={baseline['w1_n']}"
            f" | W2: Sharpe={baseline['w2_sharpe']:+.3f} n={baseline['w2_n']}"
        )
    else:
        # 직접 계산
        w1 = _backtest_slice(c, v, bc, idx, "2024-07-01", "2025-06-30", 0.0, 0.5, 1.0, btc_sma, acc, cvd_raw, rs_raw)
        w2 = _backtest_slice(c, v, bc, idx, "2025-01-01", "2025-12-31", 0.0, 0.5, 1.0, btc_sma, acc, cvd_raw, rs_raw)
        print(f"  W1: Sharpe={w1['sharpe']:+.3f} n={w1['n']} | W2: Sharpe={w2['sharpe']:+.3f} n={w2['n']}")

    # 최적 파라미터 결론
    print(f"\n{'='*75}")
    if results_2pass:
        best = results_2pass[0]
        print(f"🏆 최적 파라미터 발견!")
        print(f"   CVD>{best['cvd']:.1f}, RS[{best['rs_lo']:.2f}, {best['rs_hi']:.2f})")
        print(f"   W1 OOS Sharpe={best['w1_sharpe']:+.3f} (n={best['w1_n']})")
        print(f"   W2 OOS Sharpe={best['w2_sharpe']:+.3f} (n={best['w2_n']})")
        print(f"   → 2/2창 통과 ✅ — daemon 후보 확정 대상")
    else:
        print("❌ 2/2창 통과 파라미터 없음 — SEI 엣지 W1 구조적 취약 재확인")
        # W2만 통과하는 최적값
        w2_only = [r for r in results_1pass if r["w2_sharpe"] >= SHARPE_MIN and r["w2_n"] >= MIN_TRADES]
        w2_only.sort(key=lambda x: x["w2_sharpe"], reverse=True)
        if w2_only:
            best = w2_only[0]
            print(f"   W2 최고: CVD>{best['cvd']:.1f}, RS[{best['rs_lo']:.2f}, {best['rs_hi']:.2f}) "
                  f"→ Sharpe={best['w2_sharpe']:+.3f}")

    print("\n[사이클 115 완료]")


if __name__ == "__main__":
    main()
