"""
vpin_multi 사이클 200 — c192 베이스 복귀 + 엔트리 정밀화

배경:
- c199 (레짐 이중 출구) avg_OOS=+35.34, c192 (avg_OOS=+47.31) 대비 -11.97 악화.
- 출구 파라미터 추가는 trades(+6)를 늘렸지만 품질 저하 → 과적합 신호.
- 다음 단계 가설: c192 출구를 그대로 유지하고, 진입 품질을 미세 조정해서 trades를
  유지하면서 Sharpe를 끌어올린다 (출구 튜닝 → 입구 튜닝으로 축 전환).

탐색 그리드 (3×3×3 = 27 combos):
  MOM_THRESH:    [0.0005, 0.0007, 0.0010]   — 모멘텀 진입 임계값
  RSI_DELTA_MIN: [5, 6, 7]                  — RSI velocity 최소
  VPIN_LOW:      [0.30, 0.35, 0.40]         — VPIN 비대칭 상한

고정: c192 출구 (ttA=6 ttF=3.0) + c190/c186/c182/c176/c165/c164 모두 c192와 동일.
검증: 3-fold WF, 풀링 Sharpe, slippage stress (Top 3).
목표: avg_OOS Sharpe >= 47 AND total_trades >= 18 (c192 동급 trades, Sharpe 개선).
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from historical_loader import load_historical  # noqa: E402

# c199 모듈에서 인디케이터/백테스트 헬퍼 재사용 (구조 100% 동일, 출구 고정)
import importlib.util
_c199_path = THIS_DIR / "backtest_cycle199_vpin_multi_regime_dual_exit.py"
_spec = importlib.util.spec_from_file_location("c199_mod", _c199_path)
c199 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c199)  # type: ignore[union-attr]

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]

# c192 baseline 출구 (regime 비활성)
FIXED_REGIME_TH = 100      # 사실상 항상 저변동 모드
FIXED_HI_TP_BONUS = 0.0
FIXED_HI_TRAIL_RELAX = 1.0
FIXED_LO_SL_TIGHTEN = 0.0

# c200 탐색 그리드
MOM_THRESH_LIST = [0.0005, 0.0007, 0.0010]
RSI_DELTA_MIN_LIST = [5, 6, 7]
VPIN_LOW_LIST = [0.30, 0.35, 0.40]

WF_FOLDS = c199.WF_FOLDS
SLIPPAGE_LEVELS = c199.SLIPPAGE_LEVELS
BTC_SMA_PERIOD = c199.BTC_SMA_PERIOD


def _patched_backtest(df, mom_thresh, rsi_delta_min, vpin_low,
                      btc_c, btc_s, esp, vol_mom, atr_pctile,
                      slippage=0.0005):
    # 모듈 전역 상수 임시 패치 → c199.backtest 호출
    orig_mom = c199.MOM_THRESH
    orig_rsi = c199.RSI_DELTA_MIN
    orig_vpin = c199.VPIN_LOW
    try:
        c199.MOM_THRESH = mom_thresh
        c199.RSI_DELTA_MIN = rsi_delta_min
        c199.VPIN_LOW = vpin_low
        return c199.backtest(
            df, FIXED_REGIME_TH, FIXED_HI_TP_BONUS,
            FIXED_HI_TRAIL_RELAX, FIXED_LO_SL_TIGHTEN,
            btc_c, btc_s, esp, vol_mom, atr_pctile,
            slippage=slippage,
        )
    finally:
        c199.MOM_THRESH = orig_mom
        c199.RSI_DELTA_MIN = orig_rsi
        c199.VPIN_LOW = orig_vpin


def build_combos():
    return [
        {"mom_thresh": m, "rsi_delta_min": r, "vpin_low": v}
        for m, r, v in product(MOM_THRESH_LIST, RSI_DELTA_MIN_LIST, VPIN_LOW_LIST)
    ]


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 200 — c192 베이스 복귀 + 엔트리 정밀화 ===")
    print(f"심볼: {', '.join(SYMBOLS)}  목표: OOS Sharpe >= 47 AND trades >= 18")
    print("축 전환: 출구 튜닝 → 입구 튜닝 (MOM/RSI_delta/VPIN 미세 그리드)")
    print("=" * 80)

    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    sym_data_ok = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df_check.empty or len(df_check) < 500:
            print(f"  {sym}: 데이터 부족 → 제외")
        else:
            print(f"  {sym}: {len(df_check)}행 OK")
            sym_data_ok.append(sym)
    if not sym_data_ok:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    combos = build_combos()
    print(f"\n총 조합: {len(combos)}")

    # Phase 1: train 그리드
    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: train ({train_start} ~ {train_end})")
    sym_train_cache = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if df_tr.empty:
            continue
        btc_c, btc_s = c199.align_btc_to_symbol(df_tr, df_btc_full, BTC_SMA_PERIOD)
        esp, vm, ap = c199.precompute_indicators(df_tr)
        sym_train_cache[sym] = (df_tr, btc_c, btc_s, esp, vm, ap)
        print(f"  {sym} train: {len(df_tr)}행")

    results = []
    for idx, combo in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr, btc_c, btc_s, esp, vm, ap = sym_train_cache[sym]
            r = _patched_backtest(
                df_tr, combo["mom_thresh"], combo["rsi_delta_min"], combo["vpin_low"],
                btc_c, btc_s, esp, vm, ap,
            )
            sym_results.append(r)
        pooled = c199.pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 9 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    valid = [r for r in results if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")
    print(f"\n=== Train Top 12 ===")
    print(f"{'MOM':>7} {'rsiD':>5} {'vpin':>5} | {'Sharpe':>7} {'WR':>6} "
          f"{'avg%':>7} {'MDD':>7} {'n':>5}")
    for r in valid[:12]:
        print(f"{r['mom_thresh']:>7.4f} {r['rsi_delta_min']:>5} "
              f"{r['vpin_low']:>5.2f} | {r['sharpe']:>+7.3f} "
              f"{r['wr']:>5.1%} {r['avg_ret']*100:>+6.2f}% "
              f"{r['max_dd']*100:>+6.2f}% {r['trades']:>5}")

    if not valid:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # Phase 2: 3-fold OOS WF
    seen, top = set(), []
    for r in valid:
        k = (r["mom_thresh"], r["rsi_delta_min"], r["vpin_low"])
        if k not in seen:
            seen.add(k)
            top.append(r)
        if len(top) >= 8:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(top)}) ===")

    wf_results = []
    for rank, params in enumerate(top, 1):
        m, rmin, vp = params["mom_thresh"], params["rsi_delta_min"], params["vpin_low"]
        oos_sharpes, oos_trades, fold_details = [], [], []
        for fold in WF_FOLDS:
            sym_fold = []
            for sym in sym_data_ok:
                df_test = load_historical(sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = c199.align_btc_to_symbol(df_test, df_btc_full, BTC_SMA_PERIOD)
                esp, vm, ap = c199.precompute_indicators(df_test)
                r = _patched_backtest(df_test, m, rmin, vp, btc_c, btc_s, esp, vm, ap)
                sym_fold.append(r)
            pooled = c199.pool_results(sym_fold)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(pooled["trades"])
            fold_details.append(pooled)

        avg_oos = float(np.mean(oos_sharpes))
        total_n = sum(oos_trades)
        all_pass = all(s >= 3.0 for s in oos_sharpes) and avg_oos >= 5.0
        print(f"  #{rank}: MOM={m:.4f} rsiD={rmin} vpin={vp:.2f} | "
              f"train={params['sharpe']:+.3f} -> avg_OOS={avg_oos:+.3f} "
              f"n={total_n} {'PASS' if all_pass else 'FAIL'}")
        wf_results.append({
            **params, "train_sharpe": params["sharpe"],
            "avg_oos_sharpe": avg_oos, "oos_sharpes": oos_sharpes,
            "oos_trades": oos_trades, "total_oos_trades": total_n,
            "fold_details": fold_details, "all_pass": all_pass,
        })

    if not wf_results:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"], reverse=True)
    best = wf_sorted[0]

    # Phase 3: 슬리피지 스트레스 (Top 3)
    print(f"\n{'=' * 80}\n=== 슬리피지 스트레스 (Top 3) ===")
    for rank, p in enumerate(wf_sorted[:3], 1):
        m, rmin, vp = p["mom_thresh"], p["rsi_delta_min"], p["vpin_low"]
        print(f"\n--- #{rank}: MOM={m:.4f} rsiD={rmin} vpin={vp:.2f} ---")
        for slip in SLIPPAGE_LEVELS:
            sym_results = []
            for sym in sym_data_ok:
                df_full = load_historical(sym, "240m", "2022-01-01", "2026-12-31")
                if df_full.empty:
                    continue
                btc_c, btc_s = c199.align_btc_to_symbol(df_full, df_btc_full, BTC_SMA_PERIOD)
                esp, vm, ap = c199.precompute_indicators(df_full)
                r = _patched_backtest(df_full, m, rmin, vp, btc_c, btc_s, esp, vm, ap, slippage=slip)
                sym_results.append(r)
            pooled = c199.pool_results(sym_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            print(f"  slip={slip*100:.2f}% Sharpe={sh:+.3f} "
                  f"WR={pooled['wr']:.1%} n={pooled['trades']}")

    # 최종 요약
    print(f"\n{'=' * 80}\n=== 최종 요약 ===")
    print(f"★ OOS 최적: MOM_THRESH={best['mom_thresh']:.4f} "
          f"RSI_DELTA_MIN={best['rsi_delta_min']} VPIN_LOW={best['vpin_low']:.2f}")
    print(f"  baseline c192 avg_OOS=+47.314 → c200 avg_OOS={best['avg_oos_sharpe']:+.3f} "
          f"(Δ {best['avg_oos_sharpe']-47.314:+.3f})")
    for i, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][i]
        print(f"  Fold {i+1}: Sharpe={sh:+.3f} WR={fd['wr']:.1%} "
              f"trades={best['oos_trades'][i]} avg={fd['avg_ret']*100:+.2f}% "
              f"MDD={fd['max_dd']*100:+.2f}%")

    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))
    print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr*100:.1f}%")
    print(f"trades: {best['total_oos_trades']}")


if __name__ == "__main__":
    main()
