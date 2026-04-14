"""사이클 231: c230 best → trailing 하한 확장 + time-decay TP

- 기반: c230 best aTh=10 trlM=1.5 tpVS=0.6 pTP=0.6
  avg Sharpe=+20.898, F3=+26.156 (n=12), trades=93, WR=71.0%
- 문제:
  1) trailing mult 1.5가 그리드 하한 → 더 타이트한 trailing이 유효한지 미확인
  2) F1 MDD=-26.49% → 장기 보유 시 수익 반납, exit 타이밍 지연
  3) MAX_HOLD=30봉 고정 → 보유 시간 길어질수록 TP 낮춰서 수익 확보 가능
- 가설:
  A) trailing mult 하한 확장: [1.0, 1.2, 1.5] → 1.0~1.2에서 더 빠른 수익확보
  B) time-decay TP: N봉 이후 TP를 점진적으로 낮춤
     decay_start: [8, 12, 16] 봉 이후부터
     decay_rate: [0.03, 0.05, 0.08] 봉당 TP 감소율
     → 진입 후 시간 지나면 소폭 이익도 확보
  C) partial TP는 c230 best=0.6 고정
  = 3 × 3 × 3 = 27 조합
- 고정(c230 best): btcMin=0.010, adx=25, rsiC=100, aLB=60,
  btcLB=15, vRat=1.0, vSMA=20, aTh=10, tpVS=0.6, pTP=0.6
- 목표: avg Sharpe >= 20 AND F1 MDD > -20% AND trades >= 80
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

# --- 고정 (c230 best) ---
BTC_MOM_MIN = 0.010
ADX_THRESH = 25
RSI_CEILING = 100
ATR_PCTILE_LB = 60
BTC_MOM_LB = 15
VOL_RATIO_MIN = 1.0
VOL_SMA_PERIOD = 20
ATR_PCTILE_TH = 10
TP_VOL_SCALE = 0.6
PARTIAL_TP = 0.6

# --- c231 그리드 ---
TRAIL_MULT_LIST = [1.0, 1.2, 1.5]
DECAY_START_LIST = [8, 12, 16]    # 봉 수 이후 TP decay 시작
DECAY_RATE_LIST = [0.03, 0.05, 0.08]  # 봉당 TP 감소율


def run_backtest(
    c: np.ndarray, o: np.ndarray, h: np.ndarray, lo: np.ndarray, v: np.ndarray,
    dc_up: np.ndarray, dc_lo: np.ndarray,
    atr_val: np.ndarray, adx_val: np.ndarray,
    btc_close: np.ndarray, btc_sma: np.ndarray, btc_mom: np.ndarray,
    atr_pctile: np.ndarray, vol_sma: np.ndarray,
    trail_mult: float, decay_start: int, decay_rate: float,
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
                    1 - (atr_val[i] / position["peak"]) * trail_mult
                )
                if trail_stop > position["sl_price"]:
                    position["sl_price"] = trail_stop

            # time-decay TP: 일정 봉 수 이후 TP를 점진적으로 낮춤
            if bars_held >= decay_start:
                decay_bars = bars_held - decay_start
                decay_factor = max(0.3, 1.0 - decay_rate * decay_bars)
                current_tp = position["orig_tp_price"] * decay_factor
                # TP는 최소한 entry 가격 이상 유지
                if current_tp > position["entry_price"] * 1.002:
                    position["tp_price"] = current_tp

            exit_reason = None
            if current <= position["sl_price"]:
                exit_reason = "SL"
            if current >= position["tp_price"] and not position["tp_hit"]:
                if PARTIAL_TP > 0:
                    exit_actual = o_next * (1 - SLIPPAGE)
                    partial_ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                    entry_time = index[position["entry_bar"]]
                    if oos_start_ts <= entry_time <= oos_end_ts:
                        trades.append({
                            "entry_time": entry_time,
                            "return": partial_ret * PARTIAL_TP,
                            "reason": "PARTIAL_TP",
                            "bars": bars_held,
                        })
                    position["tp_hit"] = True
                    position["remaining"] = 1.0 - PARTIAL_TP
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
            # ADX floor
            if adx_val[i] < ADX_THRESH:
                continue
            # BTC trend gate
            if btc_close[i] <= btc_sma[i]:
                continue
            # ATR percentile (volatility regime)
            if np.isnan(atr_pctile[i]) or atr_pctile[i] < ATR_PCTILE_TH:
                continue
            # Volume confirmation
            if (np.isnan(vol_sma[i]) or vol_sma[i] <= 0
                    or v[i] / vol_sma[i] < VOL_RATIO_MIN):
                continue
            # BTC momentum gate
            if np.isnan(btc_mom[i]) or btc_mom[i] < BTC_MOM_MIN:
                continue

            entry_price = o_next * (1 + SLIPPAGE)
            atr_now = atr_val[i]
            vol_tp_bonus = 0.0
            if not np.isnan(atr_pctile[i]):
                vol_score = max(0.0, atr_pctile[i] - 50.0) / 50.0
                vol_tp_bonus = TP_VOL_SCALE * vol_score
            tp_pct = atr_now / c[i] * (ATR_TP_MULT + vol_tp_bonus)
            sl_pct = atr_now / c[i] * ATR_SL_MULT

            tp_price = entry_price * (1 + tp_pct)
            position = {
                "entry_price": entry_price,
                "entry_bar": i + 1,
                "tp_price": tp_price,
                "orig_tp_price": tp_price,
                "sl_price": entry_price * (1 - sl_pct),
                "peak": entry_price,
                "tp_hit": False,
                "remaining": 1.0,
            }

    return trades


def main() -> None:
    print("=" * 80)
    print("=== c231: c230 trail tighten + time-decay TP ===")
    print(f"고정: btcMin={BTC_MOM_MIN} adx={ADX_THRESH} aTh={ATR_PCTILE_TH} "
          f"tpVS={TP_VOL_SCALE} pTP={PARTIAL_TP}")
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

    grid = list(product(TRAIL_MULT_LIST, DECAY_START_LIST, DECAY_RATE_LIST))
    print(f"\n총 조합: {len(grid)}")

    all_results: list[dict] = []

    for gi, (trail_m, d_start, d_rate) in enumerate(grid):
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
                    trail_m, d_start, d_rate,
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
            "params": (trail_m, d_start, d_rate),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "f3_n": fold_details[2]["n"] if len(fold_details) > 2 else 0,
            "f1_mdd": fold_details[0]["mdd"] if fold_details else -999,
        })

        if (gi + 1) % 9 == 0 or (gi + 1) == len(grid):
            print(f"  진행: {gi + 1}/{len(grid)}")

    valid = [r for r in all_results if r["total_n"] >= 50]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=50): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 ===")
    print("=" * 80)
    hdr = (f"{'trlM':>5} {'dSt':>4} {'dRt':>5} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'F3n':>4} {'F1mdd':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>5.1f} {p[1]:>4} {p[2]:>5.2f} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['f3_n']:>4} {r['f1_mdd']:>+7.2f} {r['total_n']:>5}")

    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n--- Best 상세 ---")
        for f in best["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")
        print("\n--- c230 best 대비 ---")
        print("  c230: avg=+20.898 F3=+26.156 trades=93 WR=71.0 F1mdd=-26.49")
        print(f"  c231: avg={best['avg_sharpe']:+.3f} "
              f"F3={best['f3_sharpe']:+.3f} trades={best['total_n']} "
              f"F1mdd={best['f1_mdd']:+.2f}")

        total_wins = 0
        for f in best["folds"]:
            if f["n"] > 0:
                total_wins += int(f["wr"] / 100.0 * f["n"] + 0.5)
        wr_total = (total_wins / best["total_n"] * 100
                    if best["total_n"] else 0.0)

        print("\n" + "=" * 80)
        print("=== 최종 요약 ===")
        print(f"★ trlM={bp[0]:.1f} dSt={bp[1]} dRt={bp[2]:.2f}")
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
