"""
사이클 214 — c199 베이스라인 견고성 검증 (확장 심볼 + 슬리피지 스트레스)

배경:
  c200~c213까지 모든 오버레이가 c199 (OOS Sharpe +51.425) 대비 악화 또는 미미.
  c213 (entry quality score) 마저 -14.063 악화 → 추가 파라미터 탐색은 과최적화.

방향:
  파라미터를 더 늘리지 말고, c199 고정 설정이 *기존 ETH/SOL/XRP 외*에서도
  살아남는지, 슬리피지 가정이 흔들렸을 때도 견고한지를 확인한다.
  실전 paper 투입 전 최소한의 sanity check.

방법:
  - c213 모듈의 backtest()를 score_min=0, tp/sl/trail score mult=0 으로 호출
    → c199와 등가 (점수 게이트 비활성, 점수 기반 스케일링 0)
  - 심볼: 기존(ETH/SOL/XRP) + 확장(BTC/DOGE/ADA)
  - 슬리피지: 0.0005 / 0.0010 / 0.0020 (보수/현실/스트레스)
  - WF 3-fold (c213과 동일)
  - 출력: 심볼별·슬리피지별 OOS Sharpe / WR / trades, 풀링된 평균
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_cycle213_vpin_entry_quality_score_tpsl import (
    BTC_SMA_PERIOD,
    WF_FOLDS,
    align_btc_to_symbol,
    backtest,
    precompute_base,
    precompute_bb,
)
from historical_loader import load_historical

EXISTING = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]
EXTENDED = ["KRW-BTC", "KRW-DOGE", "KRW-ADA"]
SYMBOLS = EXISTING + EXTENDED
SLIPPAGES = [0.0005, 0.0010, 0.0020]


def run_fold(sym: str, fold: dict, btc_full, slippage: float) -> dict:
    test_start, test_end = fold["test"]
    df = load_historical(sym, "240m", test_start, test_end)
    if df.empty or len(df) < 200:
        return {"sharpe": float("nan"), "wr": 0.0, "trades": 0,
                "avg_ret": 0.0, "max_dd": 0.0}
    btc_c, btc_s = align_btc_to_symbol(df, btc_full, BTC_SMA_PERIOD)
    esp, vol_mom, atr_pctile = precompute_base(df)
    bb_wp = precompute_bb(df)
    return backtest(
        df,
        score_min=0.0,
        tp_score_mult=0.0,
        sl_score_mult=0.0,
        trail_score_mult=0.0,
        btc_close_aligned=btc_c,
        btc_sma_aligned=btc_s,
        ema_slope_pctile_arr=esp,
        vol_mom_arr=vol_mom,
        atr_pctile_full=atr_pctile,
        bb_width_pctile_arr=bb_wp,
        slippage=slippage,
    )


def main() -> None:
    print("=" * 80)
    print("=== c214 — c199 견고성 검증 (확장 심볼 × 슬리피지) ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"슬리피지: {SLIPPAGES}")
    print(f"WF folds: {len(WF_FOLDS)}")
    print("=" * 80)

    btc_full = load_historical(
        "KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if btc_full.empty:
        print("BTC 데이터 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    all_rows: list[dict] = []
    per_sym: dict[str, list[dict]] = {s: [] for s in SYMBOLS}

    for slip in SLIPPAGES:
        print(f"\n--- 슬리피지 {slip:.4f} ---")
        for sym in SYMBOLS:
            sym_results = []
            for fi, fold in enumerate(WF_FOLDS, 1):
                r = run_fold(sym, fold, btc_full, slip)
                sym_results.append(r)
                if r["trades"] > 0:
                    print(f"  {sym} fold{fi}: "
                          f"Sh={r['sharpe']:+.2f} "
                          f"WR={r['wr']*100:.0f}% "
                          f"n={r['trades']} "
                          f"avg={r['avg_ret']*100:+.2f}% "
                          f"MDD={r['max_dd']*100:+.2f}%")
                else:
                    print(f"  {sym} fold{fi}: 거래 없음")
            valid = [x for x in sym_results if x["trades"] > 0]
            if valid:
                avg_sh = float(np.nanmean([x["sharpe"] for x in valid]))
                tot = sum(x["trades"] for x in valid)
                wins = sum(int(round(x["wr"] * x["trades"])) for x in valid)
                wr = wins / tot if tot else 0.0
                row = {"sym": sym, "slip": slip, "sharpe": avg_sh,
                       "wr": wr, "trades": tot}
                per_sym[sym].append(row)
                all_rows.append(row)
                print(f"    → {sym} avg Sh={avg_sh:+.2f} "
                      f"WR={wr*100:.1f}% n={tot}")

    print("\n" + "=" * 80)
    print("=== 심볼별 요약 (모든 슬리피지 평균) ===")
    summary_lines = []
    for sym in SYMBOLS:
        rows = per_sym[sym]
        if not rows:
            print(f"  {sym}: 거래 없음")
            continue
        sh = float(np.nanmean([r["sharpe"] for r in rows]))
        tot = sum(r["trades"] for r in rows)
        wr = float(np.mean([r["wr"] for r in rows]))
        mark = "기존" if sym in EXISTING else "확장"
        summary_lines.append((sym, sh, wr, tot, mark))
        print(f"  [{mark}] {sym}: Sh={sh:+.2f}  "
              f"WR={wr*100:.1f}%  n={tot}")

    print("\n=== 슬리피지별 풀링 ===")
    for slip in SLIPPAGES:
        rows = [r for r in all_rows if r["slip"] == slip]
        if not rows:
            continue
        sh = float(np.nanmean([r["sharpe"] for r in rows]))
        tot = sum(r["trades"] for r in rows)
        wr = float(np.mean([r["wr"] for r in rows]))
        print(f"  slip={slip:.4f}: Sh={sh:+.2f} "
              f"WR={wr*100:.1f}% n={tot}")

    if all_rows:
        overall_sh = float(np.nanmean([r["sharpe"] for r in all_rows]))
        overall_tot = sum(r["trades"] for r in all_rows)
        overall_wr = float(np.mean([r["wr"] for r in all_rows]))
    else:
        overall_sh = float("nan")
        overall_tot = 0
        overall_wr = 0.0

    # 견고성 판정
    existing_rows = [r for r in all_rows if r["sym"] in EXISTING]
    extended_rows = [r for r in all_rows if r["sym"] in EXTENDED]
    if existing_rows and extended_rows:
        ex_sh = float(np.nanmean([r["sharpe"] for r in existing_rows]))
        nw_sh = float(np.nanmean([r["sharpe"] for r in extended_rows]))
        print(f"\n기존 심볼 평균 Sh={ex_sh:+.2f}  "
              f"확장 심볼 평균 Sh={nw_sh:+.2f}  "
              f"Δ={nw_sh - ex_sh:+.2f}")

    print("\n" + "=" * 80)
    print(f"Sharpe: {overall_sh:.2f}")
    print(f"WR: {overall_wr*100:.1f}%")
    print(f"trades: {overall_tot}")


if __name__ == "__main__":
    main()
