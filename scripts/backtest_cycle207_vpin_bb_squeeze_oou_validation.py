"""
vpin_multi 사이클 207 — c206 BB squeeze→expansion 후속:
Out-Of-Universe (OOU) 심볼 검증 + OOS 최적 주변 fine-grid.

배경:
- c206 OOS Sharpe +44.258 (목표 +45 미달, c199 +51.425 대비 -7.167 악화).
- 거래 대부분이 SOL 한 종목에 집중 (XRP 0건). 표본 과소 가능성.
- 과최적화 회피 원칙: 추가 필터를 쌓는 대신, c206 OOS Top 파라미터를
  학습에 쓰지 않은 심볼(ADA/DOGE/AVAX)에서 그대로 검증.
- 동시에 OOS 최적(bbP=20 bbS=2.0 sqTh=20 sqLB=30 expB=2 tpSq=0.5) 주변
  ±1 step fine-grid (총 12조합)로 평탄성(flatness) 확인.

실행: c206 모듈을 import 해 backtest/precompute 재사용. 로직 중복 없음.
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical
import backtest_cycle206_vpin_bb_squeeze_expansion as c206


OOU_SYMBOLS = ["KRW-ADA", "KRW-DOGE", "KRW-AVAX"]
ALL_SYMBOLS = c206.SYMBOLS + OOU_SYMBOLS

# c206 OOS 최적 + ±1 step 평탄성 확인
FINE_COMBOS = [
    {"bb_period": bp, "bb_std": bs, "squeeze_th": st,
     "squeeze_lb": sl, "expand_bars": eb, "tp_squeeze_bonus": tb}
    for bp, bs, st, sl, eb, tb in product(
        [20, 30],          # bb_period
        [2.0, 2.5],        # bb_std
        [20, 30],          # squeeze_th
        [30],              # squeeze_lb
        [2, 3],            # expand_bars
        [0.5],             # tp_squeeze_bonus
    )
]
# 명시적 OOS 최적
BEST = {"bb_period": 20, "bb_std": 2.0, "squeeze_th": 20,
        "squeeze_lb": 30, "expand_bars": 2, "tp_squeeze_bonus": 0.5}


def run_combo_on_symbol(sym: str, df_btc_full, combo: dict,
                        start: str, end: str) -> dict | None:
    df = load_historical(sym, "240m", start, end)
    if df.empty or len(df) < 500:
        return None
    btc_c, btc_s = c206.align_btc_to_symbol(
        df, df_btc_full, c206.BTC_SMA_PERIOD)
    esp, vol_mom, atr_pctile = c206.precompute_base(df)
    bb_w, bb_wp = c206.precompute_bb(
        df, combo["bb_period"], combo["bb_std"], combo["squeeze_lb"])
    return c206.backtest(
        df,
        combo["bb_period"], combo["bb_std"],
        combo["squeeze_th"], combo["squeeze_lb"],
        combo["expand_bars"], combo["tp_squeeze_bonus"],
        btc_c, btc_s, esp, vol_mom, atr_pctile, bb_w, bb_wp)


def main() -> None:
    print("=" * 80)
    print("=== c207 — c206 BB squeeze OOU 검증 + 평탄성 점검 ===")
    print(f"OOU 심볼: {', '.join(OOU_SYMBOLS)}")
    print(f"기존 심볼: {', '.join(c206.SYMBOLS)}")
    print(f"OOS 최적: {BEST}")
    print("=" * 80)

    df_btc_full = load_historical(
        "KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    folds = c206.WF_FOLDS  # 3-fold WF 그대로 사용

    # === 1) OOU 심볼에 OOS 최적 그대로 ===
    print("\n--- [1] OOU 심볼 × 3-fold OOS 검증 (c206 OOS 최적 고정) ---")
    oou_results: list[dict] = []
    for sym in OOU_SYMBOLS:
        sym_fold_rs = []
        for fold in folds:
            ts, te = fold["test"]
            r = run_combo_on_symbol(sym, df_btc_full, BEST, ts, te)
            if r is None:
                print(f"  {sym} {ts}~{te}: 데이터 부족")
                continue
            sym_fold_rs.append(r)
            print(f"  {sym} {ts}~{te}: "
                  f"Sharpe={r['sharpe']:+.3f} WR={r['wr']*100:.1f}% "
                  f"n={r['trades']} avg={r['avg_ret']*100:+.2f}% "
                  f"MDD={r['mdd']*100:+.2f}%")
        if sym_fold_rs:
            pooled = c206.pool_results(sym_fold_rs)
            oou_results.append({"sym": sym, **pooled})
            print(f"  >> {sym} pooled: Sharpe={pooled['sharpe']:+.3f} "
                  f"trades={pooled['trades']}")

    # === 2) OOS 최적 주변 fine grid (기존 3 심볼 OOS 평균) ===
    print("\n--- [2] 평탄성 점검: best 주변 fine grid (기존 심볼 OOS 평균) ---")
    fine_summary: list[dict] = []
    for combo in FINE_COMBOS:
        all_test_rs = []
        for sym in c206.SYMBOLS:
            for fold in folds:
                ts, te = fold["test"]
                r = run_combo_on_symbol(sym, df_btc_full, combo, ts, te)
                if r is not None:
                    all_test_rs.append(r)
        pooled = c206.pool_results(all_test_rs) if all_test_rs else None
        if pooled is None:
            continue
        tag = (f"bbP={combo['bb_period']} bbS={combo['bb_std']} "
               f"sqTh={combo['squeeze_th']} expB={combo['expand_bars']}")
        fine_summary.append({"tag": tag, **pooled})
        print(f"  {tag:40s} Sharpe={pooled['sharpe']:+.3f} "
              f"trades={pooled['trades']} WR={pooled['wr']*100:.1f}%")

    fine_summary.sort(key=lambda x: x["sharpe"], reverse=True)

    # === 종합 ===
    print("\n" + "=" * 80)
    print("=== 종합 ===")

    # OOU 풀 (모든 심볼·모든 fold)
    all_oou_pool = []
    for sym in OOU_SYMBOLS:
        for fold in folds:
            ts, te = fold["test"]
            r = run_combo_on_symbol(sym, df_btc_full, BEST, ts, te)
            if r is not None:
                all_oou_pool.append(r)

    if all_oou_pool:
        oou_pool = c206.pool_results(all_oou_pool)
    else:
        oou_pool = {"sharpe": float("nan"), "wr": 0.0, "trades": 0,
                    "avg_ret": 0.0, "mdd": 0.0}

    print(f"OOU pooled (ADA+DOGE+AVAX, 3-fold): "
          f"Sharpe={oou_pool['sharpe']:+.3f} "
          f"WR={oou_pool['wr']*100:.1f}% "
          f"trades={oou_pool['trades']}")

    if fine_summary:
        top = fine_summary[0]
        print(f"Fine-grid top: {top['tag']} "
              f"Sharpe={top['sharpe']:+.3f} trades={top['trades']}")

    # ralph 파서용 단일 라인 — OOU pooled를 메인 지표로
    sh = oou_pool["sharpe"] if not np.isnan(oou_pool["sharpe"]) else 0.0
    print(f"\nSharpe: {sh:+.3f}")
    print(f"WR: {oou_pool['wr']*100:.1f}%")
    print(f"trades: {oou_pool['trades']}")


if __name__ == "__main__":
    main()
