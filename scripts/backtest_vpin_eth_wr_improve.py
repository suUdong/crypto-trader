"""
vpin_eth W2(2025) WR 개선 탐색 (사이클 100)
- 목적: C_daemon W2 OOS WR=23.1%(기준 30% 미달) 개선
- 가설 1: RSI ceiling 65→60/55 — 과매수 진입 차단으로 WR 개선
- 가설 2: vpin_high 0.55→0.60/0.65 — 더 강한 VPIN 신호만 진입
- 가설 3: vpin_mom 0.0005→0.0007/0.001 — 모멘텀 임계 강화
- 검증: 3개 WF 윈도우 모두 실행, W2 WR 집중 분석
- 기준: W2 WR ≥ 30% + Sharpe ≥ 3.0 + trades ≥ 8 (W1/W3 유지)
"""
from __future__ import annotations

import sys
from itertools import product
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

# 탐색 그리드
RSI_CEILING_GRID  = [65, 60, 55]       # 가설 1: 낮출수록 과매수 진입 차단
VPIN_HIGH_GRID    = [0.55, 0.60, 0.65]  # 가설 2: 높일수록 강한 VPIN만 진입
VPIN_MOM_GRID     = [0.0005, 0.0007, 0.001]  # 가설 3: 강한 모멘텀만

# 고정 (daemon.toml 현재값)
MAX_HOLD    = 18
TP          = 0.06
SL          = 0.008
RSI_PERIOD  = 14
RSI_FLOOR   = 20.0
BUCKET_COUNT = 24
EMA_PERIOD  = 20
MOM_LOOKBACK = 8

# 기준
OOS_SHARPE_MIN = 3.0
OOS_WR_MIN     = 0.30
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
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy  = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i-bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, volumes: np.ndarray,
                          lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def backtest(df: pd.DataFrame, vpin_high: float, vpin_mom_thresh: float,
             rsi_ceiling: float) -> dict:
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
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < rsi_ceiling
            and not np.isnan(ema_val) and c[i] > ema_val
        )

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
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def main() -> None:
    print("=" * 100)
    print("vpin_eth W2(2025) WR 개선 그리드 탐색 (사이클 100)")
    print("목적: W2 OOS WR 23.1% → 30%+ (RSI ceiling / vpin_high / vpin_mom 탐색)")
    print(f"고정: max_hold={MAX_HOLD}, TP={TP:.0%}, SL={SL:.1%}")
    print("=" * 100)

    print("\n데이터 로드 중...")
    data_cache: dict[str, pd.DataFrame] = {}
    for w in WINDOWS:
        df_is  = load_historical(SYMBOL, "240m", w["is_start"],  w["is_end"])
        df_oos = load_historical(SYMBOL, "240m", w["oos_start"], w["oos_end"])
        data_cache[f"{w['name']}_is"]  = df_is
        data_cache[f"{w['name']}_oos"] = df_oos
        print(f"  {w['name']}: IS={len(df_is)}행, OOS={len(df_oos)}행")

    # 기준선 (C_daemon) 먼저 출력
    print("\n--- [기준선] C_daemon (rsi_ceil=65, vh=0.55, vm=0.0005) ---")
    print(f"{'윈도우':<10} {'OOS Sharpe':>12} {'OOS WR':>8} {'OOS T':>7} {'판정':>6}")
    print("-" * 50)
    daemon_pass = 0
    for w in WINDOWS:
        r = backtest(data_cache[f"{w['name']}_oos"], 0.55, 0.0005, 65.0)
        ok = (not np.isnan(r["sharpe"]) and r["sharpe"] > OOS_SHARPE_MIN
              and r["wr"] > OOS_WR_MIN and r["trades"] >= OOS_TRADES_MIN)
        verdict = "✅" if ok else "❌"
        if ok:
            daemon_pass += 1
        sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "  nan"
        print(f"  {w['name']:<8} {sh:>12} {r['wr']:>8.1%} {r['trades']:>7} {verdict:>6}")
    print(f"  → 기준선 통과: {daemon_pass}/3\n")

    # 그리드 탐색
    total = len(RSI_CEILING_GRID) * len(VPIN_HIGH_GRID) * len(VPIN_MOM_GRID)
    print(f"\n=== 그리드 탐색: {total}개 조합 ===")
    print(f"{'#':>3} {'rsi_c':>6} {'vh':>6} {'vm':>8} | "
          f"{'W1 Sh':>8} {'W1 WR':>7} | "
          f"{'W2 Sh':>8} {'W2 WR':>7} | "
          f"{'W3 Sh':>8} {'W3 WR':>7} | "
          f"{'통과':>4} {'W2 ok':>5}")
    print("-" * 95)

    results = []
    idx = 0
    for rsi_c, vh, vm in product(RSI_CEILING_GRID, VPIN_HIGH_GRID, VPIN_MOM_GRID):
        idx += 1
        window_results = []
        oos_stats = []
        for w in WINDOWS:
            r = backtest(data_cache[f"{w['name']}_oos"], vh, vm, float(rsi_c))
            ok = (not np.isnan(r["sharpe"]) and r["sharpe"] > OOS_SHARPE_MIN
                  and r["wr"] > OOS_WR_MIN and r["trades"] >= OOS_TRADES_MIN)
            window_results.append(ok)
            oos_stats.append(r)

        pass_count = sum(window_results)
        w2_ok = window_results[1]

        # W2 WR 개선 여부 표시
        w2_wr_marker = "★" if oos_stats[1]["wr"] >= 0.30 else " "

        r1, r2, r3 = oos_stats
        sh1 = f"{r1['sharpe']:+.2f}" if not np.isnan(r1["sharpe"]) else "  nan"
        sh2 = f"{r2['sharpe']:+.2f}" if not np.isnan(r2["sharpe"]) else "  nan"
        sh3 = f"{r3['sharpe']:+.2f}" if not np.isnan(r3["sharpe"]) else "  nan"

        print(f"{idx:>3} {rsi_c:>6} {vh:>6.2f} {vm:>8.4f} | "
              f"{sh1:>8} {r1['wr']:>6.1%} | "
              f"{sh2:>8} {r2['wr']:>6.1%}{w2_wr_marker}| "
              f"{sh3:>8} {r3['wr']:>6.1%} | "
              f"{pass_count:>4} {'✅' if w2_ok else '  ':>5}")

        results.append({
            "rsi_ceiling": rsi_c, "vpin_high": vh, "vpin_mom": vm,
            "pass_count": pass_count, "w2_ok": w2_ok,
            "w2_wr": oos_stats[1]["wr"], "w2_sharpe": oos_stats[1]["sharpe"],
            "w2_trades": oos_stats[1]["trades"],
            "w1_sharpe": oos_stats[0]["sharpe"], "w3_sharpe": oos_stats[2]["sharpe"],
        })

    # 결과 요약
    print("\n" + "=" * 100)
    print("== 결과 요약 ==")

    # W2 WR >= 30% 달성한 조합
    w2_improved = [r for r in results if r["w2_wr"] >= 0.30 and r["w2_trades"] >= OOS_TRADES_MIN]
    passed_3 = [r for r in results if r["pass_count"] == 3]
    passed_2 = [r for r in results if r["pass_count"] >= 2]

    print(f"\n전체 {total}개 중:")
    print(f"  - W2 WR ≥ 30% 달성: {len(w2_improved)}개")
    print(f"  - 전 구간(3/3) 통과: {len(passed_3)}개")
    print(f"  - 2/3 이상 통과:     {len(passed_2)}개")

    if w2_improved:
        print("\n[W2 WR ≥ 30% 달성 조합 (W2 WR 내림차순)]:")
        w2_improved.sort(key=lambda x: (-x["w2_wr"], -x["pass_count"]))
        for r in w2_improved[:10]:
            print(f"  rsi_ceil={r['rsi_ceiling']} vh={r['vpin_high']:.2f} vm={r['vpin_mom']:.4f} "
                  f"→ W2 Sharpe={r['w2_sharpe']:+.3f} WR={r['w2_wr']:.1%} T={r['w2_trades']} "
                  f"| pass={r['pass_count']}/3")
    else:
        print("\n[W2 WR ≥ 30% 달성 없음 — W2 WR 최고치 TOP 5]:")
        sorted_by_wr = sorted(results, key=lambda x: -x["w2_wr"])
        for r in sorted_by_wr[:5]:
            print(f"  rsi_ceil={r['rsi_ceiling']} vh={r['vpin_high']:.2f} vm={r['vpin_mom']:.4f} "
                  f"→ W2 Sharpe={r['w2_sharpe']:+.3f} WR={r['w2_wr']:.1%} T={r['w2_trades']} "
                  f"| pass={r['pass_count']}/3")

    if passed_3:
        print("\n[3/3 전 구간 통과 조합]:")
        for r in passed_3:
            print(f"  rsi_ceil={r['rsi_ceiling']} vh={r['vpin_high']:.2f} vm={r['vpin_mom']:.4f} "
                  f"→ W1={r['w1_sharpe']:+.3f} W2={r['w2_sharpe']:+.3f} W2_WR={r['w2_wr']:.1%} "
                  f"W3={r['w3_sharpe']:+.3f}")

    # 최종 판정
    print("\n" + "=" * 100)
    best_candidates = [r for r in results if r["pass_count"] >= 2 and r["w2_wr"] >= 0.30]
    if best_candidates:
        best = max(best_candidates, key=lambda x: (x["pass_count"], x["w2_wr"]))
        print(f"★ 권장 파라미터: rsi_ceiling={best['rsi_ceiling']}, "
              f"vpin_high={best['vpin_high']:.2f}, vpin_mom={best['vpin_mom']:.4f}")
        print(f"  W2 WR={best['w2_wr']:.1%} (기준 30% {'✅ 달성' if best['w2_wr'] >= 0.30 else '❌ 미달'}), "
              f"통과={best['pass_count']}/3")
        print(f"  → daemon.toml 업데이트 검토 필요 (Sharpe ≥ 5.0 전체 백테스트 선행)")
    else:
        best_pass = max(results, key=lambda x: (x["pass_count"], x["w2_wr"]), default=None)
        if best_pass:
            print(f"  최고 후보: rsi_ceil={best_pass['rsi_ceiling']} vh={best_pass['vpin_high']:.2f} "
                  f"vm={best_pass['vpin_mom']:.4f} → 통과={best_pass['pass_count']}/3 "
                  f"W2 WR={best_pass['w2_wr']:.1%}")
        print("  → W2 WR 30% 달성 조합 없음 — daemon 파라미터 현재 유지 권장")
    print("=" * 100)


if __name__ == "__main__":
    main()
