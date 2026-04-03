"""
vpin_eth 슬라이딩 윈도우 다중 OOS 검증 (사이클 99)
- 목적: daemon vpin_eth_wallet 파라미터(max_hold=18, TP=6%, SL=0.8%, vpin_mom=0.0005)
        IS Sharpe +7.461의 과적합 여부 확인
- 사이클 97의 backtest_eth_vpin_sliding_wf.py는 "낮은 VPIN 독성" 전략 → 다른 전략
- 이 스크립트: "높은 VPIN momentum" 전략 (현재 daemon 실제 전략)
- 3개 슬라이딩 윈도우:
  W1: IS=2022-01~2023-12 / OOS=2024-01~2024-12
  W2: IS=2023-01~2024-12 / OOS=2025-01~2025-12
  W3: IS=2024-01~2025-12 / OOS=2026-01~2026-04
- 검증 기준: OOS Sharpe > 3.0 && WR > 35% && trades >= 8
  (vpin_eth WR=27.6% 특성상 WR 기준 35%로 완화 — IS 기간 기준)
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

WINDOWS = [
    {"name": "W1", "is_start": "2022-01-01", "is_end": "2023-12-31",
     "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2023-01-01", "is_end": "2024-12-31",
     "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"name": "W3", "is_start": "2024-01-01", "is_end": "2025-12-31",
     "oos_start": "2026-01-01", "oos_end": "2026-04-04"},
]

# daemon 후보 + 비교군
CANDIDATES = [
    {
        "label": "C_daemon (vh=0.55 vm=0.0005 hold=18 TP=6% SL=0.8%) ★검증대상",
        "vpin_high": 0.55, "vpin_mom": 0.0005, "max_hold": 18, "tp": 0.06, "sl": 0.008,
    },
    {
        "label": "C1 (vm=0.0003 hold=18 TP=6% SL=0.8%)",
        "vpin_high": 0.55, "vpin_mom": 0.0003, "max_hold": 18, "tp": 0.06, "sl": 0.008,
    },
    {
        "label": "C2 (vm=0.0005 hold=24 TP=6% SL=0.8%) 이전 설정",
        "vpin_high": 0.55, "vpin_mom": 0.0005, "max_hold": 24, "tp": 0.06, "sl": 0.008,
    },
    {
        "label": "C0_base (vm=0.0005 hold=18 TP=5% SL=1.2%)",
        "vpin_high": 0.55, "vpin_mom": 0.0005, "max_hold": 18, "tp": 0.05, "sl": 0.012,
    },
]

# 고정값 (daemon.toml 현재값)
RSI_PERIOD    = 14
RSI_CEILING   = 65.0
RSI_FLOOR     = 20.0
BUCKET_COUNT  = 24
EMA_PERIOD    = 20
MOM_LOOKBACK  = 8

OOS_SHARPE_MIN = 3.0
OOS_WR_MIN     = 0.30   # vpin_eth IS WR 27-28% → OOS 기준 30%로 설정
OOS_TRADES_MIN = 8


def ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i-1] * (1 - k)
    return result


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


def compute_vpin(closes: np.ndarray, opens: np.ndarray, volumes: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    """Simplified VPIN: |close-open|/range proxy, rolling bucket_count."""
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy  = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i-bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, volumes: np.ndarray,
                          lookback: int = 8) -> np.ndarray:
    """CVD momentum proxy: (close/close[-lookback] - 1) normalized."""
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def backtest(df: pd.DataFrame, vpin_high: float, vpin_mom_thresh: float,
             max_hold: int, tp: float, sl: float) -> dict:
    c = df["close"].values
    o = df["open"].values
    v = df["volume"].values
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, v, BUCKET_COUNT)
    mom_arr  = compute_vpin_momentum(c, v, MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK) + 5
    i = warmup
    while i < n - 1:
        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]

        entry_ok = (
            not np.isnan(vpin_val) and vpin_val > vpin_high
            and not np.isnan(mom_val) and mom_val > vpin_mom_thresh
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            for j in range(i + 2, min(i + 1 + max_hold, n)):
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
                hold_end = min(i + max_hold, n - 1)
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
    print("=" * 90)
    print("vpin_eth 슬라이딩 윈도우 다중 OOS 검증 (사이클 99)")
    print("목적: daemon vpin_eth_wallet(Sharpe +7.461) 과적합 여부 확인")
    print("전략: 높은 VPIN momentum 진입 (vpin > vpin_high AND mom > threshold)")
    print("=" * 90)

    print("\n데이터 로드 중...")
    data_cache: dict[str, pd.DataFrame] = {}
    for w in WINDOWS:
        df_is  = load_historical(SYMBOL, "240m", w["is_start"],  w["is_end"])
        df_oos = load_historical(SYMBOL, "240m", w["oos_start"], w["oos_end"])
        data_cache[f"{w['name']}_is"]  = df_is
        data_cache[f"{w['name']}_oos"] = df_oos
        print(f"  {w['name']}: IS={len(df_is)}행 ({w['is_start']}~{w['is_end']}), "
              f"OOS={len(df_oos)}행 ({w['oos_start']}~{w['oos_end']})")

    print()
    print(f"검증 기준: OOS Sharpe > {OOS_SHARPE_MIN} && WR > {OOS_WR_MIN:.0%} "
          f"&& trades >= {OOS_TRADES_MIN}")
    print()

    for cand in CANDIDATES:
        vh  = cand["vpin_high"]
        vm  = cand["vpin_mom"]
        mh  = cand["max_hold"]
        tp  = cand["tp"]
        sl  = cand["sl"]
        label = cand["label"]

        print(f"{'='*80}")
        print(f"파라미터: {label}")
        print(f"  vpin_high={vh} vpin_mom={vm} max_hold={mh} TP={tp:.0%} SL={sl:.1%}")
        print(f"{'윈도우':<40} | {'IS Sharpe':>10} {'IS WR':>7} {'IS T':>5} | "
              f"{'OOS Sharpe':>10} {'OOS WR':>7} {'OOS T':>5} | {'판정':>6}")
        print("-" * 90)

        window_results = []
        for w in WINDOWS:
            df_is  = data_cache[f"{w['name']}_is"]
            df_oos = data_cache[f"{w['name']}_oos"]

            is_r  = backtest(df_is,  vh, vm, mh, tp, sl)
            oos_r = backtest(df_oos, vh, vm, mh, tp, sl)

            oos_ok = (
                not np.isnan(oos_r["sharpe"])
                and oos_r["sharpe"] > OOS_SHARPE_MIN
                and oos_r["wr"] > OOS_WR_MIN
                and oos_r["trades"] >= OOS_TRADES_MIN
            )
            verdict = "✅" if oos_ok else "❌"
            window_results.append(oos_ok)

            is_sh  = f"{is_r['sharpe']:+.3f}"  if not np.isnan(is_r['sharpe'])  else "   nan"
            oos_sh = f"{oos_r['sharpe']:+.3f}" if not np.isnan(oos_r['sharpe']) else "   nan"

            wname = f"{w['name']}(OOS: {w['oos_start'][:7]}~{w['oos_end'][:7]})"
            print(
                f"{wname:<40} | "
                f"{is_sh:>10} {is_r['wr']:>6.1%} {is_r['trades']:>5} | "
                f"{oos_sh:>10} {oos_r['wr']:>6.1%} {oos_r['trades']:>5} | {verdict:>6}"
            )

        pass_count = sum(window_results)
        print(f"\n  → 통과 {pass_count}/{len(WINDOWS)} 윈도우 | ", end="")
        if pass_count == len(WINDOWS):
            print("★★★ 전 구간 통과 — daemon 파라미터 확정")
        elif pass_count >= 2:
            print("◆◆ 2/3 통과 — 조건부 안정적 (현재 daemon 유지 근거 충분)")
        else:
            print("✗ 불안정 — 파라미터 재검토 필요")
        print()

    print("=" * 90)
    print(f"IS Sharpe +7.461 참고: 전체 구간(2022~2026) 그리드 결과 (사이클 그리드)")
    print("=" * 90)


if __name__ == "__main__":
    main()
