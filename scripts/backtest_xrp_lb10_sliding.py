"""
XRP momentum lb=10 슬라이딩 윈도우 3구간 검증 (사이클 79)
- 목적: walk-forward에서 Sh+15.2(WR=55.6%, T=18) 통과한 lb=10 adx=25의
  슬라이딩 안정성 확인 — 통과 시 C8(lb=8)에서 lb=10으로 업그레이드
- 비교: C8(lb=8, adx=25) 기준선 포함
  W1: IS=2022-05~2023-12 / OOS=2024-01~2024-12
  W2: IS=2022-05~2024-12 / OOS=2025-01~2025-12
  W3: IS=2022-05~2025-12 / OOS=2026-01~2026-04
- 통과 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6
- 2/3 이상 통과 시 daemon 후보 확정
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-XRP"
FEE    = 0.0005

WINDOWS = [
    {"name": "W1", "is_start": "2022-05-01", "is_end": "2023-12-31", "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2022-05-01", "is_end": "2024-12-31", "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"name": "W3", "is_start": "2022-05-01", "is_end": "2025-12-31", "oos_start": "2026-01-01", "oos_end": "2026-04-03"},
]

CANDIDATES = [
    {"lookback":  8, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "C8 lb=8 adx=25 (기준)"},
    {"lookback": 10, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "★C_lb10 lb=10 adx=25"},
    {"lookback": 10, "adx": 30.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "C_lb10_adx30"},
    {"lookback": 12, "adx": 25.0, "vol_mult": 2.0, "tp": 0.12, "sl": 0.04, "label": "C_lb12 (비교용)"},
]

ENTRY_THRESHOLD = 0.005
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 75.0
MAX_HOLD        = 48


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def adx_calc(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr  = np.maximum(highs[1:] - lows[1:],
          np.maximum(np.abs(highs[1:] - closes[:-1]),
                     np.abs(lows[1:]  - closes[:-1])))
    dm_p = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
                    np.maximum(highs[1:] - highs[:-1], 0.0), 0.0)
    dm_m = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
                    np.maximum(lows[:-1] - lows[1:], 0.0), 0.0)
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period-1]  = tr[:period].sum()
    dip_s[period-1]  = dm_p[:period].sum()
    dim_s[period-1]  = dm_m[:period].sum()
    for i in range(period, n - 1):
        atr_s[i] = atr_s[i-1] - atr_s[i-1] / period + tr[i]
        dip_s[i] = dip_s[i-1] - dip_s[i-1] / period + dm_p[i]
        dim_s[i] = dim_s[i-1] - dim_s[i-1] / period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dip_s / (atr_s + 1e-9)
        di_m = 100 * dim_s / (atr_s + 1e-9)
        dx   = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2*period-2] = dx[period-1:2*period-1].mean()
    for i in range(2*period-1, n-1):
        adx_vals[i] = (adx_vals[i-1] * (period-1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


def backtest(df: pd.DataFrame, lookback: int, adx_thresh: float, vol_mult: float, tp: float, sl: float) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    v  = df["volume"].values
    n  = len(c)

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n-lookback] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_calc(h, lo, c, 14)
    vol_ma  = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok  = v > vol_mult * vol_ma

    returns: list[float] = []
    i = lookback + RSI_PERIOD + 28
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE)
                    i = j
                    break
                if ret <= -sl:
                    returns.append(-sl - FEE)
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def main() -> None:
    print("=" * 80)
    print("XRP momentum lb=10 슬라이딩 윈도우 3구간 검증 (사이클 79)")
    print("목적: walk-forward Sh+15.2 통과 lb=10의 슬라이딩 안정성 확인")
    print("통과 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6")
    print("=" * 80)

    # 데이터 로드
    data_cache: dict[str, pd.DataFrame] = {}
    for w in WINDOWS:
        for key in ["is", "oos"]:
            start = w[f"{key}_start"]
            end   = w[f"{key}_end"]
            cache_key = f"{start}_{end}"
            if cache_key not in data_cache:
                df = load_historical(SYMBOL, "240m", start, end)
                data_cache[cache_key] = df

    print()
    for p in CANDIDATES:
        lb, adx_t, vm, tp, sl = p["lookback"], p["adx"], p["vol_mult"], p["tp"], p["sl"]
        label = p["label"]
        print(f"{'─'*80}")
        print(f"▶ {label}")
        print(f"  lb={lb}, adx={adx_t:.0f}, vol={vm}, TP={tp*100:.0f}%, SL={sl*100:.0f}%")
        print(f"  {'창':>4} | {'IS행수':>6} | {'OOS행수':>7} | {'OOS Sharpe':>11} {'OOS WR':>7} {'OOS T':>6} | {'판정':>6}")

        window_results = []
        for w in WINDOWS:
            is_key  = f"{w['is_start']}_{w['is_end']}"
            oos_key = f"{w['oos_start']}_{w['oos_end']}"
            df_is   = data_cache[is_key]
            df_oos  = data_cache[oos_key]

            oos_r = backtest(df_oos, lb, adx_t, vm, tp, sl)

            oos_ok = (
                not np.isnan(oos_r["sharpe"])
                and oos_r["sharpe"] > 3.0
                and oos_r["wr"] > 0.45
                and oos_r["trades"] >= 6
            )
            window_results.append(oos_ok)

            oos_sh = f"{oos_r['sharpe']:+.3f}" if not np.isnan(oos_r["sharpe"]) else "    nan"
            verdict = "✅" if oos_ok else "❌"

            print(
                f"  {w['name']:>4} | {len(df_is):>6} | {len(df_oos):>7} | "
                f"{oos_sh:>11} {oos_r['wr']:>6.1%} {oos_r['trades']:>6} | {verdict:>6}"
            )

        pass_count = sum(window_results)
        overall = "✅ 2/3+ PASS" if pass_count >= 2 else "❌ FAIL"
        print(f"  → {pass_count}/3 통과 : {overall}")

    print()
    print("=" * 80)
    print("결론 요약:")
    print()

    # 결론 재계산
    conclusions = []
    for p in CANDIDATES:
        lb, adx_t, vm, tp, sl = p["lookback"], p["adx"], p["vol_mult"], p["tp"], p["sl"]
        label = p["label"]
        window_results = []
        for w in WINDOWS:
            oos_key = f"{w['oos_start']}_{w['oos_end']}"
            df_oos  = data_cache[oos_key]
            oos_r = backtest(df_oos, lb, adx_t, vm, tp, sl)
            oos_ok = (
                not np.isnan(oos_r["sharpe"])
                and oos_r["sharpe"] > 3.0
                and oos_r["wr"] > 0.45
                and oos_r["trades"] >= 6
            )
            window_results.append(oos_ok)
        pass_count = sum(window_results)
        conclusions.append((label, pass_count, lb, adx_t))
        status = "✅ 통과" if pass_count >= 2 else "❌ 실패"
        print(f"  {status} {label}: {pass_count}/3")

    print()
    # lb=10이 2/3+ 통과했는지 확인
    lb10_result = next((c for c in conclusions if c[2] == 10 and c[3] == 25.0), None)
    c8_result   = next((c for c in conclusions if c[2] == 8  and c[3] == 25.0), None)

    if lb10_result and lb10_result[1] >= 2:
        print("★ XRP 최적 파라미터 업그레이드 권고: lb=8 → lb=10 (adx=25)")
        print("  근거: walk-forward Sh+15.2(WR=55.6%) + 슬라이딩 2/3+ 통과")
        print("  daemon.toml 업데이트 대상: momentum_xrp_wallet lookback 8→10")
    elif lb10_result and lb10_result[1] == 1:
        print("△ lb=10 슬라이딩 1/3 — walk-forward 강하지만 안정성 불충분")
        print("  기존 C8(lb=8, adx=25) 유지 권고")
    else:
        print("× lb=10 슬라이딩 0/3 실패 — walk-forward 결과가 과적합이었을 가능성")
        print("  기존 C8(lb=8, adx=25) 유지")

    if c8_result:
        c8_pass = c8_result[1]
        print(f"\n  기준선 C8(lb=8, adx=25): {c8_pass}/3 통과 (이전 사이클77 확인값: 2/3)")


if __name__ == "__main__":
    main()
