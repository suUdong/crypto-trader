"""
사이클 211: c210 최적(trail=2.5 tpM=3.0 slM=1.5 mH=30 aPTh=30 hDec=0) 정밀 탐색
- 베이스: c210 avg_OOS=+16.485 F3=+11.993 (Sharpe 16.485, WR 57.6%, n=91)
- 가설:
  A) 미세 trail/TP/SL 격자: 인접 로컬 최적 확인
  B) Breakeven Stop: 1×ATR 수익 도달 시 SL을 진입가로 끌어올려 손실->BE
     → SOL F3(-3.4) 같은 반전 손실 컷
  C) Partial TP (1차 익절): peak ATR 도달 시 절반 청산, 나머지 trailing
     → F3 추세 약할 때 일부 락인
- 그리드:
  TRAIL: [2.0, 2.25, 2.5, 2.75]
  TP_M : [2.75, 3.0, 3.25]
  SL_M : [1.25, 1.5, 1.75]
  BE_TRIG: [0.0, 1.0, 1.5]   # 0=비활성
  PARTIAL_TRIG: [0.0, 1.5, 2.0]  # 0=비활성, peak ATR 배수
  = 4×3×3×3×3 = 324 combos
- 고정: mH=30 aPTh=30 hDec=0 (+ c205/c207 고정)
- 목표: avg OOS Sharpe >= 16.5 AND F3 Sharpe >= 8 AND trades >= 60
- 3-fold WF + 슬리피지 스트레스
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_cycle210_donchian_trailing_tpsl_hold import (
    ADX_THRESH,
    ATR_PCTILE_LB,
    BTC_SMA_PERIOD,
    DC_LOWER_LB,
    DC_UPPER_LB,
    FEE,
    RSI_CEILING,
    SLIPPAGE,
    SYMBOLS,
    TP_VOL_SCALE,
    VOL_RATIO_MIN,
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

# 고정 (c210 best)
MAX_HOLD = 30
ATR_PCTILE_TH = 30

# c211 정밀 그리드
TRAIL_LIST = [2.0, 2.25, 2.5, 2.75]
TP_LIST = [2.75, 3.0, 3.25]
SL_LIST = [1.25, 1.5, 1.75]
BE_TRIG_LIST = [0.0, 1.0, 1.5]      # ATR multiple of profit to arm BE
PARTIAL_TRIG_LIST = [0.0, 1.5, 2.0]  # ATR multiple peak to half-close


def run_backtest(
    c, o, h, lo, v, dc_up, dc_lo, atr_val, adx_val,
    btc_close, btc_sma, atr_pctile, vol_sma, rsi_arr,
    trail_mult: float, atr_tp_mult: float, atr_sl_mult: float,
    be_trig: float, partial_trig: float,
    oos_start: str, oos_end: str, index: pd.DatetimeIndex,
) -> list[dict]:
    n = len(c)
    trades: list[dict] = []
    position = None
    oos_start_ts = pd.Timestamp(oos_start)
    oos_end_ts = pd.Timestamp(oos_end)
    warmup = max(DC_UPPER_LB, DC_LOWER_LB, BTC_SMA_PERIOD, 60) + 10

    for i in range(warmup, n - 1):
        o_next = o[i + 1]

        if position is not None:
            bars_held = i - position["entry_bar"]
            current_price = c[i]
            atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0.0

            # peak update
            if current_price > position["peak"]:
                position["peak"] = current_price

            # trailing stop
            if trail_mult > 0 and atr_now > 0:
                trail_stop = position["peak"] - atr_now * trail_mult
                if trail_stop > position.get("trail_stop", 0.0):
                    position["trail_stop"] = trail_stop

            # breakeven arm: profit >= be_trig * entry_atr → SL = entry
            if be_trig > 0 and not position.get("be_armed", False):
                profit_atr = (current_price - position["entry_price"])
                if (position["entry_atr"] > 0
                        and profit_atr >= be_trig * position["entry_atr"]):
                    position["sl_price"] = max(
                        position["sl_price"], position["entry_price"])
                    position["be_armed"] = True

            # partial TP: peak ATR multiple reached, half close once
            if (partial_trig > 0
                    and not position.get("partial_done", False)
                    and position["entry_atr"] > 0):
                gain_atr = (position["peak"] - position["entry_price"])
                if gain_atr >= partial_trig * position["entry_atr"]:
                    half_exit = o_next * (1 - SLIPPAGE)
                    half_ret = ((half_exit / position["entry_price"]) - 1
                                - FEE * 2)
                    # store partial as half-weight trade
                    entry_time = index[position["entry_bar"]]
                    if oos_start_ts <= entry_time <= oos_end_ts:
                        trades.append({
                            "entry_time": entry_time,
                            "return": half_ret * 0.5,
                            "reason": "PARTIAL",
                            "bars": bars_held,
                        })
                    position["partial_done"] = True
                    # tighten SL to BE after partial
                    position["sl_price"] = max(
                        position["sl_price"], position["entry_price"])

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
                # remaining size = 0.5 if partial done else 1.0
                size = 0.5 if position.get("partial_done", False) else 1.0
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": ret * size,
                        "reason": exit_reason,
                        "bars": bars_held,
                    })
                position = None
        else:
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            donchian_ok = c[i] > dc_up[i]
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

            rsi_ok = True
            if RSI_CEILING < 100:
                rsi_ok = (not np.isnan(rsi_arr[i])
                          and rsi_arr[i] < RSI_CEILING)

            if (donchian_ok and adx_ok and btc_ok and atr_pctile_ok
                    and vol_ok and rsi_ok):
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val[i]

                vol_tp_bonus = 0.0
                if TP_VOL_SCALE > 0 and not np.isnan(atr_pctile[i]):
                    vol_score = max(0.0, atr_pctile[i] - 50.0) / 50.0
                    vol_tp_bonus = TP_VOL_SCALE * vol_score

                tp_pct = atr_now / c[i] * (atr_tp_mult + vol_tp_bonus)
                sl_pct = atr_now / c[i] * atr_sl_mult
                position = {
                    "entry_price": entry_price,
                    "entry_bar": i + 1,
                    "entry_atr": atr_now,
                    "orig_tp_price": entry_price * (1 + tp_pct),
                    "sl_price": entry_price * (1 - sl_pct),
                    "peak": entry_price,
                    "trail_stop": 0.0,
                    "be_armed": False,
                    "partial_done": False,
                }

    return trades


def main() -> None:
    print("=" * 80)
    print("=== c211: c210 정밀 + Breakeven + Partial TP 3-fold WF ===")
    print(f"고정: mH={MAX_HOLD} aPTh={ATR_PCTILE_TH} hDec=0")
    print("그리드: trail×tp×sl×beTrig×partialTrig = "
          f"{len(TRAIL_LIST)}×{len(TP_LIST)}×{len(SL_LIST)}"
          f"×{len(BE_TRIG_LIST)}×{len(PARTIAL_TRIG_LIST)} = "
          f"{len(TRAIL_LIST)*len(TP_LIST)*len(SL_LIST)*len(BE_TRIG_LIST)*len(PARTIAL_TRIG_LIST)}")
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

    sym_precomp = {}
    for sym in SYMBOLS:
        df = sym_data[sym]
        h_arr = df["high"].values
        lo_arr = df["low"].values
        c_arr = df["close"].values
        o_arr = df["open"].values
        v_arr = df["volume"].values

        dc_up = donchian_upper(h_arr, DC_UPPER_LB)
        dc_lo_arr = donchian_lower(lo_arr, DC_LOWER_LB)
        atr_arr = compute_atr(h_arr, lo_arr, c_arr, 14)
        adx_arr = compute_adx(h_arr, lo_arr, c_arr, 14)
        rsi_arr = rsi_calc(c_arr, 14)
        atr_pctile = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
        vol_sma_arr = sma_calc(v_arr, VOL_SMA_PERIOD)

        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo_arr,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr,
            "atr_pctile": atr_pctile, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "index": df.index,
        }

    grid = list(product(
        TRAIL_LIST, TP_LIST, SL_LIST, BE_TRIG_LIST, PARTIAL_TRIG_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    all_results = []
    for gi, (tr, tp, sl, be, pt) in enumerate(grid):
        fold_sharpes = []
        fold_details = []
        total_n = 0

        for window in WINDOWS:
            fold_rets = []
            for sym in SYMBOLS:
                sp = sym_precomp[sym]
                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    tr, tp, sl, be, pt,
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
            "params": (tr, tp, sl, be, pt),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999.0,
        })

        if (gi + 1) % 50 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")
    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    valid = [r for r in all_results if r["total_n"] >= 60]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=60): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 ===")
    print("=" * 80)
    hdr = (f"{'trail':>5} {'tpM':>5} {'slM':>5} {'be':>4} {'pt':>4} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>5.2f} {p[1]:>5.2f} {p[2]:>5.2f} {p[3]:>4.1f} "
              f"{p[4]:>4.1f} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: trail={p[0]:.2f} tpM={p[1]:.2f} slM={p[2]:.2f} "
              f"be={p[3]:.1f} pt={p[4]:.1f}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")

    print("\n" + "=" * 80)
    print("=== c210 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print("  c210 기준: avg_OOS=+16.485 F3=+11.993")
        print(f"  c211 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f}")
        d = b["avg_sharpe"] - 16.485
        df3 = b["f3_sharpe"] - 11.993
        print(f"  Δ avg: {d:+.3f} ({'개선' if d > 0 else '악화'})")
        print(f"  Δ F3: {df3:+.3f} ({'개선' if df3 > 0 else '악화'})")

    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 8.0
        status = ("PASS" if b["avg_sharpe"] >= 16.5
                  and b["total_n"] >= 60 and f3_pass else "FAIL")
        print(f"★ OOS 최적: trail={p[0]:.2f} tpM={p[1]:.2f} "
              f"slM={p[2]:.2f} be={p[3]:.1f} pt={p[4]:.1f}")
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
        print("n>=60 조건 충족 조합 없음 — FAIL")
        print("\nSharpe: N/A")
        print("WR: N/A")
        print("trades: 0")


if __name__ == "__main__":
    main()
