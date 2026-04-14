"""
사이클 214: c213 최적 고정 + 구조적 파라미터 재탐색
- 베이스: c213 avg_OOS=+20.432 F3=+18.836 (n=70, WR 62.8%)
  고정: trail=2.0 tpM=3.25 slM=1.75 be=1.0 vRat=1.5 rsiC=100 beTr=2.0 tvs=0.0
        atrPLB=30
- 문제:
  1) DC_UPPER_LB=30, DC_LOWER_LB=10, ADX=29 — c205 이후 미탐색
  2) ATR 주기 14 고정 — 환경별 최적 상이할 수 있음
  3) F3 거래 8건 — 구조적 완화로 거래 수 증가 가능
  4) F1 MDD -13.78% — 모멘텀 확인으로 가짜 브레이크아웃 필터링
- 가설:
  A) DC_UPPER_LB: [20, 25, 30, 40] — 짧은 LB→빠른 진입, 긴 LB→강한 브레이크아웃
  B) ADX_THRESH: [25, 27, 29, 33] — 추세 강도 문턱 미세 조정
  C) MOMENTUM_LB: [0, 5, 10] — 0=비활성, N>0: close>close[N] 확인
     가짜 브레이크아웃 필터링 → MDD 개선 기대
  D) ATR_PERIOD: [10, 14, 20] — 변동성 측정 민감도
- 그리드: 4×4×3×3 = 144 combos
- 3-fold WF + 슬리피지 스트레스
- 목표: avg OOS Sharpe >= 20.432 OR (avg >= 19.0 AND F3 >= 18.0 AND n >= 65)
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

# ─── c213 최적 고정값 ────────────────────────────────────────
TRAIL_MULT = 2.0
TP_MULT = 3.25
SL_MULT = 1.75
BE_TRIGGER = 2.0
VOL_RATIO_MIN = 1.5
RSI_CEILING = 100
TP_VOL_SCALE = 0.0
ATR_PCTILE_TH = 30
ATR_PCTILE_LB = 30
MAX_HOLD = 30

# ─── c214 탐색 그리드 ────────────────────────────────────────
DC_UPPER_LB_LIST = [20, 25, 30, 40]
ADX_THRESH_LIST = [25, 27, 29, 33]
MOMENTUM_LB_LIST = [0, 5, 10]      # 0=비활성, N: close > close[N-bars-ago]
ATR_PERIOD_LIST = [10, 14, 20]

# 베이스라인 참조
C213_AVG_SHARPE = 20.432
C213_F3_SHARPE = 18.836


def run_backtest(
    c, o, h, lo, v, dc_lo, atr_val, adx_val,
    btc_close, btc_sma, atr_pctile, vol_sma, rsi_arr,
    dc_up_arr,
    momentum_lb: int,
    adx_thresh: float,
    oos_start: str, oos_end: str, index: pd.DatetimeIndex,
) -> list[dict]:
    n = len(c)
    trades: list[dict] = []
    position = None
    oos_start_ts = pd.Timestamp(oos_start)
    oos_end_ts = pd.Timestamp(oos_end)
    warmup_base = max(40, BTC_SMA_PERIOD, 60)
    warmup = warmup_base + max(momentum_lb, 10)

    for i in range(warmup, n - 1):
        o_next = o[i + 1]

        if position is not None:
            bars_held = i - position["entry_bar"]
            current_price = c[i]
            atr_now = atr_val[i] if not np.isnan(atr_val[i]) else 0.0

            if current_price > position["peak"]:
                position["peak"] = current_price

            # Trailing stop
            if TRAIL_MULT > 0 and atr_now > 0:
                trail_stop = position["peak"] - atr_now * TRAIL_MULT
                if trail_stop > position.get("trail_stop", 0.0):
                    position["trail_stop"] = trail_stop

            # Breakeven trigger
            if BE_TRIGGER > 0 and not position.get("be_armed", False):
                profit_atr = current_price - position["entry_price"]
                if (position["entry_atr"] > 0
                        and profit_atr >= BE_TRIGGER * position["entry_atr"]):
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
            adx_ok = adx_val[i] >= adx_thresh
            btc_ok = btc_close[i] > btc_sma[i]
            atr_pctile_ok = (not np.isnan(atr_pctile[i])
                             and atr_pctile[i] >= ATR_PCTILE_TH)

            vol_ok = True
            if VOL_RATIO_MIN > 0:
                if np.isnan(vol_sma[i]) or vol_sma[i] <= 0:
                    vol_ok = False
                else:
                    vol_ok = v[i] / vol_sma[i] >= VOL_RATIO_MIN

            # 모멘텀 확인: close > close[momentum_lb bars ago]
            mom_ok = True
            if momentum_lb > 0:
                ref_idx = i - momentum_lb
                if ref_idx >= 0 and not np.isnan(c[ref_idx]):
                    mom_ok = c[i] > c[ref_idx]
                else:
                    mom_ok = False

            if (donchian_ok and adx_ok and btc_ok and atr_pctile_ok
                    and vol_ok and mom_ok):
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val[i]

                tp_pct = atr_now / c[i] * TP_MULT
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
    print("=== c214: c213 best + DC/ADX/모멘텀/ATR주기 구조적 재탐색 ===")
    print(f"고정: trail={TRAIL_MULT} tpM={TP_MULT} slM={SL_MULT} "
          f"vRat={VOL_RATIO_MIN} beTr={BE_TRIGGER} tvs={TP_VOL_SCALE}")
    grid = list(product(
        DC_UPPER_LB_LIST, ADX_THRESH_LIST, MOMENTUM_LB_LIST, ATR_PERIOD_LIST))
    print(f"탐색: DC_UB×ADX×MOM_LB×ATR_P = "
          f"{len(DC_UPPER_LB_LIST)}×{len(ADX_THRESH_LIST)}"
          f"×{len(MOMENTUM_LB_LIST)}×{len(ATR_PERIOD_LIST)} = {len(grid)}")
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

    # 심볼별 기본 데이터 준비 (ATR/ADX는 period별로 재계산 필요)
    sym_base = {}
    for sym in SYMBOLS:
        df = sym_data[sym]
        h_arr = df["high"].values
        lo_arr = df["low"].values
        c_arr = df["close"].values
        o_arr = df["open"].values
        v_arr = df["volume"].values

        dc_lo_arr = donchian_lower(lo_arr, DC_LOWER_LB)
        rsi_arr = rsi_calc(c_arr, 14)
        vol_sma_arr = sma_calc(v_arr, VOL_SMA_PERIOD)

        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values

        sym_base[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_lo": dc_lo_arr, "rsi": rsi_arr, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "index": df.index,
        }

    # DC upper / ATR / ADX / atr_pctile 은 파라미터별로 재계산 → 캐시
    dc_up_cache: dict[tuple[str, int], np.ndarray] = {}
    atr_cache: dict[tuple[str, int], np.ndarray] = {}
    adx_cache: dict[tuple[str, int], np.ndarray] = {}
    atr_pctile_cache: dict[tuple[str, int], np.ndarray] = {}

    for sym in SYMBOLS:
        sb = sym_base[sym]
        for dc_ub in DC_UPPER_LB_LIST:
            dc_up_cache[(sym, dc_ub)] = donchian_upper(sb["h"], dc_ub)
        for atr_p in ATR_PERIOD_LIST:
            atr_arr = compute_atr(sb["h"], sb["lo"], sb["c"], atr_p)
            adx_arr = compute_adx(sb["h"], sb["lo"], sb["c"], atr_p)
            atr_pctile_arr = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
            atr_cache[(sym, atr_p)] = atr_arr
            adx_cache[(sym, atr_p)] = adx_arr
            atr_pctile_cache[(sym, atr_p)] = atr_pctile_arr

    print(f"\n총 조합: {len(grid)}")

    all_results = []
    for gi, (dc_ub, adx_th, mom_lb, atr_p) in enumerate(grid):
        fold_sharpes = []
        fold_details = []
        total_n = 0

        for window in WINDOWS:
            fold_rets = []
            for sym in SYMBOLS:
                sb = sym_base[sym]
                trades = run_backtest(
                    sb["c"], sb["o"], sb["h"], sb["lo"], sb["v"],
                    sb["dc_lo"],
                    atr_cache[(sym, atr_p)],
                    adx_cache[(sym, atr_p)],
                    sb["btc_c"], sb["btc_s"],
                    atr_pctile_cache[(sym, atr_p)],
                    sb["vol_sma"], sb["rsi"],
                    dc_up_cache[(sym, dc_ub)],
                    mom_lb, adx_th,
                    window["oos_start"], window["oos_end"], sb["index"],
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
            "params": (dc_ub, adx_th, mom_lb, atr_p),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999.0,
        })

        if (gi + 1) % 30 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")
    print(f"  진행: {len(grid)}/{len(grid)} 완료")

    valid = [r for r in all_results if r["total_n"] >= 50]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=50): {len(valid)}/{len(all_results)}")

    print("\n" + "=" * 80)
    print("=== Top 15 결과 ===")
    print("=" * 80)
    hdr = (f"{'dcUB':>5} {'adx':>5} {'momLB':>5} {'atrP':>5} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>5} {p[1]:>5} {p[2]:>5} {p[3]:>5} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['total_n']:>5}")

    print("\n--- Top 5 상세 ---")
    for i, r in enumerate(valid[:5]):
        p = r["params"]
        print(f"\n#{i+1}: dcUB={p[0]} adx={p[1]} momLB={p[2]} atrP={p[3]}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  "
              f"total_n={r['total_n']}")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  "
                  f"avg={f['avg']:+.2f}%  MDD={f['mdd']:+.2f}%")

    print("\n" + "=" * 80)
    print("=== c213 베이스라인 대비 비교 ===")
    if valid:
        b = valid[0]
        print(f"  c213 기준: avg_OOS={C213_AVG_SHARPE:+.3f} "
              f"F3={C213_F3_SHARPE:+.3f}")
        print(f"  c214 최적: avg_OOS={b['avg_sharpe']:+.3f} "
              f"F3={b['f3_sharpe']:+.3f}")
        d = b["avg_sharpe"] - C213_AVG_SHARPE
        df3 = b["f3_sharpe"] - C213_F3_SHARPE
        print(f"  Δ avg: {d:+.3f} ({'개선' if d > 0 else '악화'})")
        print(f"  Δ F3: {df3:+.3f} ({'개선' if df3 > 0 else '악화'})")

    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_pass = b["f3_sharpe"] >= 18.0
        status = ("PASS" if (b["avg_sharpe"] >= C213_AVG_SHARPE
                             or (b["avg_sharpe"] >= 19.0 and f3_pass
                                 and b["total_n"] >= 65))
                  else "MARGINAL" if b["avg_sharpe"] >= 19.0 else "FAIL")
        print(f"★ OOS 최적: dcUB={p[0]} adx={p[1]} "
              f"momLB={p[2]} atrP={p[3]}")
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
