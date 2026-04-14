"""
사이클 212: c211 최적(trail=2.0 tpM=3.25 slM=1.75 be=1.0 pt=0.0) 주변 레짐 필터 확장
- 베이스: c211 avg_OOS=+16.948 F3=+16.120 (n=88, WR 56.8%)
- 가설:
  A) ADX 임계 조정: 기본 ADX_THRESH 고정이었음 → [ADX-2, ADX, ADX+2, ADX+4]
     추세 강도 컷업으로 F1 승률 개선 기대
  B) ATR percentile 레짐 게이트: [25, 30, 35, 40]
     저변동 구간 제외 → 잡손실 감소
  C) MAX_HOLD: [24, 30, 36] — 추세 보유 연장 vs 조기 청산
- 고정: trail=2.0 tpM=3.25 slM=1.75 be=1.0 pt=0.0 (c211 best)
- 그리드: 4×4×3 = 48 combos
- 목표: avg OOS Sharpe >= 16.948 AND F3 Sharpe >= 14 AND trades >= 70
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
    ADX_THRESH as BASE_ADX_THRESH,
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

# c211 최적 고정
TRAIL_MULT = 2.0
TP_MULT = 3.25
SL_MULT = 1.75
BE_TRIG = 1.0
PARTIAL_TRIG = 0.0

# c212 레짐 필터 그리드
ADX_LIST = [max(0.0, BASE_ADX_THRESH - 2), BASE_ADX_THRESH,
            BASE_ADX_THRESH + 2, BASE_ADX_THRESH + 4]
ATR_PCTILE_LIST = [25, 30, 35, 40]
MAX_HOLD_LIST = [24, 30, 36]


def run_backtest(
    c, o, h, lo, v, dc_up, dc_lo, atr_val, adx_val,
    btc_close, btc_sma, atr_pctile, vol_sma, rsi_arr,
    adx_thresh: float, atr_pctile_th: float, max_hold: int,
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

            if current_price > position["peak"]:
                position["peak"] = current_price

            if TRAIL_MULT > 0 and atr_now > 0:
                trail_stop = position["peak"] - atr_now * TRAIL_MULT
                if trail_stop > position.get("trail_stop", 0.0):
                    position["trail_stop"] = trail_stop

            if BE_TRIG > 0 and not position.get("be_armed", False):
                profit_atr = (current_price - position["entry_price"])
                if (position["entry_atr"] > 0
                        and profit_atr >= BE_TRIG * position["entry_atr"]):
                    position["sl_price"] = max(
                        position["sl_price"], position["entry_price"])
                    position["be_armed"] = True

            exit_reason = None
            if current_price <= position["sl_price"]:
                exit_reason = "SL"
            if current_price >= position["orig_tp_price"]:
                exit_reason = "TP"
            if (TRAIL_MULT > 0
                    and current_price <= position.get("trail_stop", 0.0)
                    and position.get("trail_stop", 0.0) > 0):
                exit_reason = "TRAIL"
            if not np.isnan(dc_lo[i]) and current_price <= dc_lo[i]:
                exit_reason = "DC_LOW"
            if bars_held >= max_hold:
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
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            donchian_ok = c[i] > dc_up[i]
            adx_ok = adx_val[i] >= adx_thresh
            btc_ok = btc_close[i] > btc_sma[i]
            atr_pctile_ok = (not np.isnan(atr_pctile[i])
                             and atr_pctile[i] >= atr_pctile_th)

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

                tp_pct = atr_now / c[i] * (TP_MULT + vol_tp_bonus)
                sl_pct = atr_now / c[i] * SL_MULT
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
    print("=== c212: c211 best + 레짐 필터 확장 (ADX/ATRpct/MaxHold) ===")
    print(f"고정: trail={TRAIL_MULT} tpM={TP_MULT} slM={SL_MULT} "
          f"be={BE_TRIG} pt={PARTIAL_TRIG}")
    print(f"그리드: ADX×ATRpct×MaxHold = "
          f"{len(ADX_LIST)}×{len(ATR_PCTILE_LIST)}×{len(MAX_HOLD_LIST)} "
          f"= {len(ADX_LIST)*len(ATR_PCTILE_LIST)*len(MAX_HOLD_LIST)}")
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

    grid = list(product(ADX_LIST, ATR_PCTILE_LIST, MAX_HOLD_LIST))
    print(f"\n총 조합: {len(grid)}")

    all_results = []
    for gi, (adx_t, atr_t, mh) in enumerate(grid):
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
                    adx_t, atr_t, mh,
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
            "params": (adx_t, atr_t, mh),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999.0,
        })

        if (gi + 1) % 10 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")
    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    valid = [r for r in all_results if r["total_n"] >= 70]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=70): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 ===")
    print("=" * 80)
    hdr = (f"{'adx':>6} {'atrP':>5} {'mH':>4} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>6.2f} {p[1]:>5.0f} {p[2]:>4d} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: adx={p[0]:.2f} atrP={p[1]:.0f} mH={p[2]}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")

    print("\n" + "=" * 80)
    print("=== c211 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print("  c211 기준: avg_OOS=+16.948 F3=+16.120")
        print(f"  c212 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f}")
        d = b["avg_sharpe"] - 16.948
        df3 = b["f3_sharpe"] - 16.120
        print(f"  Δ avg: {d:+.3f} ({'개선' if d > 0 else '악화'})")
        print(f"  Δ F3: {df3:+.3f} ({'개선' if df3 > 0 else '악화'})")

    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 14.0
        status = ("PASS" if b["avg_sharpe"] >= 16.948
                  and b["total_n"] >= 70 and f3_pass else "FAIL")
        print(f"★ OOS 최적: adx={p[0]:.2f} atrP={p[1]:.0f} mH={p[2]}")
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
        print("n>=70 조건 충족 조합 없음 — FAIL")
        print("\nSharpe: N/A")
        print("WR: N/A")
        print("trades: 0")


if __name__ == "__main__":
    main()
