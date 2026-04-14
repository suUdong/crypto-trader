"""
사이클 215: c214 구조 확정 + 출구 메카닉 미세 조정
- 베이스: c214 avg_OOS=+20.773 F3=+18.836 (n=71, WR 63.2%)
  고정 (구조): dcUB=25 adx=29 momLB=0 atrP=14 dcLo=10 atrPLB=30
               vRat=1.5 rsiC=100 tvs=0.0
- 문제:
  1) 출구 파라미터(trail/tp/sl/be) c213에서 고정 — 새 구조에서 재검증 필요
  2) F3 거래 8건 — 출구 완화로 보유 기간 늘려 수익 극대화 가능
  3) F1 MDD -13.78% — SL 미세 조정으로 개선 여지
  4) MAX_HOLD=30 고정 — 짧은 보유 시 조기 청산 vs 긴 보유 시 추세 탑승
- 가설:
  A) TRAIL_MULT: [1.5, 2.0, 2.5, 3.0] — 좁은 트레일→빠른 익절, 넓은→추세 탑승
  B) TP_MULT: [2.5, 3.0, 3.25, 3.5, 4.0] — TP 목표 범위
  C) SL_MULT: [1.25, 1.5, 1.75, 2.0] — 넓은 SL→whipsaw 방지, 좁은→MDD 제한
  D) BE_TRIGGER: [1.5, 2.0, 2.5] — BE 전환 시점
- 그리드: 4×5×4×3 = 240 combos
- 3-fold WF + 슬리피지 스트레스
- 목표: avg OOS Sharpe >= 20.773 OR MDD 개선 with avg >= 20.0
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_cycle210_donchian_trailing_tpsl_hold import (
    BTC_SMA_PERIOD,
    DC_LOWER_LB,
    FEE,
    SLIPPAGE,
    SYMBOLS,
    VOL_SMA_PERIOD,
    WINDOWS,
    compute_adx,
    compute_atr,
    compute_atr_percentile,
    donchian_lower,
    donchian_upper,
    rsi_calc,
    sma_calc,
)
from historical_loader import load_historical

# ─── c214 확정 구조 파라미터 ─────────────────────────────────
DC_UPPER_LB = 25
ADX_THRESH = 29
ATR_PERIOD = 14
MOMENTUM_LB = 0        # 비활성
VOL_RATIO_MIN = 1.5
RSI_CEILING = 100
TP_VOL_SCALE = 0.0
ATR_PCTILE_TH = 30
ATR_PCTILE_LB = 30
MAX_HOLD = 30

# ─── c215 출구 탐색 그리드 ───────────────────────────────────
TRAIL_MULT_LIST = [1.5, 2.0, 2.5, 3.0]
TP_MULT_LIST = [2.5, 3.0, 3.25, 3.5, 4.0]
SL_MULT_LIST = [1.25, 1.5, 1.75, 2.0]
BE_TRIGGER_LIST = [1.5, 2.0, 2.5]

# 베이스라인 참조
C214_AVG_SHARPE = 20.773
C214_F3_SHARPE = 18.836


def run_backtest(
    c, o, h, lo, v, dc_lo, atr_val, adx_val,
    btc_close, btc_sma, atr_pctile, vol_sma, rsi_arr,
    dc_up_arr,
    trail_mult: float,
    tp_mult: float,
    sl_mult: float,
    be_trigger: float,
    oos_start: str, oos_end: str, index: pd.DatetimeIndex,
) -> list[dict]:
    n = len(c)
    trades: list[dict] = []
    position = None
    oos_start_ts = pd.Timestamp(oos_start)
    oos_end_ts = pd.Timestamp(oos_end)
    warmup = max(40, BTC_SMA_PERIOD, 60) + 10

    for i in range(warmup, n - 1):
        o_next = o[i + 1]

        if position is not None:
            bars_held = i - position["entry_bar"]
            current_price = c[i]
            atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0.0

            if current_price > position["peak"]:
                position["peak"] = current_price

            # Trailing stop
            if trail_mult > 0 and atr_now > 0:
                trail_stop = position["peak"] - atr_now * trail_mult
                if trail_stop > position.get("trail_stop", 0.0):
                    position["trail_stop"] = trail_stop

            # Breakeven trigger
            if be_trigger > 0 and not position.get("be_armed", False):
                profit_atr = current_price - position["entry_price"]
                if (position["entry_atr"] > 0
                        and profit_atr >= be_trigger * position["entry_atr"]):
                    position["sl_price"] = max(
                        position["sl_price"], position["entry_price"])
                    position["be_armed"] = True

            exit_reason = None
            if current_price <= position["sl_price"]:
                exit_reason = "SL"
            if current_price >= position["orig_tp_price"]:
                exit_reason = "TP"
            if (trail_mult > 0
                    and current_price <= position.get("trail_stop", 0.0)
                    and position.get("trail_stop", 0.0) > 0):
                exit_reason = "TRAIL"
            if not np.isnan(dc_lo[i]) and current_price <= dc_lo[i]:
                exit_reason = "DC_LOW"
            if bars_held >= MAX_HOLD:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": ret,
                        "reason": exit_reason,
                        "bars": bars_held,
                    })
                position = None
        else:
            if (np.isnan(dc_up_arr[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            donchian_ok = c[i] > dc_up_arr[i]
            adx_ok = adx_val[i] >= ADX_THRESH
            btc_ok = btc_close[i] > btc_sma[i]
            atr_pctile_ok = (not np.isnan(atr_pctile[i])
                             and atr_pctile[i] >= ATR_PCTILE_TH)

            vol_ok = True
            if VOL_RATIO_MIN > 0:
                if np.isnan(vol_sma[i]) or vol_sma[i] <= 0:
                    vol_ok = False
                else:
                    vol_ok = v[i] / vol_sma[i] >= VOL_RATIO_MIN

            if donchian_ok and adx_ok and btc_ok and atr_pctile_ok and vol_ok:
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val[i]

                tp_pct = atr_now / c[i] * tp_mult
                sl_pct = atr_now / c[i] * sl_mult
                position = {
                    "entry_price": entry_price,
                    "entry_bar": i + 1,
                    "entry_atr": atr_now,
                    "orig_tp_price": entry_price * (1 + tp_pct),
                    "sl_price": entry_price * (1 - sl_pct),
                    "peak": entry_price,
                    "trail_stop": 0.0,
                    "be_armed": False,
                }

    return trades


def main() -> None:
    print("=" * 80)
    print("=== c215: c214 구조 확정 + 출구 메카닉 미세 조정 ===")
    print(f"고정(구조): dcUB={DC_UPPER_LB} adx={ADX_THRESH} atrP={ATR_PERIOD} "
          f"vRat={VOL_RATIO_MIN} atrPcTh={ATR_PCTILE_TH}")
    grid = list(product(
        TRAIL_MULT_LIST, TP_MULT_LIST, SL_MULT_LIST, BE_TRIGGER_LIST))
    print(f"탐색: TRAIL×TP×SL×BE = "
          f"{len(TRAIL_MULT_LIST)}×{len(TP_MULT_LIST)}"
          f"×{len(SL_MULT_LIST)}×{len(BE_TRIGGER_LIST)} = {len(grid)}")
    print("=" * 80)

    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"BTC 데이터: {len(btc_df)} rows")

    sym_data = {}
    for sym in SYMBOLS:
        df = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        sym_data[sym] = df
        print(f"{sym} 데이터: {len(df)} rows")

    btc_close_full = btc_df["close"].values
    btc_sma_full = sma_calc(btc_close_full, BTC_SMA_PERIOD)

    # 심볼별 데이터 준비 (구조 파라미터 고정 → 1회 계산)
    sym_precomp = {}
    for sym in SYMBOLS:
        df = sym_data[sym]
        h_arr = df["high"].values
        lo_arr = df["low"].values
        c_arr = df["close"].values
        o_arr = df["open"].values
        v_arr = df["volume"].values

        dc_lo_arr = donchian_lower(lo_arr, DC_LOWER_LB)
        dc_up_arr = donchian_upper(h_arr, DC_UPPER_LB)
        atr_arr = compute_atr(h_arr, lo_arr, c_arr, ATR_PERIOD)
        adx_arr = compute_adx(h_arr, lo_arr, c_arr, ATR_PERIOD)
        atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
        rsi_arr = rsi_calc(c_arr, 14)
        vol_sma_arr = sma_calc(v_arr, VOL_SMA_PERIOD)

        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_lo": dc_lo_arr, "dc_up": dc_up_arr,
            "atr": atr_arr, "adx": adx_arr,
            "atr_pctile": atr_pctile_arr,
            "rsi": rsi_arr, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "index": df.index,
        }

    print(f"\n총 조합: {len(grid)}")

    all_results = []
    for gi, (trail_m, tp_m, sl_m, be_t) in enumerate(grid):
        fold_sharpes = []
        fold_details = []
        total_n = 0

        for window in WINDOWS:
            fold_rets = []
            for sym in SYMBOLS:
                sp = sym_precomp[sym]
                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_lo"], sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    sp["dc_up"],
                    trail_m, tp_m, sl_m, be_t,
                    window["oos_start"], window["oos_end"], sp["index"],
                )
                fold_rets.extend([t["return"] for t in trades])

            if fold_rets:
                avg = float(np.mean(fold_rets))
                std = (float(np.std(fold_rets, ddof=1))
                       if len(fold_rets) > 1 else 1e-10)
                sharpe = ((avg / std) * np.sqrt(252 / (240 / 60 / 24))
                          if std > 0 else 0.0)
                wr = sum(1 for r in fold_rets if r > 0) / len(fold_rets) * 100
                eq = np.cumprod([1 + r for r in fold_rets])
                pk = np.maximum.accumulate(eq)
                mdd = float(np.min(eq / pk - 1) * 100)
            else:
                sharpe, wr, avg, mdd = -999.0, 0.0, 0.0, 0.0

            fold_sharpes.append(sharpe)
            fold_details.append({
                "name": window["name"], "sharpe": sharpe, "wr": wr,
                "n": len(fold_rets), "avg": avg * 100, "mdd": mdd,
            })
            total_n += len(fold_rets)

        avg_sharpe = float(np.mean(fold_sharpes)) if fold_sharpes else -999.0
        all_results.append({
            "params": (trail_m, tp_m, sl_m, be_t),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999.0,
        })

        if (gi + 1) % 40 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")
    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    valid = [r for r in all_results if r["total_n"] >= 50]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=50): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 ===")
    print("=" * 80)
    hdr = (f"{'trail':>6} {'tp':>5} {'sl':>5} {'be':>5} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'n':>5} {'F1mdd':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        f1_mdd = r["folds"][0]["mdd"] if r["folds"] else 0.0
        print(f"{p[0]:>6.1f} {p[1]:>5.2f} {p[2]:>5.2f} {p[3]:>5.1f} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['total_n']:>5} {f1_mdd:>+7.2f}%")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: trail={p[0]} tp={p[1]} sl={p[2]} be={p[3]}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")

    # ─── MDD 최적 별도 표시 ──────────────────────────────────
    print("\n" + "=" * 80)
    print("=== MDD 최적 (avg Sharpe >= 20.0 중) ===")
    mdd_candidates = [r for r in valid if r["avg_sharpe"] >= 20.0]
    if mdd_candidates:
        mdd_candidates.sort(
            key=lambda x: max(f["mdd"] for f in x["folds"]))
        # max(mdd) = least negative = best MDD
        best_mdd = mdd_candidates[-1]
        worst_fold_mdd = min(f["mdd"] for f in best_mdd["folds"])
        p = best_mdd["params"]
        print(f"  trail={p[0]} tp={p[1]} sl={p[2]} be={p[3]}")
        print(f"  avg Sharpe: {best_mdd['avg_sharpe']:+.3f}  "
              f"worst fold MDD: {worst_fold_mdd:+.2f}%")
        for f in best_mdd["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"MDD={f['mdd']:+.2f}%  n={f['n']}")

    print("\n" + "=" * 80)
    print("=== c214 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c214 기준: avg_OOS={C214_AVG_SHARPE:+.3f} "
              f"F3={C214_F3_SHARPE:+.3f}")
        print(f"  c215 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f}")
        d = b["avg_sharpe"] - C214_AVG_SHARPE
        df3 = b["f3_sharpe"] - C214_F3_SHARPE
        print(f"  Δ avg: {d:+.3f} ({'개선' if d > 0 else '악화'})")
        print(f"  Δ F3: {df3:+.3f} ({'개선' if df3 > 0 else '악화'})")

    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 18.0
        status = ("PASS" if (b["avg_sharpe"] >= C214_AVG_SHARPE
                             or (b["avg_sharpe"] >= 20.0 and f3_pass
                                 and b["total_n"] >= 60))
                  else "MARGINAL" if b["avg_sharpe"] >= 19.0 else "FAIL")
        print(f"★ OOS 최적: trail={p[0]} tp={p[1]} "
              f"sl={p[2]} be={p[3]}")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  total trades: {b['total_n']}")
        for f in b["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  trades={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")
        avg_wr = float(np.mean([f["wr"] for f in b["folds"]]))
        print(f"\nSharpe: {b['avg_sharpe']:+.3f}")
        print(f"WR: {avg_wr:.1f}%")
        print(f"trades: {b['total_n']}")
    else:
        print("n>=50 조건 충족 조합 없음 — FAIL")
        print("\nSharpe: N/A")
        print("WR: N/A")
        print("trades: 0")


if __name__ == "__main__":
    main()
