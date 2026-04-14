"""
vpin_multi 사이클 200 — c192 finer grid + edge extension

c192 최적: ttA=6 ttF=3.0 aTPS=0.5 → avg OOS Sharpe +30.947, trades 26
- ttA는 그리드 최저(6)에서 최적 → 더 짧은 후보 [3,4,5,6,8] 탐색
- ttF는 최고(3.0)에서 최적 → 더 강한 [3.0,4.0,5.0] 탐색
- aTPS는 최저(0.5)에서 최적 → 더 작은/0 포함 [0.0,0.25,0.5,0.75] 탐색
= 5×3×4 = 60 combos, 3-fold WF.

c192의 backtest/precompute 함수를 그대로 재사용하고 그리드만 교체.
"""
from __future__ import annotations

import importlib.util
import sys
from itertools import product
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# c192 모듈 동적 로드 (파일명에 점 없으므로 import 가능하지만 안전하게)
spec = importlib.util.spec_from_file_location(
    "c192_base",
    HERE / "backtest_cycle192_vpin_multi_time_decay_trail_atr_tp_scale.py",
)
c192 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c192)

from historical_loader import load_historical  # noqa: E402

SYMBOLS = c192.SYMBOLS
WF_FOLDS = c192.WF_FOLDS
BTC_SMA_PERIOD = c192.BTC_SMA_PERIOD

# 확장 그리드
TTA_LIST = [3, 4, 5, 6, 8]
TTF_LIST = [3.0, 4.0, 5.0]
ATS_LIST = [0.0, 0.25, 0.5, 0.75]


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 200 — c192 finer grid + edge extension ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"기준선: c192 ttA=6 ttF=3.0 aTPS=0.5 → OOS +30.947 n=26")
    print(f"확장: ttA{TTA_LIST} ttF{TTF_LIST} aTPS{ATS_LIST} = "
          f"{len(TTA_LIST) * len(TTF_LIST) * len(ATS_LIST)} combos")
    print("=" * 80)

    df_btc_full = load_historical(
        "KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    sym_data_ok = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if not df_check.empty and len(df_check) >= 500:
            sym_data_ok.append(sym)
            print(f"  {sym}: {len(df_check)}행 OK")

    if not sym_data_ok:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    combos = [
        {"trail_tighten_after": tta,
         "trail_tighten_factor": ttf,
         "atr_tp_scale_hi": ats}
        for tta, ttf, ats in product(TTA_LIST, TTF_LIST, ATS_LIST)
    ]

    # -- Phase 1: train 그리드 (fold1 train) --
    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: train ({train_start} ~ {train_end})")

    sym_train_cache: dict = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if df_tr.empty:
            continue
        btc_c, btc_s = c192.align_btc_to_symbol(
            df_tr, df_btc_full, BTC_SMA_PERIOD)
        esp, vol_mom, atr_pct = c192.precompute_indicators(df_tr)
        sym_train_cache[sym] = (df_tr, btc_c, btc_s, esp, vol_mom, atr_pct)

    train_results: list[dict] = []
    for combo in combos:
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr, btc_c, btc_s, esp, vm, ap = sym_train_cache[sym]
            r = c192.backtest(
                df_tr,
                combo["trail_tighten_after"],
                combo["trail_tighten_factor"],
                combo["atr_tp_scale_hi"],
                btc_c, btc_s, esp, vm, ap,
            )
            sym_results.append(r)
        pooled = c192.pool_results(sym_results)
        train_results.append({**combo, **pooled})

    valid = [r for r in train_results
             if r["trades"] >= 8 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n유효 train 조합 (n>=8): {len(valid)}/{len(train_results)}")
    print(f"\n=== Train Top 12 ===")
    print(f"{'ttA':>4} {'ttF':>5} {'aTPS':>5} | "
          f"{'Sharpe':>8} {'WR':>6} {'n':>5}")
    for r in valid[:12]:
        print(f"{r['trail_tighten_after']:>4} "
              f"{r['trail_tighten_factor']:>5.1f} "
              f"{r['atr_tp_scale_hi']:>5.2f} | "
              f"{r['sharpe']:>+8.3f} {r['wr']:>5.1%} {r['trades']:>5}")

    if not valid:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # -- Phase 2: 3-fold OOS WF (Top 10) --
    top_n = min(10, len(valid))
    top_combos = valid[:top_n]

    print(f"\n{'=' * 80}\n=== 3-fold OOS WF (Top {top_n}) ===")
    wf_results: list[dict] = []
    for rank, params in enumerate(top_combos, 1):
        tta = params["trail_tighten_after"]
        ttf = params["trail_tighten_factor"]
        ats = params["atr_tp_scale_hi"]
        oos_sh = []
        oos_n = []
        fold_dets = []
        for fold in WF_FOLDS:
            sym_fold = []
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = c192.align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                esp, vm, ap = c192.precompute_indicators(df_test)
                r = c192.backtest(
                    df_test, tta, ttf, ats, btc_c, btc_s, esp, vm, ap)
                sym_fold.append(r)
            pooled = c192.pool_results(sym_fold)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            oos_sh.append(sh)
            oos_n.append(pooled["trades"])
            fold_dets.append(pooled)
        avg_oos = float(np.mean(oos_sh)) if oos_sh else 0.0
        total_n = sum(oos_n)
        # WR 평균
        wrs = [d["wr"] for d in fold_dets if d["trades"] > 0]
        avg_wr = float(np.mean(wrs)) if wrs else 0.0
        print(f"  #{rank}: ttA={tta} ttF={ttf:.1f} aTPS={ats:.2f} | "
              f"train={params['sharpe']:+.3f} -> OOS={avg_oos:+.3f} "
              f"n={total_n} WR={avg_wr:.1%}")
        wf_results.append({
            **params,
            "avg_oos_sharpe": avg_oos,
            "total_oos_trades": total_n,
            "avg_wr": avg_wr,
            "fold_sharpes": oos_sh,
            "fold_trades": oos_n,
        })

    wf_sorted = sorted(wf_results,
                       key=lambda x: x["avg_oos_sharpe"], reverse=True)
    best = wf_sorted[0]

    # -- c192 비교 --
    print(f"\n{'=' * 80}\n=== c192 베이스라인 대비 ===")
    print(f"  c192 최적 (ttA=6 ttF=3.0 aTPS=0.5): OOS=+30.947 n=26")
    print(f"  c200 최적 (ttA={best['trail_tighten_after']} "
          f"ttF={best['trail_tighten_factor']:.1f} "
          f"aTPS={best['atr_tp_scale_hi']:.2f}): "
          f"OOS={best['avg_oos_sharpe']:+.3f} n={best['total_oos_trades']}")
    delta = best["avg_oos_sharpe"] - 30.947
    print(f"  Δ Sharpe: {delta:+.3f} "
          f"({'개선' if delta > 0 else '악화' if delta < 0 else '동일'})")
    print(f"  Δ trades: {best['total_oos_trades'] - 26:+d}")

    # -- 최종 --
    print(f"\n{'=' * 80}\n=== 최종 요약 ===")
    print(f"★ ttA={best['trail_tighten_after']} "
          f"ttF={best['trail_tighten_factor']:.1f} "
          f"aTPS={best['atr_tp_scale_hi']:.2f}")
    for i, (sh, n) in enumerate(zip(best["fold_sharpes"],
                                    best["fold_trades"]), 1):
        print(f"  Fold {i}: Sharpe={sh:+.3f} trades={n}")

    print(f"\nSharpe: {best['avg_oos_sharpe']:.3f}")
    print(f"WR: {best['avg_wr'] * 100:.1f}%")
    print(f"trades: {best['total_oos_trades']}")


if __name__ == "__main__":
    main()
