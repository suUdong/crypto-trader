"""
ETH C2_VPIN vs C0_base walk-forward 비교 (사이클 81)
- 목적: 슬라이딩 2/3 통과한 C2_VPIN과 C0_base 중 daemon 최종 후보 결정
        VPIN(bkt=12, thr<0.40) 추가가 실질 Sharpe 향상인지 노이즈인지 판단
- 방법: 단일 walk-forward (IS: 2022-05~2024-12 / OOS: 2025-01~2026-04)
- 후보:
    adx=20 계열 (슬라이딩 테스트 기준):
      C2_VPIN_adx20: lb=12, adx=20, vol=2.5, VPIN bkt=12 thr<0.40
      C0_base_adx20: lb=12, adx=20, vol=2.5, VPIN 없음
    adx=25 계열 (SOL/XRP 기준):
      C2_VPIN_adx25: lb=12, adx=25, vol=2.0, VPIN bkt=12 thr<0.40
      C0_base_adx25: lb=12, adx=25, vol=2.0, VPIN 없음
- 통과 기준: OOS Sharpe > 3.0 && WR > 45% && trades >= 6
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
FEE    = 0.0005

IS_START  = "2022-05-01"
IS_END    = "2024-12-31"
OOS_START = "2025-01-01"
OOS_END   = "2026-04-04"

CANDIDATES = [
    # adx=20 계열 (슬라이딩 윈도우 동일 설정)
    {
        "label":       "C2_VPIN_adx20 (bkt=12 thr<0.40)",
        "lookback":    12,
        "adx":         20.0,
        "vol_mult":    2.5,
        "tp":          0.10,
        "sl":          0.03,
        "vpin_thresh": 0.40,
        "bucket":      12,
    },
    {
        "label":       "C0_base_adx20 (VPIN 없음)",
        "lookback":    12,
        "adx":         20.0,
        "vol_mult":    2.5,
        "tp":          0.10,
        "sl":          0.03,
        "vpin_thresh": None,
        "bucket":      None,
    },
    # adx=25 계열 (SOL/XRP daemon 기준 파라미터)
    {
        "label":       "C2_VPIN_adx25 (bkt=12 thr<0.40)",
        "lookback":    12,
        "adx":         25.0,
        "vol_mult":    2.0,
        "tp":          0.10,
        "sl":          0.03,
        "vpin_thresh": 0.40,
        "bucket":      12,
    },
    {
        "label":       "C0_base_adx25 (VPIN 없음)",
        "lookback":    12,
        "adx":         25.0,
        "vol_mult":    2.0,
        "tp":          0.10,
        "sl":          0.03,
        "vpin_thresh": None,
        "bucket":      None,
    },
]

ENTRY_THRESHOLD = 0.005
RSI_PERIOD      = 14
RSI_OVERBOUGHT  = 75.0
MAX_HOLD        = 48

PASS_SHARPE = 3.0
PASS_WR     = 0.45
PASS_TRADES = 6


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
    """VPIN BVC 방법 (분모=high-low)."""
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


def backtest(df: pd.DataFrame, p: dict) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    o  = df["open"].values
    v  = df["volume"].values
    n  = len(c)

    lb       = p["lookback"]
    adx_th   = p["adx"]
    vol_mult = p["vol_mult"]
    tp       = p["tp"]
    sl       = p["sl"]
    vpin_th  = p["vpin_thresh"]
    bucket   = p["bucket"]

    mom = np.full(n, np.nan)
    mom[lb:] = c[lb:] / c[:n-lb] - 1.0

    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_calc(h, lo, c, 14)
    vol_ma  = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok  = v > vol_mult * vol_ma

    use_vpin = vpin_th is not None
    if use_vpin:
        vpin_arr = compute_vpin(h, lo, c, o, v, bucket)

    warmup = max(bucket or 0, lb, RSI_PERIOD + 1) + 28
    returns: list[float] = []
    i = warmup
    while i < n - 1:
        if use_vpin and np.isnan(vpin_arr[i]):
            i += 1
            continue

        base_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_th
            and vol_ok[i]
        )
        entry_ok = base_ok and (not use_vpin or vpin_arr[i] < vpin_th)

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
                j = min(i + MAX_HOLD, n - 1)
                returns.append(c[j] / buy - 1 - FEE)
                i = j
        i += 1

    if len(returns) == 0:
        return {"sharpe": float("nan"), "wr": float("nan"), "trades": 0, "avg_ret": float("nan")}

    rets = np.array(returns)
    sharpe = (rets.mean() / (rets.std() + 1e-9)) * np.sqrt(len(rets))
    wr     = (rets > 0).mean()
    return {
        "sharpe":   round(sharpe, 3),
        "wr":       round(wr, 4),
        "trades":   len(rets),
        "avg_ret":  round(rets.mean() * 100, 3),
    }


def run_walkforward(df_all: pd.DataFrame, p: dict) -> dict:
    df_is  = df_all[(df_all.index >= IS_START) & (df_all.index <= IS_END)]
    df_oos = df_all[(df_all.index >= OOS_START) & (df_all.index <= OOS_END)]
    is_res  = backtest(df_is, p)
    oos_res = backtest(df_oos, p)
    return {"is": is_res, "oos": oos_res}


def passes(r: dict) -> bool:
    return (
        not np.isnan(r["sharpe"])
        and r["sharpe"] >= PASS_SHARPE
        and r["wr"] >= PASS_WR
        and r["trades"] >= PASS_TRADES
    )


def main() -> None:
    print(f"ETH C2_VPIN vs C0_base walk-forward 비교 (사이클 81)")
    print(f"IS: {IS_START} ~ {IS_END}  |  OOS: {OOS_START} ~ {OOS_END}")
    print(f"통과 기준: Sharpe > {PASS_SHARPE}, WR > {PASS_WR*100:.0f}%, T >= {PASS_TRADES}")
    print("=" * 80)

    df_all = load_historical(SYMBOL, "240m")
    print(f"데이터: {len(df_all)}행  ({df_all.index[0].date()} ~ {df_all.index[-1].date()})")
    print()

    results = []
    for p in CANDIDATES:
        wf = run_walkforward(df_all, p)
        is_r  = wf["is"]
        oos_r = wf["oos"]
        ok    = passes(oos_r)
        results.append((p["label"], is_r, oos_r, ok))

        print(f"[{p['label']}]")
        print(f"  IS : Sh={is_r['sharpe']:+.3f}  WR={is_r['wr']*100:.1f}%  T={is_r['trades']}  avg={is_r['avg_ret']:+.2f}%")
        print(f"  OOS: Sh={oos_r['sharpe']:+.3f}  WR={oos_r['wr']*100:.1f}%  T={oos_r['trades']}  avg={oos_r['avg_ret']:+.2f}%  {'✅ PASS' if ok else '❌ FAIL'}")
        print()

    # VPIN 기여 델타 계산
    print("=" * 80)
    print("VPIN 기여 분석 (Δ = VPIN - base):")
    print()

    # adx=20 계열 비교
    vpin20  = next(r for r in results if "adx20" in r[0] and "VPIN" in r[0])
    base20  = next(r for r in results if "adx20" in r[0] and "base" in r[0])
    delta_sh20 = vpin20[2]["sharpe"] - base20[2]["sharpe"] if not np.isnan(vpin20[2]["sharpe"]) and not np.isnan(base20[2]["sharpe"]) else float("nan")
    delta_wr20 = vpin20[2]["wr"] - base20[2]["wr"]
    print(f"adx=20 계열:")
    print(f"  C2_VPIN OOS Sh={vpin20[2]['sharpe']:+.3f} WR={vpin20[2]['wr']*100:.1f}% T={vpin20[2]['trades']}")
    print(f"  C0_base OOS Sh={base20[2]['sharpe']:+.3f} WR={base20[2]['wr']*100:.1f}% T={base20[2]['trades']}")
    print(f"  Δ Sharpe={delta_sh20:+.3f}  Δ WR={delta_wr20*100:+.1f}%  Δ trades={vpin20[2]['trades']-base20[2]['trades']}")
    print()

    # adx=25 계열 비교
    vpin25  = next(r for r in results if "adx25" in r[0] and "VPIN" in r[0])
    base25  = next(r for r in results if "adx25" in r[0] and "base" in r[0])
    delta_sh25 = vpin25[2]["sharpe"] - base25[2]["sharpe"] if not np.isnan(vpin25[2]["sharpe"]) and not np.isnan(base25[2]["sharpe"]) else float("nan")
    delta_wr25 = vpin25[2]["wr"] - base25[2]["wr"]
    print(f"adx=25 계열:")
    print(f"  C2_VPIN OOS Sh={vpin25[2]['sharpe']:+.3f} WR={vpin25[2]['wr']*100:.1f}% T={vpin25[2]['trades']}")
    print(f"  C0_base OOS Sh={base25[2]['sharpe']:+.3f} WR={base25[2]['wr']*100:.1f}% T={base25[2]['trades']}")
    print(f"  Δ Sharpe={delta_sh25:+.3f}  Δ WR={delta_wr25*100:+.1f}%  Δ trades={vpin25[2]['trades']-base25[2]['trades']}")
    print()

    # 최종 판단
    print("=" * 80)
    print("최종 판단:")
    pass_count = sum(1 for r in results if r[3])

    if abs(delta_sh20) < 1.0 and abs(delta_sh25) < 1.0:
        print("  → VPIN 기여 Δ Sharpe < 1.0 (노이즈 범위) — C0_base 선택 권장 (trades 더 많음)")
        daemon_choice = "C0_base"
    elif delta_sh20 > 1.0 or delta_sh25 > 1.0:
        print("  → VPIN Δ Sharpe > 1.0 — C2_VPIN 실질 기여 확인, daemon 후보로 유지")
        daemon_choice = "C2_VPIN"
    else:
        print("  → adx 계열 간 결과 불일치 — 추가 검토 필요")
        daemon_choice = "미결"

    print(f"  → daemon 후보 권장: {daemon_choice}")
    print()


if __name__ == "__main__":
    main()
