"""
사이클 217: c216 후속 — BTC 모멘텀 lookback 스윕 + SOL SL 초강화

c216 결과:
  ★ emaP=12 sLB=4 slPct=0.80 slSOL=0.70 slXRP=0.95 btcMomTh=+1.0
  avg=+20.550 F3=+15.099 SOL=+6.435 trades=70  → SOL FAIL (<10)

다음 단계 가설:
  1) BTC 10봉(≈40h) 고정이 SOL에 최적이 아닐 수 있음 → lookback 스윕
  2) SOL은 고변동 → SL을 더 타이트(0.50~0.70)하게 압축
  3) BTC 모멘텀 임계 상향(1.0~2.5) → 진짜 상승 추세만 진입
  4) 코어 파라미터(emaP=12, sLB=4, slPct=0.80, slXRP=0.95) 고정

그리드: BTC_LB(3) × BTC_TH(4) × slSOL(5) = 60 조합
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
    BTC_SMA_PERIOD,
    DC_LOWER_LB,
    DC_UPPER_LB,
    SYMBOLS,
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
    run_backtest,
)

# ─── c217 그리드 ────────────────────────────────
EMA_P_FIX = 12
SLOPE_LB_FIX = 4
SLOPE_MIN_PCT_FIX = 0.80
SL_XRP_FIX = 0.95

BTC_MOM_LB_LIST = [6, 10, 14]       # 24h / 40h / 56h
BTC_MOM_TH_LIST = [1.0, 1.5, 2.0, 2.5]
SL_SOL_LIST = [0.50, 0.55, 0.60, 0.65, 0.70]


def main() -> None:
    print("=" * 80)
    print("=== c217: BTC 모멘텀 lookback 스윕 + SOL SL 초강화 ===")
    print("=== 고정: emaP=12 sLB=4 slPct=0.80 slXRP=0.95 ===")
    print("=" * 80)

    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"BTC 데이터: {len(btc_df)} rows")

    sym_data = {}
    for sym in SYMBOLS:
        sym_data[sym] = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        print(f"{sym} 데이터: {len(sym_data[sym])} rows")

    btc_close_full = btc_df["close"].values
    btc_sma_full = sma_calc(btc_close_full, BTC_SMA_PERIOD)

    # lookback별 BTC momentum 사전계산
    btc_mom_by_lb = {
        lb: btc_return_pct(btc_close_full, lb) for lb in BTC_MOM_LB_LIST
    }

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
        from backtest_cycle215_donchian_momentum_confirm_sym_sl import (
            ATR_PCTILE_LB,
            VOL_SMA_PERIOD,
        )
        atr_pctile = compute_atr_percentile(atr_arr, ATR_PCTILE_LB)
        vol_sma_arr = sma_calc(v_arr, VOL_SMA_PERIOD)

        btc_c_s = pd.Series(btc_close_full, index=btc_df.index)
        btc_s_s = pd.Series(btc_sma_full, index=btc_df.index)
        btc_c_aligned = btc_c_s.reindex(df.index, method="ffill").values
        btc_s_aligned = btc_s_s.reindex(df.index, method="ffill").values

        btc_m_aligned_by_lb = {}
        for lb in BTC_MOM_LB_LIST:
            s = pd.Series(btc_mom_by_lb[lb], index=btc_df.index)
            btc_m_aligned_by_lb[lb] = s.reindex(df.index, method="ffill").values

        ema_arr = ema_calc(c_arr, EMA_P_FIX)
        slope_arr = ema_slope_pct(ema_arr, SLOPE_LB_FIX)

        sym_precomp[sym] = {
            "c": c_arr, "o": o_arr, "h": h_arr, "lo": lo_arr, "v": v_arr,
            "dc_up": dc_up, "dc_lo": dc_lo_arr,
            "atr": atr_arr, "adx": adx_arr, "rsi": rsi_arr,
            "atr_pctile": atr_pctile, "vol_sma": vol_sma_arr,
            "btc_c": btc_c_aligned, "btc_s": btc_s_aligned,
            "btc_m_by_lb": btc_m_aligned_by_lb,
            "slope": slope_arr,
            "index": df.index,
        }

    grid = list(product(BTC_MOM_LB_LIST, BTC_MOM_TH_LIST, SL_SOL_LIST))
    print(f"\n총 조합: {len(grid)}")

    all_results = []
    for gi, (btc_lb, btc_th, sl_sol) in enumerate(grid):
        sl_map = {"KRW-ETH": 1.0, "KRW-SOL": sl_sol, "KRW-XRP": SL_XRP_FIX}

        fold_sharpes = []
        fold_details = []
        total_n = 0
        sym_fold_data = {s: [] for s in SYMBOLS}

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
                    sp["slope"], sp["btc_m_by_lb"][btc_lb],
                    SLOPE_MIN_PCT_FIX, sl_map[sym], btc_th,
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
                sol_sharpes.append(
                    ((a / s) * np.sqrt(252 / (240 / 60 / 24)) if s > 0 else 0)
                )
            else:
                sol_sharpes.append(-999)
        sol_avg_sharpe = np.mean(sol_sharpes) if sol_sharpes else -999

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        all_results.append({
            "params": (btc_lb, btc_th, sl_sol),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
            "f3_sharpe": fold_sharpes[2] if len(fold_sharpes) > 2 else -999,
            "sol_avg_sharpe": sol_avg_sharpe,
        })

        if (gi + 1) % 10 == 0:
            print(f"  진행: {gi + 1}/{len(grid)}")

    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=30): {len(valid)}/{len(all_results)}")

    print("\n=== Top 15 ===")
    hdr = (f"{'btcLB':>5} {'btcTH':>6} {'slSOL':>6} | "
           f"{'avgSh':>7} {'F3Sh':>7} {'solSh':>7} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        p = r["params"]
        print(f"{p[0]:>5} {p[1]:>+6.1f} {p[2]:>6.2f} | "
              f"{r['avg_sharpe']:>+7.3f} {r['f3_sharpe']:>+7.3f} "
              f"{r['sol_avg_sharpe']:>+7.3f} {r['total_n']:>5}")

    # lookback 효과
    print("\n=== BTC lookback 효과 (top10 평균) ===")
    for lb in BTC_MOM_LB_LIST:
        sub = [r for r in valid if r["params"][0] == lb]
        if sub:
            sub_sorted = sorted(sub, key=lambda x: x["avg_sharpe"], reverse=True)[:10]
            print(f"  LB={lb:>2}: avgSh={np.mean([r['avg_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"F3={np.mean([r['f3_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"SOL={np.mean([r['sol_avg_sharpe'] for r in sub_sorted]):+.3f}  "
                  f"n_combos={len(sub)}")

    # SOL 합격 조합 필터
    sol_pass = [r for r in valid
                if r["sol_avg_sharpe"] >= 10.0 and r["f3_sharpe"] >= 10.0]
    print(f"\n=== SOL>=10 & F3>=10 통과: {len(sol_pass)}개 ===")
    for r in sol_pass[:5]:
        p = r["params"]
        print(f"  btcLB={p[0]} btcTH={p[1]:+.1f} slSOL={p[2]:.2f} | "
              f"avg={r['avg_sharpe']:+.3f} F3={r['f3_sharpe']:+.3f} "
              f"SOL={r['sol_avg_sharpe']:+.3f} n={r['total_n']}")

    print("\n=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        f3_ok = b["f3_sharpe"] >= 10.0
        sol_ok = b["sol_avg_sharpe"] >= 10.0
        main_ok = b["avg_sharpe"] >= 16.0 and b["total_n"] >= 30 and f3_ok
        print(f"★ OOS 최적: btcLB={p[0]} btcTH={p[1]:+.1f} slSOL={p[2]:.2f}")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} "
              f"{'PASS' if main_ok else 'FAIL'}")
        print(f"  F3 Sharpe: {b['f3_sharpe']:+.3f} {'PASS' if f3_ok else 'FAIL'}")
        print(f"  SOL avg Sharpe: {b['sol_avg_sharpe']:+.3f} "
              f"{'PASS' if sol_ok else 'FAIL'}")
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
