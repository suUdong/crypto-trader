"""
사이클 218: c217 후속 — SOL 전용 EXIT 파라미터 튜닝

c217 결과:
  ★ btcLB=10 btcTH=+1.0 slSOL=0.50 (고정)
  avg=+21.249 F3=+16.682 SOL=+7.182 trades=71 → SOL FAIL (<10)

SOL 문제 분석:
  - SL 타이트(0.50)로 손절은 줄였으나 SOL Sharpe 여전히 <10
  - SOL은 변동성이 ETH/XRP보다 2~3배 → 동일 TP/Trail 배수 부적합
  - 가설: SOL은 빠른 스파이크 후 되돌림 패턴 → TP 배수 낮추거나 Trail 타이트하게

가설별 탐색:
  1) SOL TP 배수: 기본 3.0 ATR → 2.0~4.0 스윕 (빠른 익절 vs 추세 추종)
  2) SOL Trail 배수: 기본 2.5 ATR → 1.5~3.0 스윕 (타이트 vs 넓은 트레일)
  3) SOL 최대 보유봉수: 기본 30 → 15~30 스윕 (빠른 청산)
  4) ETH/XRP는 c217 최적 그대로 유지

고정:
  emaP=12 sLB=4 slPct=0.80 slXRP=0.95 slSOL=0.50
  btcLB=10 btcTH=+1.0
  dcU=30 dcL=10 adx=25 trail=2.5(ETH/XRP) tpM=3.0(ETH/XRP)

그리드: SOL_TP(5) × SOL_TRAIL(4) × SOL_MAXHOLD(4) = 80 combos
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
    ADX_THRESH,
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

# ─── c218 SOL EXIT 탐색 ────────────────────────────
SOL_TP_MULT_LIST = [2.0, 2.5, 3.0, 3.5, 4.0]
SOL_TRAIL_MULT_LIST = [1.5, 2.0, 2.5, 3.0]
SOL_MAX_HOLD_LIST = [15, 20, 25, 30]


def run_backtest_sym_exit(
    c, o, h, lo, v, dc_up, dc_lo, atr_val, adx_val,
    btc_close, btc_sma, atr_pctile, vol_sma, rsi_arr,
    ema_slope, btc_mom,
    slope_min_pct, sl_scale, btc_mom_th,
    tp_mult, trail_mult, max_hold,
    oos_start, oos_end, index,
):
    """run_backtest with per-symbol TP/trail/maxhold override."""
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
            if not (adx_val[i] >= ADX_THRESH):
                continue
            if not (btc_close[i] > btc_sma[i]):
                continue
            if ATR_PCTILE_TH > 0:
                if np.isnan(atr_pctile[i]) or atr_pctile[i] < ATR_PCTILE_TH:
                    continue
            if VOL_RATIO_MIN > 0:
                if (np.isnan(vol_sma[i]) or vol_sma[i] <= 0
                        or v[i] / vol_sma[i] < VOL_RATIO_MIN):
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


def main() -> None:
    print("=" * 80)
    print("=== c218: SOL 전용 EXIT 파라미터 튜닝 ===")
    print("=== 고정: emaP=12 sLB=4 slPct=0.80 slSOL=0.50 slXRP=0.95 ===")
    print("=== 고정: btcLB=10 btcTH=+1.0 ===")
    print("=== 탐색: SOL TP배수 / Trail배수 / MaxHold ===")
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

    # SOL exit 그리드 — ETH/XRP는 기본값 고정
    grid = list(product(SOL_TP_MULT_LIST, SOL_TRAIL_MULT_LIST, SOL_MAX_HOLD_LIST))
    print(f"\n총 조합: {len(grid)}")

    sl_map = {"KRW-ETH": 1.0, "KRW-SOL": SL_SOL_FIX, "KRW-XRP": SL_XRP_FIX}

    all_results = []
    for gi, (sol_tp, sol_trail, sol_mh) in enumerate(grid):
        fold_sharpes = []
        fold_details = []
        total_n = 0
        sym_fold_data = {s: [] for s in SYMBOLS}

        for window in WINDOWS:
            fold_rets = []
            for sym in SYMBOLS:
                sp = sym_precomp[sym]

                # SOL gets override exit params, others get defaults
                if sym == "KRW-SOL":
                    tp_m = sol_tp
                    tr_m = sol_trail
                    mh = sol_mh
                else:
                    tp_m = ATR_TP_MULT
                    tr_m = TRAIL_MULT
                    mh = MAX_HOLD

                trades = run_backtest_sym_exit(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    sp["slope"], sp["btc_m"],
                    SLOPE_MIN_PCT_FIX, sl_map[sym], BTC_MOM_TH_FIX,
                    tp_m, tr_m, mh,
                    window["oos_start"], window["oos_end"],
                    sp["index"],
                )
                rets = [t["return"] for t in trades]
                fold_rets.extend(rets)
                sym_fold_data[sym].append(rets)

            if fold_rets:
                avg = np.mean(fold_rets)
                std = (np.std(fold_rets, ddof=1)
                       if len(fold_rets) > 1 else 1e-10)
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

        # SOL per-fold Sharpe
        sol_sharpes = []
        for rs in sym_fold_data["KRW-SOL"]:
            if rs:
                a = np.mean(rs)
                s = np.std(rs, ddof=1) if len(rs) > 1 else 1e-10
                sol_sharpes.append(
                    ((a / s) * np.sqrt(252 / (240 / 60 / 24)) if s > 0 else 0)
                )
            else:
                sol_sharpes.append(-999)
        sol_avg_sharpe = np.mean(sol_sharpes) if sol_sharpes else -999

        # ETH per-fold Sharpe
        eth_sharpes = []
        for rs in sym_fold_data["KRW-ETH"]:
            if rs:
                a = np.mean(rs)
                s = np.std(rs, ddof=1) if len(rs) > 1 else 1e-10
                eth_sharpes.append(
                    ((a / s) * np.sqrt(252 / (240 / 60 / 24)) if s > 0 else 0)
                )
            else:
                eth_sharpes.append(-999)
        eth_avg_sharpe = np.mean(eth_sharpes) if eth_sharpes else -999

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        all_results.append({
            "params": (sol_tp, sol_trail, sol_mh),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg_sharpe,
            "eth_avg_sharpe": eth_avg_sharpe,
        })

        if (gi + 1) % 10 == 0:
            print(f"  진행: {gi + 1}/{len(grid)}")

    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_results)}")

    print("\n=== Top 15 ===")
    hdr = (f"{'solTP':>6} {'solTR':>6} {'solMH':>6} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'solSh':>7} {'ethSh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>6.1f} {p[1]:>6.1f} {p[2]:>6} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['sol_avg_sharpe']:>+7.3f} {r['eth_avg_sharpe']:>+7.3f} "
              f"{r['total_n']:>5}")

    # SOL TP 효과
    print("\n=== SOL TP 배수 효과 (top5 평균) ===")
    for tp in SOL_TP_MULT_LIST:
        sub = [r for r in valid if r["params"][0] == tp]
        if sub:
            sub_sorted = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            print(f"  TP={tp:.1f}: avgSh={np.mean([r['avg_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"SOL={np.mean([r['sol_avg_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"F3={np.mean([r['f3_sharpe'] for r in sub_sorted]):+.3f}")

    # SOL Trail 효과
    print("\n=== SOL Trail 배수 효과 (top5 평균) ===")
    for tr in SOL_TRAIL_MULT_LIST:
        sub = [r for r in valid if r["params"][1] == tr]
        if sub:
            sub_sorted = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            print(f"  TR={tr:.1f}: avgSh={np.mean([r['avg_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"SOL={np.mean([r['sol_avg_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"F3={np.mean([r['f3_sharpe'] for r in sub_sorted]):+.3f}")

    # SOL MaxHold 효과
    print("\n=== SOL MaxHold 효과 (top5 평균) ===")
    for mh in SOL_MAX_HOLD_LIST:
        sub = [r for r in valid if r["params"][2] == mh]
        if sub:
            sub_sorted = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:5]
            print(f"  MH={mh:>2}: avgSh={np.mean([r['avg_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"SOL={np.mean([r['sol_avg_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"F3={np.mean([r['f3_sharpe'] for r in sub_sorted]):+.3f}")

    # 합격 조합
    sol_pass = [r for r in valid
                if r["sol_avg_sharpe"] >= 10.0 and r["f3_sharpe"] >= 10.0]
    print(f"\n=== SOL>=10 & F3>=10 통과: {len(sol_pass)}개 ===")
    for r in sol_pass[:10]:
        p = r["params"]
        print(f"  solTP={p[0]:.1f} solTR={p[1]:.1f} solMH={p[2]} | "
              f"avg={r['avg_sharpe']:+.3f} F3={r['f3_sharpe']:+.3f} "
              f"SOL={r['sol_avg_sharpe']:+.3f} n={r['total_n']}")

    print("\n=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_ok = b["f3_sharpe"] >= 10.0
        sol_ok = b["sol_avg_sharpe"] >= 10.0
        main_ok = b["avg_sharpe"] >= 16.0 and b["total_n"] >= 30 and f3_ok
        print(f"★ OOS 최적: solTP={p[0]:.1f} solTR={p[1]:.1f} solMH={p[2]}")
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
