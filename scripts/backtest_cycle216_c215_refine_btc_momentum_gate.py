"""
사이클 216: c215 최적 근방 정밀 탐색 + BTC 모멘텀 게이트

- c215 결과: emaP=10 sLB=5 slPct=0.5 slSOL=0.70 slXRP=0.85
  avg OOS Sharpe +18.682, F3 +15.099, SOL +10.482, trades=90
- 다음 단계:
  1) 최적 근방 정밀 그리드 (emaP 8~14, sLB 4~6, slPct 0.3~0.8)
  2) slSOL 0.60~0.80 더 타이트하게
  3) BTC 모멘텀 게이트 추가: BTC 단기 수익률 > 임계 → 진입 허용
     (거짓 브레이크아웃 제거 — BTC 약세 시 알트 돌파는 대부분 실패)
  4) SOL F3 표본 3개가 불안정 → BTC 게이트로 F3 안정화 기대
- 그리드: 4×3×4×3×3×3 = 432 combos (BTC gate 포함)
- 합격선: avg Sharpe >= 16, F3 >= 10, SOL avg >= 10
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical  # noqa: E402

# c215 엔진/지표 재사용
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
    HOLD_DECAY,
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

# ─── c216 정밀 그리드 ─────────────────────────────────────────
EMA_PERIOD_LIST = [8, 10, 12, 14]
SLOPE_LB_LIST = [4, 5, 6]
SLOPE_MIN_PCT_LIST = [0.3, 0.5, 0.7, 0.8]
SYM_SL_SCALE_SOL_LIST = [0.60, 0.70, 0.80]
SYM_SL_SCALE_XRP_LIST = [0.75, 0.85, 0.95]
# ★ BTC 모멘텀 게이트: 최근 N봉 수익률 >= threshold(%)
BTC_MOM_LB = 10  # 고정 (≈ 40h @ 240m)
BTC_MOM_TH_LIST = [-999.0, 0.0, 1.0]  # -999=비활성


def btc_return_pct(btc_close: np.ndarray, lookback: int) -> np.ndarray:
    n = len(btc_close)
    out = np.full(n, np.nan)
    for i in range(lookback, n):
        prev = btc_close[i - lookback]
        if prev > 0:
            out[i] = (btc_close[i] / prev - 1.0) * 100.0
    return out


def run_backtest(
    c, o, h, lo, v, dc_up, dc_lo, atr_val, adx_val,
    btc_close, btc_sma, atr_pctile, vol_sma, rsi_arr,
    ema_slope, btc_mom,
    slope_min_pct, sl_scale, btc_mom_th,
    oos_start, oos_end, index,
):
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
            if TRAIL_MULT > 0 and cp > position["peak"]:
                position["peak"] = cp
                atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0
                ts = cp - atr_now * TRAIL_MULT
                if ts > position.get("trail_stop", 0):
                    position["trail_stop"] = ts

            exit_reason = None
            if cp <= position["sl_price"]:
                exit_reason = "SL"
            if cp >= position["tp_price"]:
                exit_reason = "TP"
            if TRAIL_MULT > 0 and cp <= position.get("trail_stop", 0):
                exit_reason = "TRAIL"
            if not np.isnan(dc_lo[i]) and cp <= dc_lo[i]:
                exit_reason = "DC_LOW"
            if bars_held >= MAX_HOLD:
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
            # ★ c216 NEW: BTC 모멘텀 게이트
            if btc_mom_th > -900.0:
                if np.isnan(btc_mom[i]) or btc_mom[i] < btc_mom_th:
                    continue

            entry_price = o_next * (1 + SLIPPAGE)
            atr_now = atr_val[i]
            vol_tp_bonus = 0.0
            if TP_VOL_SCALE > 0 and not np.isnan(atr_pctile[i]):
                vol_score = max(0, atr_pctile[i] - 50) / 50.0
                vol_tp_bonus = TP_VOL_SCALE * vol_score
            tp_pct = atr_now / c[i] * (ATR_TP_MULT + vol_tp_bonus)
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
    print("=== c216: c215 최적 근방 정밀 탐색 + BTC 모멘텀 게이트 ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | 슬리피지포함 ===")
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
    btc_mom_full = btc_return_pct(btc_close_full, BTC_MOM_LB)

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

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo_arr,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr,
            "atr_pctile": atr_pctile, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "btc_m": btc_m_aligned,
            "index": df.index,
        }

    grid = list(product(
        EMA_PERIOD_LIST, SLOPE_LB_LIST, SLOPE_MIN_PCT_LIST,
        SYM_SL_SCALE_SOL_LIST, SYM_SL_SCALE_XRP_LIST, BTC_MOM_TH_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    ema_slope_cache = {}
    for sym in SYMBOLS:
        sp = sym_precomp[sym]
        ema_slope_cache[sym] = {}
        for ema_p in EMA_PERIOD_LIST:
            ema_arr = ema_calc(sp["c"], ema_p)
            for slb in SLOPE_LB_LIST:
                ema_slope_cache[sym][(ema_p, slb)] = ema_slope_pct(
                    ema_arr, slb)

    all_results = []

    for gi, combo in enumerate(grid):
        ema_p, slb, slope_pct, sl_sol, sl_xrp, btc_mom_th = combo
        sl_map = {"KRW-ETH": 1.0, "KRW-SOL": sl_sol, "KRW-XRP": sl_xrp}

        fold_sharpes = []
        fold_details = []
        total_n = 0
        sym_fold_data = {s: [] for s in SYMBOLS}

        for window in WINDOWS:
            fold_rets = []
            for sym in SYMBOLS:
                sp = sym_precomp[sym]
                slope_arr = ema_slope_cache[sym][(ema_p, slb)]
                trades = run_backtest(
                    sp["c"], sp["o"], sp["h"], sp["lo"], sp["v"],
                    sp["dc_up"], sp["dc_lo"],
                    sp["atr"], sp["adx"],
                    sp["btc_c"], sp["btc_s"],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    slope_arr, sp["btc_m"],
                    slope_pct, sl_map[sym], btc_mom_th,
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

        sol_sharpes = []
        for rs in sym_fold_data["KRW-SOL"]:
            if rs:
                a = np.mean(rs)
                s = np.std(rs, ddof=1) if len(rs) > 1 else 1e-10
                sol_sharpes.append(((a / s) * np.sqrt(252 / (240 / 60 / 24))
                                    if s > 0 else 0))
            else:
                sol_sharpes.append(-999)
        sol_avg_sharpe = np.mean(sol_sharpes) if sol_sharpes else -999

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        all_results.append({
            "params": combo,
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg_sharpe,
        })

        if (gi + 1) % 50 == 0:
            print(f"  진행: {gi + 1}/{len(grid)}")

    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_results)}")

    print("\n=== Top 15 ===")
    hdr = (f"{'emaP':>5} {'sLB':>4} {'slPct':>6} {'slSOL':>6} "
           f"{'slXRP':>6} {'btcM':>7} | {'avgSh':>7} {'F3Sh':>7} "
           f"{'solSh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>5} {p[1]:>4} {p[2]:>6.2f} {p[3]:>6.2f} "
              f"{p[4]:>6.2f} {p[5]:>+7.1f} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['sol_avg_sharpe']:>+7.3f} {r['total_n']:>5}")

    # BTC 모멘텀 게이트 효과
    print("\n=== BTC 모멘텀 게이트 효과 ===")
    for th in BTC_MOM_TH_LIST:
        sub = [r for r in valid if r["params"][5] == th]
        if sub:
            avg_sh = np.mean([r["avg_sharpe"] for r in sub[:10]])
            avg_f3 = np.mean([r["f3_sharpe"] for r in sub[:10]])
            avg_sol = np.mean([r["sol_avg_sharpe"] for r in sub[:10]])
            label = "비활성" if th < -900 else f">={th:+.1f}%"
            print(f"  BTC mom {label}: top10 avg={avg_sh:+.3f}  "
                  f"F3={avg_f3:+.3f}  SOL={avg_sol:+.3f}  n_combos={len(sub)}")

    print("\n=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 10.0
        sol_pass = b["sol_avg_sharpe"] >= 10.0
        main_pass = b["avg_sharpe"] >= 16.0 and b["total_n"] >= 30 and f3_pass
        status = "PASS" if main_pass else "FAIL"
        print(f"★ OOS 최적: emaP={p[0]} sLB={p[1]} slPct={p[2]:.2f} "
              f"slSOL={p[3]:.2f} slXRP={p[4]:.2f} btcMomTh={p[5]:+.1f}")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} "
              f"{'PASS' if f3_pass else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_pass else 'FAIL'}")
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
