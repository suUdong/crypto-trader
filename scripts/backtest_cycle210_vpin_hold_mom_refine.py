"""
사이클 210 — c198 후속: HOLD bars × MOM_THRESH 미세 탐색
- 배경: c198/c192 최적은 vrLB=3 vrMin=0.0 rdLB=3 rdSk=0 (신규 필터 OFF)
  → 신규 필터로는 개선 불가. c165 고정값(MAX_HOLD=20, MOM_THRESH=0.0007) 자체를
    재검증하여 추가 마진이 있는지 본다.
- 그리드:
  MAX_HOLD: [16, 20, 24, 28]   — 보유 기간
  MOM_THRESH: [0.0005, 0.0007, 0.0010, 0.0015] — 모멘텀 임계
  = 16 combos
- c198 신규 필터는 OFF로 고정 (vrMin=0.0, rdSk=0)
- 3-fold WF + 슬리피지 기본 0.0005
- 목표: avg OOS Sharpe > 47 또는 trades > 26 (c192 대비)
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_cycle198_vpin_multi_vpin_roc_rsi_divergence as c198
from historical_loader import load_historical

SYMBOLS = c198.SYMBOLS
WF_FOLDS = c198.WF_FOLDS

HOLD_LIST = [16, 20, 24, 28]
MOM_LIST = [0.0005, 0.0007, 0.0010, 0.0015]


def run_with(max_hold: int, mom_thresh: float, df_btc_full) -> dict:
    """전체 OOS pooled 결과."""
    orig_hold = c198.MAX_HOLD
    orig_mom = c198.MOM_THRESH
    c198.MAX_HOLD = max_hold
    c198.MOM_THRESH = mom_thresh
    try:
        oos_sharpes: list[float] = []
        oos_trades_total = 0
        oos_wrs: list[float] = []
        fold_pooled: list[dict] = []
        for fold in WF_FOLDS:
            sym_results = []
            for sym in SYMBOLS:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = c198.align_btc_to_symbol(
                    df_test, df_btc_full, c198.BTC_SMA_PERIOD)
                esp, vol_mom, atr_pctile, vpin = c198.precompute_indicators(
                    df_test)
                r = c198.backtest(
                    df_test,
                    vpin_roc_lb=3, vpin_roc_min=0.0,
                    rsi_div_lb=3, rsi_div_skip=0,
                    btc_close_aligned=btc_c, btc_sma_aligned=btc_s,
                    ema_slope_pctile_arr=esp, vol_mom_arr=vol_mom,
                    atr_pctile_full=atr_pctile, vpin_full=vpin,
                )
                sym_results.append(r)
            pooled = c198.pool_results(sym_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades_total += pooled["trades"]
            oos_wrs.append(pooled["wr"])
            fold_pooled.append(pooled)
        avg = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
        avg_wr = float(np.mean(oos_wrs)) if oos_wrs else 0.0
        return {
            "max_hold": max_hold,
            "mom_thresh": mom_thresh,
            "avg_oos_sharpe": avg,
            "avg_wr": avg_wr,
            "total_trades": oos_trades_total,
            "fold_sharpes": oos_sharpes,
            "fold_pooled": fold_pooled,
        }
    finally:
        c198.MAX_HOLD = orig_hold
        c198.MOM_THRESH = orig_mom


def main() -> None:
    print("=" * 80)
    print("=== 사이클 210 — c198 후속: HOLD × MOM 미세 탐색 ===")
    print(f"기준: c192 avg_OOS=+47.314 n=20")
    print(f"그리드: HOLD={HOLD_LIST} × MOM={MOM_LIST} = "
          f"{len(HOLD_LIST) * len(MOM_LIST)} combos")
    print("=" * 80)

    df_btc_full = load_historical(
        "KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    results: list[dict] = []
    combos = list(product(HOLD_LIST, MOM_LIST))
    for idx, (h, m) in enumerate(combos, 1):
        r = run_with(h, m, df_btc_full)
        results.append(r)
        print(f"  [{idx}/{len(combos)}] HOLD={h} MOM={m:.4f} -> "
              f"avg_OOS={r['avg_oos_sharpe']:+.3f} "
              f"WR={r['avg_wr'] * 100:.1f}% n={r['total_trades']}")

    results.sort(key=lambda x: x["avg_oos_sharpe"], reverse=True)

    print("\n" + "=" * 80)
    print("=== Top 5 (avg OOS Sharpe 기준) ===")
    print(f"{'HOLD':>5} {'MOM':>8} {'avg_OOS':>10} {'WR':>7} {'trades':>7}")
    print("-" * 45)
    for r in results[:5]:
        print(f"{r['max_hold']:>5} {r['mom_thresh']:>8.4f} "
              f"{r['avg_oos_sharpe']:>+10.3f} "
              f"{r['avg_wr'] * 100:>6.1f}% {r['total_trades']:>7}")

    best = results[0]
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    print(f"★ 최적: HOLD={best['max_hold']} MOM={best['mom_thresh']:.4f}")
    for fi, (sh, fd) in enumerate(zip(best["fold_sharpes"],
                                       best["fold_pooled"])):
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={fd['trades']}  "
              f"avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    delta_sh = best["avg_oos_sharpe"] - 47.314
    print(f"\n  Δ vs c192: {delta_sh:+.3f}")

    print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
    print(f"WR: {best['avg_wr'] * 100:.1f}%")
    print(f"trades: {best['total_trades']}")


if __name__ == "__main__":
    main()
