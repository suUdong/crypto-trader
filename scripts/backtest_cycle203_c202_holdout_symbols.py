"""
사이클 203 — c202 최적 고정 설정 미관측 심볼 홀드아웃 검증

목적:
  c202는 c199 대비 OOS Sharpe 개선 없음 (tied, Δ=0.000, n=26).
  그리드를 더 넓히는 것은 과최적화 리스크 — 대신 **미관측 심볼**로
  일반화 여부를 확인한다. 실전 배포 전 robustness 체크.

고정 파라미터 (c202 best):
  ADX_TH=5  OBV_EMA_LB=3  OBV_SLOPE_MIN=-0.02
  (+ c199/c192/... 전체 스택)

홀드아웃 심볼 (train/tune 과정에서 미사용):
  KRW-ADA, KRW-DOGE, KRW-LINK

방법:
  - c202 모듈에서 backtest/precompute 함수 재사용 (동일 로직 보장)
  - 3-fold WF 동일 기간에서 OOS 구간만 사용
  - 결과 폴드별/심볼별 집계

판정 기준:
  PASS: avg OOS Sharpe >= 15 AND trades >= 10
  (기존 학습 심볼 대비 크게 악화되면 과최적화 시그널)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from historical_loader import load_historical  # noqa: E402
from backtest_cycle202_vpin_adx_obv_entry_gate import (  # noqa: E402
    BTC_SMA_PERIOD,
    WF_FOLDS,
    align_btc_to_symbol,
    backtest,
    precompute_indicators,
    precompute_obv_slopes,
)

HOLDOUT_SYMBOLS = ["KRW-ADA", "KRW-DOGE", "KRW-LINK"]

# c202 reported best
ADX_TH = 5
OBV_EMA_LB = 3
OBV_SLOPE_MIN = -0.02


def main() -> None:
    print("=" * 80)
    print("=== 사이클 203 — c202 best 고정, 미관측 심볼 홀드아웃 ===")
    print(f"고정: ADX_TH={ADX_TH} OBV_EMA_LB={OBV_EMA_LB} "
          f"OBV_SLOPE_MIN={OBV_SLOPE_MIN:+.2f}")
    print(f"홀드아웃 심볼: {', '.join(HOLDOUT_SYMBOLS)}")
    print("목표: avg OOS Sharpe >= 15 AND trades >= 10 (robustness)")
    print("=" * 80)

    df_btc_full = load_historical(
        "KRW-BTC", "240m", "2021-01-01", "2026-12-31"
    )
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # -- 데이터 유효성 --
    valid_syms: list[str] = []
    for sym in HOLDOUT_SYMBOLS:
        df_chk = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        rows = len(df_chk)
        if rows < 500:
            print(f"  {sym}: 데이터 부족 ({rows}행) → 제외")
        else:
            print(f"  {sym}: {rows}행 OK")
            valid_syms.append(sym)

    if not valid_syms:
        print("\n유효 홀드아웃 심볼 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    all_sharpes: list[float] = []
    all_wrs: list[float] = []
    total_trades = 0

    for sym in valid_syms:
        print(f"\n--- {sym} ---")
        sym_sharpes: list[float] = []
        sym_wrs: list[float] = []
        sym_trades = 0
        for fi, fold in enumerate(WF_FOLDS):
            t_start, t_end = fold["test"]
            df_test = load_historical(sym, "240m", t_start, t_end)
            if df_test.empty or len(df_test) < 100:
                print(f"  Fold {fi+1}: 데이터 부족")
                continue
            btc_c, btc_s = align_btc_to_symbol(
                df_test, df_btc_full, BTC_SMA_PERIOD
            )
            esp, vol_mom, atr_pctile, adx_arr = precompute_indicators(df_test)
            obv_slopes = precompute_obv_slopes(df_test, [OBV_EMA_LB])
            obv_slope = obv_slopes[OBV_EMA_LB]

            r = backtest(
                df_test, ADX_TH, OBV_EMA_LB, OBV_SLOPE_MIN,
                btc_c, btc_s, esp, vol_mom, atr_pctile,
                adx_arr, obv_slope,
            )
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            sym_sharpes.append(sh)
            sym_wrs.append(r["wr"])
            sym_trades += r["trades"]
            print(
                f"  Fold {fi+1}: Sharpe={sh:+.3f}  WR={r['wr']:.1%}  "
                f"n={r['trades']}  avg={r['avg_ret']*100:+.2f}%  "
                f"MDD={r['max_dd']*100:+.2f}%"
            )
        if sym_sharpes:
            avg = float(np.mean(sym_sharpes))
            print(f"  {sym} 평균: Sharpe={avg:+.3f}  trades={sym_trades}")
            all_sharpes.extend(sym_sharpes)
            all_wrs.extend(sym_wrs)
            total_trades += sym_trades

    print("\n" + "=" * 80)
    print("=== 홀드아웃 요약 ===")
    if all_sharpes:
        avg_sh = float(np.mean(all_sharpes))
        avg_wr = float(np.mean(all_wrs)) if all_wrs else 0.0
    else:
        avg_sh = float("nan")
        avg_wr = 0.0

    print(f"  학습 심볼 (ETH/SOL/XRP) 기준: OOS +35.341, n=26")
    print(f"  홀드아웃 심볼: OOS {avg_sh:+.3f}, n={total_trades}")
    if not np.isnan(avg_sh):
        delta = avg_sh - 35.341
        verdict = "일반화 OK" if delta >= -10 else "과최적화 의심"
        print(f"  Δ vs 학습: {delta:+.3f} ({verdict})")

    passed = (
        not np.isnan(avg_sh) and avg_sh >= 15 and total_trades >= 10
    )
    status = "PASS" if passed else "FAIL"
    print(f"  robustness: {status}")

    print(f"\nSharpe: {avg_sh:+.3f}")
    print(f"WR: {avg_wr*100:.1f}%")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
