"""사이클 229: c228 진입 문턱 완화 + Partial TP 도입

- 기반: c228 best trlM=2.0 rsiC=100 aLB=60 aTh=20 btcMin=0.025
  avg Sharpe=+17.383, F3=+9.203 (n=8), trades=61, WR=62.3%
- 문제:
  1) trades=61, F3 n=8 → 표본 부족으로 신뢰도 약함
  2) aTh=20, btcMin=0.025 모두 최저값 승리 → 더 낮은 범위 미탐색
  3) ADX=25 고정(c207) → 완화 시 진입 증가 가능
- 가설:
  A) ATR pctile TH 하향: 10/15/20 → 변동성 문턱 낮춰 더 많은 진입
  B) BTC mom min 하향: 0.01/0.015/0.025 → BTC 게이트 완화
  C) ADX 문턱 완화: 20/25/30 → 트렌드 강도 요구 조절
  D) Partial TP: TP 도달 시 포지션 일부(30/50%) 청산, 나머지 trailing
     → 이익 확보 + 추세 추종 양립
- 탐색 그리드:
  ATR_PCTILE_TH: [10, 15, 20]      (c228 best=20, 하향 탐색)
  BTC_MOM_MIN:   [0.01, 0.015, 0.025]  (c228 best=0.025, 하향 탐색)
  ADX_THRESH_V:  [20, 25, 30]       (c207 고정=25)
  PARTIAL_TP:    [0.0, 0.3, 0.5]    (0.0=기존 전량 TP)
  = 3*3*3*3 = 81 조합
- 고정(c228 best): trlM=2.0, rsiC=100, aLB=60, btcLB=15,
  vRat=1.0, tpVS=0.6, vSMA=20
- 목표: trades >= 80 AND F3_n >= 12 AND avg Sharpe >= 10
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_cycle207_donchian_vol_regime_filter import (  # type: ignore
    ATR_SL_MULT,
    ATR_TP_MULT,
    BTC_SMA_PERIOD,
    DC_LOWER_LB,
    DC_UPPER_LB,
    FEE,
    MAX_HOLD,
    SLIPPAGE,
    SYMBOLS,
    WINDOWS,
    compute_adx,
    compute_atr,
    compute_atr_percentile,
    donchian_lower,
    donchian_upper,
    sma_calc,
)
from backtest_cycle223_donchian_c207_refine_btc_mom_partial_tp import (  # type: ignore
    btc_momentum,
)
from historical_loader import load_historical

# ─── 고정 (c228 best) ───────────────────────────────────────────
TRAIL_MULT = 2.0
RSI_CEILING = 100  # 비활성 (c228 검증)
ATR_PCTILE_LB = 60
BTC_MOM_LB = 15
VOL_RATIO_MIN = 1.0
TP_VOL_SCALE = 0.6
VOL_SMA_PERIOD = 20

# ─── c229 그리드 ───────────────────────────────────────────────────
ATR_PCTILE_TH_LIST = [10, 15, 20]
BTC_MOM_MIN_LIST = [0.01, 0.015, 0.025]
ADX_THRESH_LIST = [20, 25, 30]
PARTIAL_TP_LIST = [0.0, 0.3, 0.5]


def run_backtest(
    c: np.ndarray, o: np.ndarray, h: np.ndarray, lo: np.ndarray, v: np.ndarray,
    dc_up: np.ndarray, dc_lo: np.ndarray,
    atr_val: np.ndarray, adx_val: np.ndarray,
    btc_close: np.ndarray, btc_sma: np.ndarray, btc_mom: np.ndarray,
    atr_pctile: np.ndarray, vol_sma: np.ndarray,
    atr_pctile_th: float, btc_mom_min: float,
    adx_thresh: float, partial_tp: float,
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

            # trailing stop update
            if current > position["peak"]:
                position["peak"] = current
                trail_stop = position["peak"] * (
                    1 - (atr_val[i] / position["peak"]) * TRAIL_MULT
                )
                if trail_stop > position["sl_price"]:
                    position["sl_price"] = trail_stop

            exit_reason = None
            if current <= position["sl_price"]:
                exit_reason = "SL"
            if current >= position["tp_price"] and not position["tp_hit"]:
                if partial_tp > 0:
                    # partial TP: 일부 청산, 나머지 trailing 유지
                    exit_actual = o_next * (1 - SLIPPAGE)
                    partial_ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                    entry_time = index[position["entry_bar"]]
                    if oos_start_ts <= entry_time <= oos_end_ts:
                        trades.append({
                            "entry_time": entry_time,
                            "return": partial_ret * partial_tp,
                            "reason": "PARTIAL_TP",
                            "bars": bars_held,
                        })
                    position["tp_hit"] = True
                    # 나머지 포지션은 trailing으로 계속
                    position["remaining"] = 1.0 - partial_tp
                else:
                    exit_reason = "TP"
            if not np.isnan(dc_lo[i]) and current <= dc_lo[i]:
                exit_reason = "DC_LOW"
            if bars_held >= MAX_HOLD:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                remaining = position.get("remaining", 1.0)
                entry_time = index[position["entry_bar"]]
                if oos_start_ts <= entry_time <= oos_end_ts:
                    trades.append({
                        "entry_time": entry_time,
                        "return": ret * remaining,
                        "reason": exit_reason,
                        "bars": bars_held,
                    })
                position = None
        else:
            if (np.isnan(dc_up[i]) or np.isnan(adx_val[i])
                    or np.isnan(atr_val[i]) or atr_val[i] <= 0
                    or np.isnan(btc_close[i]) or np.isnan(btc_sma[i])):
                continue
            # Donchian breakout
            if not (c[i] > dc_up[i]):
                continue
            # ADX floor (variable)
            if adx_val[i] < adx_thresh:
                continue
            # BTC trend gate
            if btc_close[i] <= btc_sma[i]:
                continue
            # ATR percentile (volatility regime)
            if np.isnan(atr_pctile[i]) or atr_pctile[i] < atr_pctile_th:
                continue
            # Volume confirmation
            if (np.isnan(vol_sma[i]) or vol_sma[i] <= 0
                    or v[i] / vol_sma[i] < VOL_RATIO_MIN):
                continue
            # BTC momentum gate
            if np.isnan(btc_mom[i]) or btc_mom[i] < btc_mom_min:
                continue

            entry_price = o_next * (1 + SLIPPAGE)
            atr_now = atr_val[i]
            vol_tp_bonus = 0.0
            if not np.isnan(atr_pctile[i]):
                vol_score = max(0.0, atr_pctile[i] - 50.0) / 50.0
                vol_tp_bonus = TP_VOL_SCALE * vol_score
            tp_pct = atr_now / c[i] * (ATR_TP_MULT + vol_tp_bonus)
            sl_pct = atr_now / c[i] * ATR_SL_MULT

            position = {
                "entry_price": entry_price,
                "entry_bar": i + 1,
                "tp_price": entry_price * (1 + tp_pct),
                "sl_price": entry_price * (1 - sl_pct),
                "peak": entry_price,
                "tp_hit": False,
                "remaining": 1.0,
            }

    return trades


def main() -> None:
    print("=" * 80)
    print("=== c229: 진입 문턱 완화 + Partial TP ===")
    print(f"고정: trlM={TRAIL_MULT} rsiC={RSI_CEILING} aLB={ATR_PCTILE_LB} "
          f"btcLB={BTC_MOM_LB} vRat={VOL_RATIO_MIN} tpVS={TP_VOL_SCALE} "
          f"vSMA={VOL_SMA_PERIOD}")
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
    btc_mom_arr = btc_momentum(btc_close_full, BTC_MOM_LB)

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
        vol_sma = sma_calc(v_arr, VOL_SMA_PERIOD)
        atr_pctile = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)

        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_m_s = pd.Series(btc_mom_arr, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values
        btc_m_aligned = btc_m_s.reindex(df.index, method="ffill").values

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo,
            "atr": atr_arr, "adx": adx_arr,
            "vol_sma": vol_sma, "atr_pctile": atr_pctile,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "btc_m": btc_m_aligned,
            "index": df.index,
        }

    grid = list(product(
        ATR_PCTILE_TH_LIST, BTC_MOM_MIN_LIST,
        ADX_THRESH_LIST, PARTIAL_TP_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    all_results: list[dict] = []

    for gi, (atr_th, btc_min, adx_th, ptp) in enumerate(grid):
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
                    sp["btc_c"], sp["btc_s"], sp["btc_m"],
                    sp["atr_pctile"], sp["vol_sma"],
                    atr_th, btc_min, adx_th, ptp,
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
            "params": (atr_th, btc_min, adx_th, ptp),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "f3_n": fold_details[2]["n"] if len(fold_details) > 2 else 0,
        })

        if (gi + 1) % 20 == 0 or (gi + 1) == len(grid):
            print(f"  진행: {gi + 1}/{len(grid)}")

    valid = [r for r in all_results if r["total_n"] >= 50]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=50): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 ===")
    print("=" * 80)
    hdr = (f"{'aTh':>4} {'bMin':>6} {'adx':>4} {'pTP':>4} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'F3n':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>4} {p[1]:>6.3f} {p[2]:>4} {p[3]:>4.1f} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['f3_n']:>4} {r['total_n']:>5}")

    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n--- Best 상세 ---")
        for f in best["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")
        print("\n--- c228 best 대비 ---")
        print("  c228: avg=+17.383 F3=+9.203 trades=61 WR=62.3")
        print(f"  c229: avg={best['avg_sharpe']:+.3f} "
              f"F3={best['f3_sharpe']:+.3f} trades={best['total_n']}")

        total_wins = 0
        for f in best["folds"]:
            if f["n"] > 0:
                total_wins += int(f["wr"] / 100.0 * f["n"] + 0.5)
        wr_total = (total_wins / best["total_n"] * 100
                    if best["total_n"] else 0.0)

        print("\n" + "=" * 80)
        print("=== 최종 요약 ===")
        print(f"★ aTh={bp[0]} btcMin={bp[1]:.3f} adx={bp[2]} pTP={bp[3]:.1f}")
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
