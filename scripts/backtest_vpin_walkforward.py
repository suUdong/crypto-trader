"""
ETH momentum+VPIN_fixed walk-forward 검증 (사이클 71)

- 사이클 70 확정 파라미터:
    안정판: safe VPIN<0.35 bucket=12 lb=12 adx=20 vol=2.5 TP=0.10 SL=0.03
    고성능: safe VPIN<0.30 bucket=20 lb=12 adx=20 vol=2.5 TP=0.12 SL=0.03
- In-sample:    2022-01-01 ~ 2024-12-31
- Out-of-sample: 2025-01-01 ~ 2026-04-03
- 검증 기준: OOS Sharpe > 3.0 && OOS WR > 50% && OOS trades >= 8
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
FEE    = 0.0005

IS_START  = "2022-01-01"
IS_END    = "2024-12-31"
OOS_START = "2025-01-01"
OOS_END   = "2026-04-03"

# 후보 파라미터 (사이클 70 최적)
CANDIDATES = [
    {
        "label":      "C1_stable (사이클70 안정판)",
        "lookback":   12,
        "adx":        20.0,
        "vol_mult":   2.5,
        "tp":         0.10,
        "sl":         0.03,
        "vpin_thresh": 0.35,
        "direction":  "safe",
        "bucket":     12,
    },
    {
        "label":      "C2_perf (사이클70 고성능)",
        "lookback":   12,
        "adx":        20.0,
        "vol_mult":   2.5,
        "tp":         0.12,
        "sl":         0.03,
        "vpin_thresh": 0.30,
        "direction":  "safe",
        "bucket":     20,
    },
    {
        "label":      "C0_base (VPIN 없음, 비교용)",
        "lookback":   12,
        "adx":        20.0,
        "vol_mult":   2.5,
        "tp":         0.10,
        "sl":         0.03,
        "vpin_thresh": None,
        "direction":  None,
        "bucket":     None,
    },
]

ENTRY_THR  = 0.005
RSI_PERIOD = 14
RSI_OB     = 75.0
MAX_HOLD   = 48


# ── 지표 함수 ──────────────────────────────────────────────────────────────────

def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
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
    with np.errstate(invalid="ignore", divide="ignore"):
        rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr   = np.maximum(highs[1:] - lows[1:],
           np.maximum(np.abs(highs[1:] - closes[:-1]),
                      np.abs(lows[1:]  - closes[:-1])))
    dm_p = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
                    np.maximum(highs[1:] - highs[:-1], 0.0), 0.0)
    dm_m = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
                    np.maximum(lows[:-1] - lows[1:], 0.0), 0.0)
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period-1] = tr[:period].sum()
    dip_s[period-1] = dm_p[:period].sum()
    dim_s[period-1] = dm_m[:period].sum()
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


def compute_vpin(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    opens: np.ndarray,
    volumes: np.ndarray,
    bucket_count: int = 20,
) -> np.ndarray:
    """VPIN BVC 방법 (분모=high-low, 수정판)."""
    n = len(closes)
    result = np.full(n, np.nan)
    price_range = highs - lows
    with np.errstate(invalid="ignore", divide="ignore"):
        z_scores = np.where(price_range > 0, (closes - opens) / price_range, 0.0)
    buy_frac = 0.5 * (1.0 + np.tanh(z_scores * 0.7978))
    buy_vol  = volumes * buy_frac
    sell_vol = volumes * (1.0 - buy_frac)
    imbal    = np.abs(buy_vol - sell_vol)
    imbal_cumsum = np.concatenate([[0.0], np.cumsum(imbal)])
    vol_cumsum   = np.concatenate([[0.0], np.cumsum(volumes)])
    for i in range(bucket_count, n):
        total_vol = vol_cumsum[i] - vol_cumsum[i - bucket_count]
        if total_vol > 0:
            result[i] = (imbal_cumsum[i] - imbal_cumsum[i - bucket_count]) / total_vol
    return result


# ── 단일 기간 백테스트 ─────────────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame, p: dict) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    o  = df["open"].values
    v  = df["volume"].values
    n  = len(c)

    lookback  = p["lookback"]
    adx_th    = p["adx"]
    vol_mult  = p["vol_mult"]
    tp        = p["tp"]
    sl        = p["sl"]
    vpin_th   = p["vpin_thresh"]
    direction = p["direction"]
    bucket    = p["bucket"]

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n - lookback] - 1.0

    rsi_arr = compute_rsi(c, RSI_PERIOD)
    adx_arr = compute_adx(h, lo, c, 14)

    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > vol_mult * vol_ma

    use_vpin = vpin_th is not None
    if use_vpin:
        vpin_arr = compute_vpin(h, lo, c, o, v, bucket)

    returns: list[float] = []
    warmup = max(bucket or 0, lookback, RSI_PERIOD + 1) + 28
    i = warmup
    while i < n - 1:
        if use_vpin and np.isnan(vpin_arr[i]):
            i += 1
            continue
        base_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THR
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OB
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_th
            and vol_ok[i]
        )
        if use_vpin:
            if direction == "safe":
                vpin_ok = vpin_arr[i] < vpin_th
            else:
                vpin_ok = vpin_arr[i] > vpin_th
            entry_ok = base_ok and vpin_ok
        else:
            entry_ok = base_ok

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
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": len(returns)}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


# ── 메인 ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("ETH momentum+VPIN_fixed walk-forward 검증 (사이클 71)")
    print(f"  IS:  {IS_START} ~ {IS_END}")
    print(f"  OOS: {OOS_START} ~ {OOS_END}")
    print("=" * 70)

    df_full = load_historical(SYMBOL, "240m", IS_START, OOS_END)
    df_full = df_full.sort_index()
    print(f"전체 데이터: {len(df_full)}행 ({df_full.index[0]} ~ {df_full.index[-1]})\n")

    df_is  = df_full[(df_full.index >= IS_START) & (df_full.index <= IS_END)].reset_index(drop=True)
    df_oos = df_full[df_full.index >= OOS_START].reset_index(drop=True)
    print(f"IS  rows: {len(df_is)}")
    print(f"OOS rows: {len(df_oos)}\n")

    results = []
    for p in CANDIDATES:
        is_r  = run_backtest(df_is,  p)
        oos_r = run_backtest(df_oos, p)

        pass_oos = (
            not math.isnan(oos_r["sharpe"])
            and oos_r["sharpe"] > 3.0
            and oos_r["wr"]     > 0.50
            and oos_r["trades"] >= 8
        )
        results.append({
            "label":       p["label"],
            "is_sharpe":   is_r["sharpe"],
            "is_wr":       is_r["wr"],
            "is_trades":   is_r["trades"],
            "oos_sharpe":  oos_r["sharpe"],
            "oos_wr":      oos_r["wr"],
            "oos_avg_ret": oos_r["avg_ret"],
            "oos_trades":  oos_r["trades"],
            "pass":        pass_oos,
        })

    # ── 결과 출력 ──────────────────────────────────────────────────────────────
    print("=" * 70)
    print(f"{'라벨':<35} {'IS_Sh':>7} {'IS_WR':>6} {'IS_N':>5} | {'OOS_Sh':>7} {'OOS_WR':>7} {'OOS_avg':>8} {'OOS_N':>5} {'통과':>5}")
    print("-" * 70)
    for r in results:
        is_sh  = f"{r['is_sharpe']:+.3f}"  if not math.isnan(r['is_sharpe'])  else "  NaN"
        oos_sh = f"{r['oos_sharpe']:+.3f}" if not math.isnan(r['oos_sharpe']) else "  NaN"
        chk = "✅" if r["pass"] else "❌"
        print(
            f"{r['label']:<35} {is_sh:>7} {r['is_wr']:>5.1%} {r['is_trades']:>5} | "
            f"{oos_sh:>7} {r['oos_wr']:>6.1%} {r['oos_avg_ret']:>+8.3%} {r['oos_trades']:>5} {chk}"
        )
    print("=" * 70)

    passed = [r for r in results if r["pass"]]
    if passed:
        best = max(passed, key=lambda x: x["oos_sharpe"])
        print(f"\n✅ walk-forward 통과: {best['label']}")
        print(f"   OOS Sharpe={best['oos_sharpe']:+.3f}, WR={best['oos_wr']:.1%}, trades={best['oos_trades']}")
        print(f"   IS  Sharpe={best['is_sharpe']:+.3f}, WR={best['is_wr']:.1%}, trades={best['is_trades']}")
        print("\n→ daemon momentum_eth_wallet 재활성화 조건 충족 가능 (BULL 레짐 전환 시)")
    else:
        print("\n❌ 모든 후보 OOS 검증 실패 — daemon 반영 보류")


if __name__ == "__main__":
    main()
