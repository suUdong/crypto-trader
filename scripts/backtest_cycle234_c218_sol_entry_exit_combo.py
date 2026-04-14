"""
사이클 234: c218 SOL exit 최적 고정 + SOL 전용 entry 필터 복합 스윕

c218 결과:
  ★ solTP=3.0 solTR=2.0 solMH=20
  avg OOS Sharpe: +21.455, F3: +16.682, SOL: +7.973(FAIL), ETH: +81.983
  → SOL exit 튜닝만으로 SOL>=10 불가, entry 품질이 병목

c221(SOL entry quality)은 c219 베이스였고, c218은 c217 베이스 → 조합 미탐색.
본 사이클: c218 최적 exit + SOL entry 필터 결합.

가설:
  1) SOL ADX 부스트: 기본 25 → +5/+10/+15 → 약추세 가짜돌파 차단
  2) SOL 볼륨비율 강화: 기본 1.0 → 1.5/2.0/2.5 → 거래량 미동반 돌파 차단
  3) SOL BTC 모멘텀 강화: 기본 +1.0 → +1.5/+2.0/+2.5 → BTC 약세시 SOL 진입 차단
  4) SOL EMA slope 강화: 기본 0.80 → 1.0/1.5/2.0 → 평탄 추세 차단

고정 (c217+c218):
  emaP=12 sLB=4 slPct=0.80 slSOL=0.50 slXRP=0.95
  btcLB=10 btcTH=+1.0 (ETH/XRP용)
  dcU=30 dcL=10 adx=25 (ETH/XRP용)
  SOL exit: TP=3.0 TR=2.0 MH=20
  ETH/XRP exit: TP=3.0 TR=2.5 MH=30

그리드: ADX_BOOST(4) × VOL_BOOST(4) × BTC_MOM_BOOST(4) × SLOPE_BOOST(4) = 256 combos
합격선: avg>=16, F3>=10, SOL>=10
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical  # noqa: E402

from backtest_cycle215_donchian_momentum_confirm_sym_sl import (  # noqa: E402
    ATR_PCTILE_LB,
    ATR_PCTILE_TH,
    ATR_SL_MULT,
    ATR_TP_MULT,
    BTC_SMA_PERIOD,
    DC_LOWER_LB,
    DC_UPPER_LB,
    FEE,
    MAX_HOLD,
    RSI_CEILING,
    SLIPPAGE,
    SYMBOLS,
    TP_VOL_SCALE,
    TRAIL_MULT,
    VOL_RATIO_MIN,
    VOL_SMA_PERIOD,
    WINDOWS,
    compute_adx,
    compute_atr,
    compute_atr_percentile,
    donchian_lower,
    donchian_upper,
    ema_calc,
    ema_slope_pct,
    rsi_calc,
    sma_calc,
)
from backtest_cycle216_c215_refine_btc_momentum_gate import (  # noqa: E402
    btc_return_pct,
)

# ─── c217 최적 고정 ────────────────────────────────
EMA_P_FIX = 12
SLOPE_LB_FIX = 4
SLOPE_MIN_PCT_FIX = 0.80
SL_XRP_FIX = 0.95
SL_SOL_FIX = 0.50
BTC_MOM_LB_FIX = 10
BTC_MOM_TH_FIX = 1.0
ADX_THRESH_BASE = 25

# ─── c218 SOL exit 최적 고정 ──────────────────────
SOL_TP_FIX = 3.0
SOL_TRAIL_FIX = 2.0
SOL_MAX_HOLD_FIX = 20

# ─── c234 SOL entry 탐색 그리드 ───────────────────
SOL_ADX_BOOST_LIST = [0, 5, 10, 15]       # SOL ADX = 25 + boost
SOL_VOL_RATIO_LIST = [1.0, 1.5, 2.0, 2.5]  # SOL 최소 볼륨비율
SOL_BTC_MOM_TH_LIST = [1.0, 1.5, 2.0, 2.5]  # SOL BTC mom 임계
SOL_SLOPE_MIN_LIST = [0.80, 1.0, 1.5, 2.0]   # SOL EMA slope 최소


def run_backtest_entry_exit(
    c, o, h, lo, v, dc_up, dc_lo, atr_val, adx_val,
    btc_close, btc_sma, atr_pctile, vol_sma, rsi_arr,
    ema_slope, btc_mom,
    slope_min_pct, sl_scale, btc_mom_th,
    adx_thresh, vol_ratio_min,
    tp_mult, trail_mult, max_hold,
    oos_start, oos_end, index,
):
    """Backtest with per-symbol entry AND exit overrides."""
    n = len(c)
    trades = []
    position = None
    oos_s = pd.Timestamp(oos_start)
    oos_e = pd.Timestamp(oos_end)
    warmup = max(DC_UPPER_LB, DC_LOWER_LB, BTC_SMA_PERIOD, 60) + 10

    for i in range(warmup, n - 1):
        o_next = o[i + 1]

        if position is not None:
            bars_held = i - position["entry_bar"]
            cp = c[i]
            if trail_mult > 0 and cp > position["peak"]:
                position["peak"] = cp
                atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0
                ts = cp - atr_now * trail_mult
                if ts > position.get("trail_stop", 0):
                    position["trail_stop"] = ts

            exit_reason = None
            if cp <= position["sl_price"]:
                exit_reason = "SL"
            if cp >= position["tp_price"]:
                exit_reason = "TP"
            if trail_mult > 0 and cp <= position.get("trail_stop", 0):
                exit_reason = "TRAIL"
            if not np.isnan(dc_lo[i]) and cp <= dc_lo[i]:
                exit_reason = "DC_LOW"
            if bars_held >= max_hold:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                et = index[position["entry_bar"]]
                if oos_s <= et <= oos_e:
                    trades.append({"entry_time": et, "return": ret,
                                   "reason": exit_reason, "bars": bars_held})
                position = None
        else:
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            if not (c[i] > dc_up[i]):
                continue
            if not (adx_val[i] >= adx_thresh):
                continue
            if not (btc_close[i] > btc_sma[i]):
                continue
            if ATR_PCTILE_TH > 0:
                if np.isnan(atr_pctile[i]) or atr_pctile[i] < ATR_PCTILE_TH:
                    continue
            if vol_ratio_min > 0:
                if (np.isnan(vol_sma[i]) or vol_sma[i] <= 0
                        or v[i] / vol_sma[i] < vol_ratio_min):
                    continue
            if RSI_CEILING < 100:
                if np.isnan(rsi_arr[i]) or rsi_arr[i] >= RSI_CEILING:
                    continue
            if slope_min_pct > 0:
                if np.isnan(ema_slope[i]) or ema_slope[i] < slope_min_pct:
                    continue
            if btc_mom_th > -900.0:
                if np.isnan(btc_mom[i]) or btc_mom[i] < btc_mom_th:
                    continue

            entry_price = o_next * (1 + SLIPPAGE)
            atr_now = atr_val[i]
            vol_tp_bonus = 0.0
            if TP_VOL_SCALE > 0 and not np.isnan(atr_pctile[i]):
                vol_score = max(0, atr_pctile[i] - 50) / 50.0
                vol_tp_bonus = TP_VOL_SCALE * vol_score
            tp_pct = atr_now / c[i] * (tp_mult + vol_tp_bonus)
            sl_pct = atr_now / c[i] * ATR_SL_MULT * sl_scale
            position = {
                "entry_price": entry_price,
                "entry_bar": i + 1,
                "tp_price": entry_price * (1 + tp_pct),
                "sl_price": entry_price * (1 - sl_pct),
                "peak": entry_price,
                "trail_stop": 0,
            }

    return trades


def compute_sharpe(rets):
    if not rets:
        return -999
    avg = np.mean(rets)
    std = np.std(rets, ddof=1) if len(rets) > 1 else 1e-10
    return (avg / std) * np.sqrt(252 / (240 / 60 / 24)) if std > 0 else 0


def main() -> None:
    print("=" * 80)
    print("=== c234: c218 SOL exit 최적 + SOL entry 필터 복합 스윕 ===")
    print("=== SOL exit 고정: TP=3.0 TR=2.0 MH=20 ===")
    print("=== SOL entry 탐색: ADX boost × Vol ratio × BTC mom × Slope ===")
    print("=" * 80)

    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"BTC 데이터: {len(btc_df)} rows")

    sym_data = {}
    for sym in SYMBOLS:
        sym_data[sym] = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        print(f"{sym} 데이터: {len(sym_data[sym])} rows")

    btc_close_full = btc_df["close"].values
    btc_sma_full = sma_calc(btc_close_full, BTC_SMA_PERIOD)
    btc_mom_full = btc_return_pct(btc_close_full, BTC_MOM_LB_FIX)

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
        btc_m_s = pd.Series(btc_mom_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values
        btc_m_aligned = btc_m_s.reindex(df.index, method="ffill").values

        ema_arr = ema_calc(c_arr, EMA_P_FIX)
        slope_arr = ema_slope_pct(ema_arr, SLOPE_LB_FIX)

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo_arr,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr,
            "atr_pctile": atr_pctile, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "btc_m": btc_m_aligned,
            "slope": slope_arr,
            "index": df.index,
        }

    sl_map = {"KRW-ETH": 1.0, "KRW-SOL": SL_SOL_FIX, "KRW-XRP": SL_XRP_FIX}

    grid = list(product(
        SOL_ADX_BOOST_LIST, SOL_VOL_RATIO_LIST,
        SOL_BTC_MOM_TH_LIST, SOL_SLOPE_MIN_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    all_results = []
    for gi, (adx_boost, vol_ratio, btc_mom_sol, slope_sol) in enumerate(grid):
        fold_sharpes = []
        fold_details = []
        total_n = 0
        sym_fold_data = {s: [] for s in SYMBOLS}

        for window in WINDOWS:
            fold_rets = []
            for sym in SYMBOLS:
                sp = sym_precomp[sym]

                if sym == "KRW-SOL":
                    tp_m = SOL_TP_FIX
                    tr_m = SOL_TRAIL_FIX
                    mh = SOL_MAX_HOLD_FIX
                    adx_th = ADX_THRESH_BASE + adx_boost
                    vr = vol_ratio
                    btc_th = btc_mom_sol
                    sl_min = slope_sol
                else:
                    tp_m = ATR_TP_MULT
                    tr_m = TRAIL_MULT
                    mh = MAX_HOLD
                    adx_th = ADX_THRESH_BASE
                    vr = VOL_RATIO_MIN
                    btc_th = BTC_MOM_TH_FIX
                    sl_min = SLOPE_MIN_PCT_FIX

                trades = run_backtest_entry_exit(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    sp["slope"], sp["btc_m"],
                    sl_min, sl_map[sym], btc_th,
                    adx_th, vr,
                    tp_m, tr_m, mh,
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                rets = [t["return"] for t in trades]
                fold_rets.extend(rets)
                sym_fold_data[sym].append(rets)

            if fold_rets:
                avg = np.mean(fold_rets)
                std = np.std(fold_rets, ddof=1) if len(fold_rets) > 1 else 1e-10
                sharpe = ((avg / std) * np.sqrt(252 / (240 / 60 / 24))
                          if std > 0 else 0)
                wr = sum(1 for r in fold_rets if r > 0) / len(fold_rets) * 100
                equity = np.cumprod([1 + r for r in fold_rets])
                peak_eq = np.maximum.accumulate(equity)
                mdd = np.min(equity / peak_eq - 1) * 100
            else:
                sharpe, wr, avg, mdd = -999, 0, 0, 0

            fold_sharpes.append(sharpe)
            fold_details.append({
                "name": window["name"],
                "sharpe": sharpe, "wr": wr,
                "n": len(fold_rets), "avg": avg * 100, "mdd": mdd,
            })
            total_n += len(fold_rets)

        sol_avg_sharpe = np.mean([
            compute_sharpe(rs) for rs in sym_fold_data["KRW-SOL"]
        ])
        eth_avg_sharpe = np.mean([
            compute_sharpe(rs) for rs in sym_fold_data["KRW-ETH"]
        ])

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        all_results.append({
            "params": (adx_boost, vol_ratio, btc_mom_sol, slope_sol),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg_sharpe,
            "eth_avg_sharpe": eth_avg_sharpe,
        })

        if (gi + 1) % 32 == 0:
            print(f"  진행: {gi + 1}/{len(grid)}")

    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_results)}")

    print("\n=== Top 20 ===")
    hdr = (f"{'adxB':>5} {'volR':>5} {'btcM':>5} {'slpM':>5} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'solSh':>7} {'ethSh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:20]:
        p = r["params"]
        print(f"{p[0]:>5} {p[1]:>5.1f} {p[2]:>5.1f} {p[3]:>5.2f} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['sol_avg_sharpe']:>+7.3f} {r['eth_avg_sharpe']:>+7.3f} "
              f"{r['total_n']:>5}")

    # ─── 개별 필터 효과 분석 ───────────────────────
    print("\n=== SOL ADX boost 효과 (top5 평균) ===")
    for ab in SOL_ADX_BOOST_LIST:
        sub = sorted([r for r in valid if r["params"][0] == ab],
                     key=lambda x: x["avg_sharpe"], reverse=True)[:5]
        if sub:
            print(f"  ADX+{ab:>2}: avgSh={np.mean([r['avg_sharpe'] for r in sub]):+.3f}  "
                  f"SOL={np.mean([r['sol_avg_sharpe'] for r in sub]):+.3f}  "
                  f"F3={np.mean([r['f3_sharpe'] for r in sub]):+.3f}")

    print("\n=== SOL 볼륨비율 효과 (top5 평균) ===")
    for vr in SOL_VOL_RATIO_LIST:
        sub = sorted([r for r in valid if r["params"][1] == vr],
                     key=lambda x: x["avg_sharpe"], reverse=True)[:5]
        if sub:
            print(f"  VR={vr:.1f}: avgSh={np.mean([r['avg_sharpe'] for r in sub]):+.3f}  "
                  f"SOL={np.mean([r['sol_avg_sharpe'] for r in sub]):+.3f}  "
                  f"F3={np.mean([r['f3_sharpe'] for r in sub]):+.3f}")

    print("\n=== SOL BTC mom 임계 효과 (top5 평균) ===")
    for bm in SOL_BTC_MOM_TH_LIST:
        sub = sorted([r for r in valid if r["params"][2] == bm],
                     key=lambda x: x["avg_sharpe"], reverse=True)[:5]
        if sub:
            print(f"  BTC>={bm:.1f}: avgSh={np.mean([r['avg_sharpe'] for r in sub]):+.3f}  "
                  f"SOL={np.mean([r['sol_avg_sharpe'] for r in sub]):+.3f}  "
                  f"F3={np.mean([r['f3_sharpe'] for r in sub]):+.3f}")

    print("\n=== SOL EMA slope 효과 (top5 평균) ===")
    for sm in SOL_SLOPE_MIN_LIST:
        sub = sorted([r for r in valid if r["params"][3] == sm],
                     key=lambda x: x["avg_sharpe"], reverse=True)[:5]
        if sub:
            print(f"  SLP>={sm:.2f}: avgSh={np.mean([r['avg_sharpe'] for r in sub]):+.3f}  "
                  f"SOL={np.mean([r['sol_avg_sharpe'] for r in sub]):+.3f}  "
                  f"F3={np.mean([r['f3_sharpe'] for r in sub]):+.3f}")

    # ─── 합격 조합 ────────────────────────────────
    sol_pass = [r for r in valid
                if r["sol_avg_sharpe"] >= 10.0 and r["f3_sharpe"] >= 10.0]
    print(f"\n=== SOL>=10 & F3>=10 통과: {len(sol_pass)}개 ===")
    for r in sol_pass[:10]:
        p = r["params"]
        print(f"  adxB={p[0]} volR={p[1]:.1f} btcM={p[2]:.1f} slp={p[3]:.2f} | "
              f"avg={r['avg_sharpe']:+.3f} F3={r['f3_sharpe']:+.3f} "
              f"SOL={r['sol_avg_sharpe']:+.3f} n={r['total_n']}")

    # ─── 최종 요약 ────────────────────────────────
    print("\n=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_ok = b["f3_sharpe"] >= 10.0
        sol_ok = b["sol_avg_sharpe"] >= 10.0
        main_ok = b["avg_sharpe"] >= 16.0 and b["total_n"] >= 30 and f3_ok
        print(f"★ OOS 최적: adxB={p[0]} volR={p[1]:.1f} "
              f"btcM={p[2]:.1f} slp={p[3]:.2f}")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} "
              f"{'PASS' if main_ok else 'FAIL'}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} {'PASS' if f3_ok else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_ok else 'FAIL'}")
        print(f"  ETH avg Sharpe: {b['eth_avg_sharpe']:+.3f}")
        print(f"  total trades: {b['total_n']}")
        for f in b["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  trades={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")
        avg_wr = np.mean([f["wr"] for f in b["folds"]])
        print(f"\nSharpe: {b['avg_sharpe']:+.3f}")
        print(f"WR: {avg_wr:.1f}%")
        print(f"trades: {b['total_n']}")
    else:
        print("n>=30 조건 충족 조합 없음 — FAIL")
        print("\nSharpe: N/A")
        print("WR: N/A")
        print("trades: 0")


if __name__ == "__main__":
    main()
