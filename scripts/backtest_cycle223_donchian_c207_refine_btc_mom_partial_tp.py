"""사이클 223: c207 winner 리파인 + BTC 모멘텀 게이트 + 부분 익절

- 기반: c207 winner aPth=30 aPLB=30 vRat=1.0 vSMA=20 rsiC=100 tpVS=0.5
  avg OOS Sharpe=+15.41, F3=+6.67, trades=88
- 문제: SOL F3 Sharpe=-3.45 (횡보/약세), XRP F3=-1.37 — F3 심볼 편차
- 가설:
  A) winner 근방 정밀 그리드 — 진짜 최적점인지, 과적합인지 검증
  B) BTC 10봉 수익률 게이트 — BTC 약세 구간 진입 차단 (SOL F3 타겟)
  C) 부분 익절(PTP) — ATR * PTP_MULT 도달 시 50% 청산,
     나머지는 기존 TP/SL/trail → 변동성 축소 구간에서 수익 보존
- 탐색 그리드:
  ATR_PCTILE_TH: [20, 25, 30, 35, 40]        (winner 30 ±)
  VOL_RATIO_MIN: [0.8, 1.0, 1.2]             (winner 1.0 ±)
  TP_VOL_SCALE:  [0.3, 0.5, 0.7]             (winner 0.5 ±)
  BTC_MOM_LB:    [0, 10, 20]                 (0=비활성)
  BTC_MOM_MIN:   [0.0, 0.0, 0.02]            (LB와 pair)
  PTP_MULT:      [0.0, 1.5, 2.0]             (0.0=비활성)
  = 5*3*3*3*3 = 405 조합 (pair 중복 제거 후 ~270)
- c207 고정: aPLB=30 vSMA=20 rsiC=100
- 목표: avg OOS Sharpe >= 15 AND F3 >= 8 AND trades >= 60
- 출력: Sharpe / WR / trades 포함
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_cycle207_donchian_vol_regime_filter import (  # type: ignore
    ADX_THRESH,
    ATR_SL_MULT,
    ATR_TP_MULT,
    BTC_SMA_PERIOD,
    DC_LOWER_LB,
    DC_UPPER_LB,
    FEE,
    MAX_HOLD,
    SLIPPAGE,
    SYMBOLS,
    TRAIL_MULT,
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

# ─── c207 winner 고정 ─────────────────────────────────────────────
ATR_PCTILE_LB = 30
VOL_SMA_PERIOD = 20
RSI_CEILING = 100

# ─── c223 그리드 ───────────────────────────────────────────────────
ATR_PCTILE_TH_LIST = [20, 25, 30, 35, 40]
VOL_RATIO_MIN_LIST = [0.8, 1.0, 1.2]
TP_VOL_SCALE_LIST = [0.3, 0.5, 0.7]
BTC_MOM_PAIRS = [(0, 0.0), (10, 0.0), (10, 0.02), (20, 0.0), (20, 0.02)]
PTP_MULT_LIST = [0.0, 1.5, 2.0]


def btc_momentum(btc_close: np.ndarray, lookback: int) -> np.ndarray:
    n = len(btc_close)
    out = np.full(n, np.nan)
    if lookback <= 0:
        out[:] = 1.0
        return out
    for i in range(lookback, n):
        prev = btc_close[i - lookback]
        if prev > 0:
            out[i] = btc_close[i] / prev - 1.0
    return out


def run_backtest(
    c: np.ndarray, o: np.ndarray, h: np.ndarray, lo: np.ndarray, v: np.ndarray,
    dc_up: np.ndarray, dc_lo: np.ndarray,
    atr_val: np.ndarray, adx_val: np.ndarray,
    btc_close: np.ndarray, btc_sma: np.ndarray, btc_mom: np.ndarray,
    atr_pctile: np.ndarray, vol_sma: np.ndarray, rsi_arr: np.ndarray,
    atr_pctile_th: float, vol_ratio_min: float, rsi_ceiling: float,
    tp_vol_scale: float, btc_mom_min: float, ptp_mult: float,
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
            current = c[i]

            # 부분 익절 체크 (한 번만)
            if (ptp_mult > 0 and not position["ptp_done"]
                    and current >= position["ptp_price"]):
                partial_exit = o_next * (1 - SLIPPAGE)
                partial_ret = (partial_exit / position["entry_price"]) - 1 - FEE * 2
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": partial_ret * 0.5,
                        "reason": "PTP",
                        "bars": bars_held,
                    })
                position["ptp_done"] = True

            exit_reason = None
            if current <= position["sl_price"]:
                exit_reason = "SL"
            if current >= position["tp_price"]:
                exit_reason = "TP"
            if (not np.isnan(dc_lo[i]) and current <= dc_lo[i]):
                exit_reason = "DC_LOW"
            if bars_held >= MAX_HOLD:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                remain_w = 0.5 if position["ptp_done"] else 1.0
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": ret * remain_w,
                        "reason": exit_reason,
                        "bars": bars_held,
                    })
                position = None
        else:
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue

            if not (c[i] > dc_up[i]):
                continue
            if adx_val[i] < ADX_THRESH:
                continue
            if btc_close[i] <= btc_sma[i]:
                continue

            if atr_pctile_th > 0:
                if np.isnan(atr_pctile[i]) or atr_pctile[i] < atr_pctile_th:
                    continue

            if vol_ratio_min > 0:
                if (np.isnan(vol_sma[i]) or vol_sma[i] <= 0
                        or v[i] / vol_sma[i] < vol_ratio_min):
                    continue

            if rsi_ceiling < 100:
                if np.isnan(rsi_arr[i]) or rsi_arr[i] >= rsi_ceiling:
                    continue

            if btc_mom_min > 0:
                if np.isnan(btc_mom[i]) or btc_mom[i] < btc_mom_min:
                    continue

            entry_price = o_next * (1 + SLIPPAGE)
            atr_now = atr_val[i]
            vol_tp_bonus = 0.0
            if tp_vol_scale > 0 and not np.isnan(atr_pctile[i]):
                vol_score = max(0.0, atr_pctile[i] - 50.0) / 50.0
                vol_tp_bonus = tp_vol_scale * vol_score
            tp_pct = atr_now / c[i] * (ATR_TP_MULT + vol_tp_bonus)
            sl_pct = atr_now / c[i] * ATR_SL_MULT
            ptp_pct = atr_now / c[i] * ptp_mult if ptp_mult > 0 else 0.0

            position = {
                "entry_price": entry_price,
                "entry_bar": i + 1,
                "tp_price": entry_price * (1 + tp_pct),
                "sl_price": entry_price * (1 - sl_pct),
                "ptp_price": entry_price * (1 + ptp_pct) if ptp_pct > 0 else 0,
                "ptp_done": ptp_mult <= 0,
            }

    return trades


def main() -> None:
    print("=" * 80)
    print("=== c223: c207 winner refine + BTC momentum + Partial TP ===")
    print(f"고정: aPLB={ATR_PCTILE_LB} vSMA={VOL_SMA_PERIOD} "
          f"rsiC={RSI_CEILING}  (c205: dcU={DC_UPPER_LB} dcL={DC_LOWER_LB} "
          f"adx={ADX_THRESH} atrTP={ATR_TP_MULT} atrSL={ATR_SL_MULT} "
          f"trail={TRAIL_MULT})")
    print("=" * 80)

    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"BTC: {len(btc_df)} rows")

    sym_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        sym_data[sym] = load_historical(
            sym, "240m", "2022-01-01", "2026-04-05")
        print(f"{sym}: {len(sym_data[sym])} rows")

    btc_close_full = btc_df["close"].values
    btc_sma_full = sma_calc(btc_close_full, BTC_SMA_PERIOD)
    btc_mom_cache: dict[int, np.ndarray] = {}
    for lb in {p[0] for p in BTC_MOM_PAIRS}:
        btc_mom_cache[lb] = btc_momentum(btc_close_full, lb)

    sym_precomp: dict[str, dict] = {}
    for sym in SYMBOLS:
        df = sym_data[sym]
        h_arr = df["high"].values
        lo_arr = df["low"].values
        c_arr = df["close"].values
        o_arr = df["open"].values
        v_arr = df["volume"].values

        dc_up = donchian_upper(h_arr, DC_UPPER_LB)
        dc_lo = donchian_lower(lo_arr, DC_LOWER_LB)
        atr_arr = compute_atr(h_arr, lo_arr, c_arr, 14)
        adx_arr = compute_adx(h_arr, lo_arr, c_arr, 14)
        rsi_arr = rsi_calc(c_arr, 14)
        vol_sma = sma_calc(v_arr, VOL_SMA_PERIOD)
        atr_pctile = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)

        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values

        btc_mom_aligned: dict[int, np.ndarray] = {}
        for lb, arr in btc_mom_cache.items():
            s = pd.Series(arr, index=btc_df.index)
            btc_mom_aligned[lb] = s.reindex(df.index, method="ffill").values

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr,
            "vol_sma": vol_sma, "atr_pctile": atr_pctile,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "btc_mom": btc_mom_aligned,
            "index": df.index,
        }

    grid = list(product(
        ATR_PCTILE_TH_LIST, VOL_RATIO_MIN_LIST, TP_VOL_SCALE_LIST,
        BTC_MOM_PAIRS, PTP_MULT_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    all_results: list[dict] = []

    for gi, (atr_p_th, vol_r_min, tp_vs, (btc_lb, btc_min), ptp_m) in enumerate(grid):
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
                    sp["btc_c"], sp["btc_s"], sp["btc_mom"][btc_lb],
                    sp["atr_pctile"], sp["vol_sma"], sp["rsi"],
                    atr_p_th, vol_r_min, RSI_CEILING,
                    tp_vs, btc_min, ptp_m,
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
                equity = np.cumprod([1 + r for r in fold_rets])
                peak_eq = np.maximum.accumulate(equity)
                mdd = float(np.min(equity / peak_eq - 1) * 100)
            else:
                sharpe, wr, avg, mdd = -999, 0, 0, 0

            fold_sharpes.append(sharpe)
            fold_details.append({
                "name": window["name"], "sharpe": sharpe, "wr": wr,
                "n": len(fold_rets), "avg": avg * 100, "mdd": mdd,
            })
            total_n += len(fold_rets)

        avg_sharpe = float(np.mean(fold_sharpes)) if fold_sharpes else -999
        all_results.append({
            "params": (atr_p_th, vol_r_min, tp_vs, btc_lb, btc_min, ptp_m),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
        })

        if (gi + 1) % 30 == 0:
            print(f"  진행: {gi + 1}/{len(grid)}")

    print(f"  진행: {len(grid)}/{len(grid)}")

    valid = [r for r in all_results if r["total_n"] >= 60]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=60): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 ===")
    print("=" * 80)
    hdr = (f"{'aPth':>5} {'vRat':>5} {'tpVS':>5} {'bLB':>4} {'bMin':>6} "
           f"{'ptp':>5} | {'avgSh':>7} {'F3Sh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>5} {p[1]:>5.1f} {p[2]:>5.1f} {p[3]:>4} "
              f"{p[4]:>6.3f} {p[5]:>5.1f} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['total_n']:>5}")

    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n--- Best 상세 ---")
        for f in best["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")
        # c207 대비
        print("\n--- c207 winner 대비 ---")
        print("  c207: avg=+15.410 F3=+6.665 trades=88")
        print(f"  c223: avg={best['avg_sharpe']:+.3f} "
              f"F3={best['f3_sharpe']:+.3f} trades={best['total_n']}")

        total_rets = []
        total_wins = 0
        for f in best["folds"]:
            if f["n"] > 0:
                total_wins += int(f["wr"] / 100.0 * f["n"] + 0.5)
        wr_total = (total_wins / best["total_n"] * 100
                    if best["total_n"] else 0.0)

        print("\n" + "=" * 80)
        print("=== 최종 요약 ===")
        print(f"★ aPth={bp[0]} vRat={bp[1]:.1f} tpVS={bp[2]:.1f} "
              f"btcLB={bp[3]} btcMin={bp[4]:.3f} ptp={bp[5]:.1f}")
        print(f"Sharpe: {best['avg_sharpe']:+.3f}")
        print(f"WR: {wr_total:.1f}%")
        print(f"trades: {best['total_n']}")
    else:
        print("\n유효 조합 없음")
        print("Sharpe: -999.000")
        print("WR: 0.0%")
        print("trades: 0")


if __name__ == "__main__":
    main()
