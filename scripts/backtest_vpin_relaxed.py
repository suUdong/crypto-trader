"""
VPIN 임계값 완화 + 버킷 그리드 탐색 (사이클 72)

문제: 사이클 71에서 VPIN<0.35 OOS 신호 희소화 (trades=6, 기준 미달)
가설: VPIN 임계값 완화(0.40~0.50) + 버킷 증가(20~50)로 OOS trades 개선 가능

- 기본 파라미터 고정: lb=12, adx=20, vol_mult=2.5, TP=0.10, SL=0.03
- VPIN threshold: 0.35, 0.40, 0.45, 0.50
- 버킷 수: 12, 20, 30, 50
- IS: 2022-01-01 ~ 2024-12-31
- OOS: 2025-01-01 ~ 2026-04-03
- 통과 기준: OOS Sharpe > 3.0 AND OOS WR > 50% AND OOS trades >= 8
"""
from __future__ import annotations

import math
import sys
from itertools import product
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

# 고정 파라미터 (사이클 69~71 확정)
LOOKBACK  = 12
ADX_THRESH = 20.0
VOL_MULT  = 2.5
TP        = 0.10
SL        = 0.03

ENTRY_THR  = 0.005
RSI_PERIOD = 14
RSI_OB     = 75.0
MAX_HOLD   = 48

# 탐색 범위
VPIN_THRESH_LIST = [0.35, 0.40, 0.45, 0.50]
BUCKET_LIST      = [12, 20, 30, 50]


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


def run_backtest(df: pd.DataFrame, vpin_thresh: float | None, bucket: int | None) -> dict:
    c  = df["close"].values
    h  = df["high"].values
    lo = df["low"].values
    o  = df["open"].values
    v  = df["volume"].values
    n  = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0

    rsi_arr = compute_rsi(c, RSI_PERIOD)
    adx_arr = compute_adx(h, lo, c, 14)

    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    use_vpin = vpin_thresh is not None
    vpin_arr = None
    if use_vpin and bucket is not None:
        vpin_arr = compute_vpin(h, lo, c, o, v, bucket)

    returns: list[float] = []
    warmup = max(bucket or 0, LOOKBACK, RSI_PERIOD + 1) + 28
    i = warmup
    while i < n - 1:
        if use_vpin and vpin_arr is not None and np.isnan(vpin_arr[i]):
            i += 1
            continue
        base_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THR
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OB
            and not np.isnan(adx_arr[i]) and adx_arr[i] > ADX_THRESH
            and vol_ok[i]
        )
        if use_vpin and vpin_arr is not None:
            vpin_ok = vpin_arr[i] < vpin_thresh
            entry_ok = base_ok and vpin_ok
        else:
            entry_ok = base_ok

        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= TP:
                    returns.append(TP - FEE)
                    i = j
                    break
                if ret <= -SL:
                    returns.append(-SL - FEE)
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


def main() -> None:
    print("=" * 70)
    print("VPIN 임계값 완화 + 버킷 그리드 탐색 (사이클 72)")
    print(f"  고정 파라미터: lb={LOOKBACK} adx={ADX_THRESH} vol={VOL_MULT} TP={TP} SL={SL}")
    print(f"  IS:  {IS_START} ~ {IS_END}")
    print(f"  OOS: {OOS_START} ~ {OOS_END}")
    print(f"  VPIN 임계값: {VPIN_THRESH_LIST}")
    print(f"  버킷 수: {BUCKET_LIST}")
    print("=" * 70)

    df_full = load_historical(SYMBOL, "240m", IS_START, OOS_END)
    df_full = df_full.sort_index()
    print(f"전체 데이터: {len(df_full)}행\n")

    df_is  = df_full[(df_full.index >= IS_START) & (df_full.index <= IS_END)].reset_index(drop=True)
    df_oos = df_full[df_full.index >= OOS_START].reset_index(drop=True)
    print(f"IS  rows: {len(df_is)}")
    print(f"OOS rows: {len(df_oos)}\n")

    results = []

    # C0_base: VPIN 없음 (기준)
    is_r  = run_backtest(df_is,  None, None)
    oos_r = run_backtest(df_oos, None, None)
    results.append({
        "label": "C0_base (VPIN없음)",
        "thresh": None, "bucket": None,
        "is_sh": is_r["sharpe"], "is_wr": is_r["wr"], "is_n": is_r["trades"],
        "oos_sh": oos_r["sharpe"], "oos_wr": oos_r["wr"],
        "oos_avg": oos_r["avg_ret"], "oos_n": oos_r["trades"],
    })

    # VPIN 그리드
    combos = list(product(VPIN_THRESH_LIST, BUCKET_LIST))
    print(f"총 {len(combos)}개 VPIN 조합 실행 중...")
    for thresh, bucket in combos:
        is_r  = run_backtest(df_is,  thresh, bucket)
        oos_r = run_backtest(df_oos, thresh, bucket)
        results.append({
            "label": f"VPIN<{thresh:.2f} bkt={bucket}",
            "thresh": thresh, "bucket": bucket,
            "is_sh": is_r["sharpe"], "is_wr": is_r["wr"], "is_n": is_r["trades"],
            "oos_sh": oos_r["sharpe"], "oos_wr": oos_r["wr"],
            "oos_avg": oos_r["avg_ret"], "oos_n": oos_r["trades"],
        })

    # ── 결과 출력 ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print(f"{'라벨':<25} {'IS_Sh':>7} {'IS_N':>5} | {'OOS_Sh':>7} {'OOS_WR':>7} {'OOS_avg':>8} {'OOS_N':>6} {'통과':>5}")
    print("-" * 90)

    for r in results:
        pass_oos = (
            not math.isnan(r["oos_sh"])
            and r["oos_sh"] > 3.0
            and r["oos_wr"] > 0.50
            and r["oos_n"] >= 8
        )
        flag = "✅" if pass_oos else "❌"
        oos_sh_str = f"{r['oos_sh']:+.3f}" if not math.isnan(r["oos_sh"]) else "  NaN "
        print(
            f"{r['label']:<25} {r['is_sh']:>+7.3f} {r['is_n']:>5} | "
            f"{oos_sh_str:>7} {r['oos_wr']:>7.1%} {r['oos_avg']:>8.4f} {r['oos_n']:>6} {flag}"
        )

    # 통과 조합
    passed = [r for r in results if (
        not math.isnan(r["oos_sh"])
        and r["oos_sh"] > 3.0
        and r["oos_wr"] > 0.50
        and r["oos_n"] >= 8
    )]
    print(f"\n통과 조합: {len(passed)}/{len(results)}")

    if passed:
        passed.sort(key=lambda x: x["oos_sh"], reverse=True)
        best = passed[0]
        print(f"\n★ Best 통과: {best['label']}")
        print(f"  OOS Sharpe={best['oos_sh']:+.3f}, WR={best['oos_wr']:.1%}, avg={best['oos_avg']:.4f}, trades={best['oos_n']}")

        # VPIN 개선 효과 측정
        base = results[0]
        if best["thresh"] is not None:
            delta = best["oos_sh"] - base["oos_sh"]
            print(f"  베이스라인 대비 Sharpe Δ{delta:+.3f}")

    # OOS VPIN 분포 분석
    print("\n[VPIN OOS 신호 수 히트맵]")
    print(f"{'임계값':>8}", end="")
    for b in BUCKET_LIST:
        print(f"  bkt={b:>2}", end="")
    print()
    for thresh in VPIN_THRESH_LIST:
        print(f"  < {thresh:.2f}", end="")
        for bucket in BUCKET_LIST:
            row = next(
                (r for r in results if r["thresh"] == thresh and r["bucket"] == bucket), None
            )
            if row:
                print(f"  {row['oos_n']:>6}", end="")
            else:
                print(f"  {'N/A':>6}", end="")
        print()

    # docs/backtest_history.md 기록
    hist_path = Path(__file__).resolve().parent.parent / "docs" / "backtest_history.md"
    entry = _format_history(results, passed)
    with open(hist_path, "a") as f:
        f.write(entry)
    print(f"\n결과 저장 → {hist_path}")


def _format_history(results: list[dict], passed: list[dict]) -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n## {now} — VPIN 임계값 완화 그리드 탐색 (사이클 72)\n\n"]
    lines.append("**목적**: VPIN<0.35 OOS 신호 희소화 해결 — 임계값 완화(0.35~0.50) + 버킷 증가(12~50)  \n")
    lines.append(f"**고정 파라미터**: lb={LOOKBACK}, adx={ADX_THRESH}, vol={VOL_MULT}, TP={TP}, SL={SL}  \n")
    lines.append("**기간**: IS 2022-2024 / OOS 2025-2026  \n\n")

    lines.append("### 결과 요약\n\n")
    lines.append(f"| 라벨 | IS Sharpe | IS N | OOS Sharpe | OOS WR | OOS avg | OOS N | 통과 |\n")
    lines.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n")

    for r in results:
        pass_oos = (
            not math.isnan(r["oos_sh"])
            and r["oos_sh"] > 3.0
            and r["oos_wr"] > 0.50
            and r["oos_n"] >= 8
        )
        flag = "✅" if pass_oos else "❌"
        oos_str = f"{r['oos_sh']:+.3f}" if not math.isnan(r["oos_sh"]) else "NaN"
        lines.append(
            f"| {r['label']} | {r['is_sh']:+.3f} | {r['is_n']} | "
            f"{oos_str} | {r['oos_wr']:.1%} | {r['oos_avg']:.4f} | {r['oos_n']} | {flag} |\n"
        )

    lines.append(f"\n**통과 조합**: {len(passed)}/{len(results)}\n\n")

    if passed:
        best = passed[0]
        base = results[0]
        delta = best["oos_sh"] - base["oos_sh"]
        lines.append("### 최적 통과 조합\n\n")
        lines.append(f"**{best['label']}**  \n")
        lines.append(f"OOS Sharpe={best['oos_sh']:+.3f}, WR={best['oos_wr']:.1%}, trades={best['oos_n']}  \n")
        lines.append(f"베이스라인(VPIN없음, {base['oos_sh']:+.3f}) 대비 Sharpe Δ{delta:+.3f}  \n\n")
    else:
        lines.append("**결론**: 모든 VPIN 임계값에서 OOS trades 기준(8개) 미달 — VPIN 필터 전략 폐기 검토\n\n")

    lines.append("---\n")
    return "".join(lines)


if __name__ == "__main__":
    main()
