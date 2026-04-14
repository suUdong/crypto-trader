"""
vpin_multi 사이클 206 — ATR-adaptive 출구 (TP/SL 배수)

배경:
- c205 최적: VPIN_HI=0.36 VPIN_LO=0.30 ATR_HI_TH=50 RSI_DELTA=7
  avg_OOS=+42.219, WR=68.1%, trades=17
- ATR-adaptive 진입은 저변동성 구간 VPIN 완화로 거래수 확보 성공
- 다음 문제: 출구(TP/SL)가 고정 ATR 배수 → 변동성에 무관하게 동일한 TP/SL
- trades=17은 여전히 적음 → 심볼 확장(DOGE, AVAX 추가)

가설:
- 저변동성 구간: TP 타이트 + SL 약간 넓혀 → 작은 움직임도 수익 확보
- 고변동성 구간: TP 넓히 + SL 유지 → 큰 움직임 극대화
- ATR pctile 기반 TP_MULT / SL_MULT 동적 조절
- 심볼 5개로 확장해 거래수 확보

탐색 그리드 (3×3×2 = 18 combos, c205 최적 진입 파라미터 고정):
  TP_HI_MULT: [1.0, 1.2, 1.4]  — 고변동 TP ATR 배수 스케일러
  TP_LO_MULT: [0.6, 0.7, 0.8]  — 저변동 TP ATR 배수 스케일러
  SL_SCALE:   [1.0, 1.2]       — 저변동 SL 완화 스케일러 (고변동=1.0 고정)

고정 (c205 최적):
  VPIN_HI=0.36, VPIN_LO=0.30, ATR_HI_TH=50, RSI_DELTA=7, MOM=0.0003
검증: 3-fold WF, slippage stress Top 3
목표: avg_OOS Sharpe > 42.219 OR trades >= 25 with Sharpe > 35
"""
from __future__ import annotations

import importlib.util
import sys
from itertools import product
from pathlib import Path

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from historical_loader import load_historical  # noqa: E402

_c199_path = THIS_DIR / "backtest_cycle199_vpin_multi_regime_dual_exit.py"
_spec = importlib.util.spec_from_file_location("c199_mod", _c199_path)
c199 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c199)  # type: ignore[union-attr]

# 심볼 확장: c205 3개 + DOGE, AVAX
SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE", "KRW-AVAX"]

# c205 최적 진입 파라미터 (고정)
FIXED_VPIN_HI = 0.36
FIXED_VPIN_LO = 0.30
FIXED_ATR_HI_TH = 50
FIXED_RSI_DELTA = 7
FIXED_MOM = 0.0003
ATR_OFFSET = 20

# regime 비활성
FIXED_REGIME_TH = 100
FIXED_HI_TP_BONUS = 0.0
FIXED_HI_TRAIL_RELAX = 1.0
FIXED_LO_SL_TIGHTEN = 0.0

# 탐색 그리드 — 출구 스케일러
TP_HI_MULT_LIST = [1.0, 1.2, 1.4]    # 고변동 TP 스케일러
TP_LO_MULT_LIST = [0.6, 0.7, 0.8]    # 저변동 TP 스케일러
SL_LO_SCALE_LIST = [1.0, 1.2]        # 저변동 SL 완화 스케일러

WF_FOLDS = c199.WF_FOLDS
SLIPPAGE_LEVELS = c199.SLIPPAGE_LEVELS
BTC_SMA_PERIOD = c199.BTC_SMA_PERIOD

C205_BASELINE_OOS = 42.219


def _adaptive_exit_backtest(
    df, tp_hi_mult, tp_lo_mult, sl_lo_scale,
    btc_c, btc_s, esp, vol_mom, atr_pctile,
    slippage=0.0005,
):
    """ATR-adaptive 진입(c205) + ATR-adaptive 출구(c206).

    진입: c205 로직 그대로 (VPIN_HI/LO + ATR pctile 기반 동적 VPIN)
    출구: ATR pctile 기반 TP/SL 배수 동적 조절
      고변동(ATR pctile >= hi_th): TP *= tp_hi_mult, SL 기본
      저변동(ATR pctile <= lo_th): TP *= tp_lo_mult, SL *= sl_lo_scale
      중간: 선형 보간
    """
    c_arr = df["close"].values
    o_arr = df["open"].values
    h_arr = df["high"].values
    lo_arr = df["low"].values
    v_arr = df["volume"].values
    n = len(c_arr)

    rsi_arr = c199.rsi_calc(c_arr, c199.RSI_PERIOD)
    ema_arr = c199.ema_calc(c_arr, c199.EMA_PERIOD)
    vpin_arr = c199.compute_vpin_bvc(
        c_arr, o_arr, h_arr, lo_arr, v_arr, c199.BUCKET_COUNT)
    mom_arr = c199.compute_momentum(c_arr, c199.MOM_LOOKBACK)
    atr_arr = c199.compute_atr(h_arr, lo_arr, c_arr, c199.ATR_PERIOD)
    vol_sma_arr = c199.sma_calc(v_arr, c199.VOL_SMA_PERIOD)
    body_ratio_arr = c199.compute_body_ratio(o_arr, c_arr, h_arr, lo_arr)
    vol_pctile_arr = c199.compute_vol_percentile(v_arr, c199.VOL_PCTILE_LB)

    atr_lo_th = FIXED_ATR_HI_TH - ATR_OFFSET

    returns: list[float] = []
    warmup = max(c199.BUCKET_COUNT, c199.EMA_PERIOD, c199.RSI_PERIOD + 1,
                 c199.MOM_LOOKBACK, c199.ATR_PERIOD, c199.VOL_SMA_PERIOD,
                 c199.ATR_PCTILE_LB, c199.VOL_PCTILE_LB,
                 c199.EMA_SLOPE_LB + 60, c199.VOL_MOM_LB + 10, 50) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    FEE = c199.FEE

    while i < n - 1:
        if c199.COOLDOWN_BARS > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_sma_val = vol_sma_arr[i]
        atr_pctile_val = atr_pctile[i]
        body_val = body_ratio_arr[i]
        vol_pctile_val = vol_pctile_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0):
            i += 1
            continue

        rsi_prev_idx = i - c199.RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # === c205 진입: ATR-adaptive VPIN threshold ===
        if np.isnan(atr_pctile_val):
            effective_vpin_low = FIXED_VPIN_HI
        elif atr_pctile_val >= FIXED_ATR_HI_TH:
            effective_vpin_low = FIXED_VPIN_HI
        elif atr_pctile_val <= atr_lo_th:
            effective_vpin_low = FIXED_VPIN_LO
        else:
            ratio = (atr_pctile_val - atr_lo_th) / ATR_OFFSET
            effective_vpin_low = FIXED_VPIN_LO + (FIXED_VPIN_HI - FIXED_VPIN_LO) * ratio

        # 진입 조건 (c205 동일)
        vpin_ok = (
            vpin_val < effective_vpin_low
            and mom_val >= FIXED_MOM
            and c199.RSI_FLOOR < rsi_val < c199.RSI_CEILING
            and c_arr[i] > ema_val
        )
        btc_ok = (
            not np.isnan(btc_c[i])
            and not np.isnan(btc_s[i])
            and btc_c[i] > btc_s[i]
        )
        rsi_velocity_ok = rsi_delta >= FIXED_RSI_DELTA
        vol_ok = v_arr[i] >= vol_sma_val * c199.VOL_MULT

        atr_pctile_ok = (not np.isnan(atr_pctile_val)
                         and atr_pctile_val >= c199.ATR_TH)
        body_ok = True
        if c199.BODY_RATIO_MIN > 0:
            if np.isnan(body_val):
                body_ok = False
            else:
                body_ok = body_val >= c199.BODY_RATIO_MIN and c_arr[i] >= o_arr[i]
        vol_pctile_ok = (not np.isnan(vol_pctile_val)
                         and vol_pctile_val >= c199.VOL_PCTILE_TH)
        esp_val = esp[i]
        ema_slope_ok = not np.isnan(esp_val) and esp_val >= c199.EMA_SLOPE_PCTILE_TH
        vm_val = vol_mom[i]
        vol_mom_ok = True
        if c199.VOL_MOM_MIN > 0:
            vol_mom_ok = not np.isnan(vm_val) and vm_val >= c199.VOL_MOM_MIN

        if (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and vol_pctile_ok
                and ema_slope_ok and vol_mom_ok):

            buy = o_arr[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val
            entry_bar = i + 1

            rsi_ratio = (c199.RSI_CEILING - rsi_val) / (c199.RSI_CEILING - c199.RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            slope_tp_extra = 0.0
            if c199.TP_SLOPE_BONUS > 0 and not np.isnan(esp_val):
                if esp_val >= 70.0:
                    slope_tp_extra = c199.TP_SLOPE_BONUS
                elif esp_val >= 60.0:
                    slope_tp_extra = c199.TP_SLOPE_BONUS * 0.5

            # === c206 핵심: ATR-adaptive 출구 스케일러 ===
            if np.isnan(atr_pctile_val) or atr_pctile_val >= FIXED_ATR_HI_TH:
                eff_tp_scale = tp_hi_mult
                eff_sl_scale = 1.0
            elif atr_pctile_val <= atr_lo_th:
                eff_tp_scale = tp_lo_mult
                eff_sl_scale = sl_lo_scale
            else:
                interp = (atr_pctile_val - atr_lo_th) / ATR_OFFSET
                eff_tp_scale = tp_lo_mult + (tp_hi_mult - tp_lo_mult) * interp
                eff_sl_scale = sl_lo_scale + (1.0 - sl_lo_scale) * interp

            base_tp_mult = (c199.TP_BASE_ATR + c199.TP_BONUS_ATR * rsi_ratio
                            + slope_tp_extra)
            tp_price = buy + atr_at_entry * base_tp_mult * eff_tp_scale

            base_sl_mult = c199.SL_BASE_ATR - c199.SL_BONUS_ATR * rsi_ratio
            base_sl_mult = max(0.15, base_sl_mult)
            sl_price = buy - atr_at_entry * base_sl_mult * eff_sl_scale

            base_trail_mult = (c199.TRAIL_BASE_ATR
                               + c199.TRAIL_BONUS_ATR * (1.0 - rsi_ratio))
            min_profit_dist = atr_at_entry * c199.MIN_PROFIT_ATR
            max_hold = c199.MAX_HOLD_BASE

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c_arr[j]
                bars_held = j - entry_bar

                if current_price >= tp_price:
                    exit_ret = (tp_price / buy - 1) - FEE - slippage
                    i = j
                    break
                if current_price <= sl_price:
                    exit_ret = (sl_price / buy - 1) - FEE - slippage
                    i = j
                    break
                if current_price > peak_price:
                    peak_price = current_price

                if bars_held >= c199.TRAIL_TIGHTEN_AFTER:
                    eff_trail = base_trail_mult / c199.TRAIL_TIGHTEN_FACTOR
                else:
                    eff_trail = base_trail_mult
                trail_dist = atr_at_entry * eff_trail

                unrealized = peak_price - buy
                if unrealized >= min_profit_dist:
                    if peak_price - current_price >= trail_dist:
                        exit_ret = (current_price / buy - 1) - FEE - slippage
                        i = j
                        break

            if exit_ret is None:
                hold_end = min(i + max_hold, n - 1)
                exit_ret = c_arr[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)
            if exit_ret < 0:
                consecutive_losses += 1
                if (consecutive_losses >= c199.COOLDOWN_LOSSES
                        and c199.COOLDOWN_BARS > 0):
                    cooldown_until = i + c199.COOLDOWN_BARS
                    consecutive_losses = 0
            else:
                consecutive_losses = 0
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    mcl = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl}


def build_combos():
    return [
        {"tp_hi_mult": th, "tp_lo_mult": tl, "sl_lo_scale": ss}
        for th, tl, ss in product(
            TP_HI_MULT_LIST, TP_LO_MULT_LIST, SL_LO_SCALE_LIST)
    ]


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 206 — ATR-adaptive 출구 (TP/SL 배수) ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"목표: OOS Sharpe > {C205_BASELINE_OOS:.3f} OR "
          f"(trades >= 25 AND Sharpe > 35)")
    print("핵심: c205 adaptive 진입 고정 + 변동성 적응형 TP/SL 스케일러")
    print("=" * 80)

    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    sym_data_ok = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-10")
        if df_check.empty or len(df_check) < 500:
            print(f"  {sym}: 데이터 부족 → 제외")
        else:
            print(f"  {sym}: {len(df_check)}행 OK")
            sym_data_ok.append(sym)
    if not sym_data_ok:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    combos = build_combos()
    print(f"\n총 조합: {len(combos)}")

    # Phase 1: train grid
    train_start, train_end = WF_FOLDS[0]["train"]
    print(f"\nPhase 1: train ({train_start} ~ {train_end})")
    sym_train_cache = {}
    for sym in sym_data_ok:
        df_tr = load_historical(sym, "240m", train_start, train_end)
        if df_tr.empty:
            continue
        btc_c, btc_s = c199.align_btc_to_symbol(df_tr, df_btc_full, BTC_SMA_PERIOD)
        esp, vm, ap = c199.precompute_indicators(df_tr)
        sym_train_cache[sym] = (df_tr, btc_c, btc_s, esp, vm, ap)
        print(f"  {sym} train: {len(df_tr)}행")

    results = []
    for idx, combo in enumerate(combos):
        sym_results = []
        for sym in sym_data_ok:
            if sym not in sym_train_cache:
                continue
            df_tr, btc_c, btc_s, esp, vm, ap = sym_train_cache[sym]
            r = _adaptive_exit_backtest(
                df_tr, combo["tp_hi_mult"], combo["tp_lo_mult"],
                combo["sl_lo_scale"],
                btc_c, btc_s, esp, vm, ap,
            )
            sym_results.append(r)
        pooled = c199.pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 5 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    valid = [r for r in results if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")
    print("\n=== Train Top 10 ===")
    print(f"{'tpHi':>5} {'tpLo':>5} {'slSc':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'n':>5}")
    for r in valid[:10]:
        print(f"{r['tp_hi_mult']:>5.2f} {r['tp_lo_mult']:>5.2f} "
              f"{r['sl_lo_scale']:>5.2f} | "
              f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} "
              f"{r['avg_ret']*100:>+6.2f}% {r['max_dd']*100:>+6.2f}% "
              f"{r['trades']:>5}")

    if not valid:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # Phase 2: 3-fold OOS WF
    seen, top = set(), []
    for r in valid:
        k = (r["tp_hi_mult"], r["tp_lo_mult"], r["sl_lo_scale"])
        if k not in seen:
            seen.add(k)
            top.append(r)
        if len(top) >= 10:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(top)}) ===")

    wf_results = []
    for rank, params in enumerate(top, 1):
        th = params["tp_hi_mult"]
        tl = params["tp_lo_mult"]
        ss = params["sl_lo_scale"]
        oos_sharpes, oos_trades, fold_details = [], [], []

        for fold in WF_FOLDS:
            sym_fold = []
            for sym in sym_data_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = c199.align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                esp, vm, ap = c199.precompute_indicators(df_test)
                r = _adaptive_exit_backtest(
                    df_test, th, tl, ss,
                    btc_c, btc_s, esp, vm, ap,
                )
                sym_fold.append(r)
            pooled = c199.pool_results(sym_fold)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(pooled["trades"])
            fold_details.append(pooled)

        avg_oos = float(np.mean(oos_sharpes))
        total_n = sum(oos_trades)
        fold_min_trades = min(oos_trades)
        all_pass = (all(s >= 3.0 for s in oos_sharpes)
                    and avg_oos >= 5.0
                    and fold_min_trades >= 3)
        print(f"  #{rank}: tpHi={th:.2f} tpLo={tl:.2f} slSc={ss:.2f} | "
              f"train={params['sharpe']:+.3f} -> avg_OOS={avg_oos:+.3f} "
              f"n={total_n} fold_min={fold_min_trades} "
              f"{'PASS' if all_pass else 'FAIL'}")
        wf_results.append({
            **params, "train_sharpe": params["sharpe"],
            "avg_oos_sharpe": avg_oos, "oos_sharpes": oos_sharpes,
            "oos_trades": oos_trades, "total_oos_trades": total_n,
            "fold_details": fold_details, "all_pass": all_pass,
            "fold_min_trades": fold_min_trades,
        })

    if not wf_results:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    eligible = [w for w in wf_results if w["fold_min_trades"] >= 3]
    wf_pool = eligible if eligible else wf_results
    wf_sorted = sorted(wf_pool, key=lambda x: x["avg_oos_sharpe"], reverse=True)
    best = wf_sorted[0]

    # Phase 3: slippage stress Top 3
    print(f"\n{'=' * 80}\n=== 슬리피지 스트레스 (Top 3) ===")
    for rank, p in enumerate(wf_sorted[:3], 1):
        th, tl, ss = p["tp_hi_mult"], p["tp_lo_mult"], p["sl_lo_scale"]
        print(f"\n--- #{rank}: tpHi={th:.2f} tpLo={tl:.2f} slSc={ss:.2f} ---")
        for slip in SLIPPAGE_LEVELS:
            sym_results = []
            for sym in sym_data_ok:
                df_full = load_historical(
                    sym, "240m", "2022-01-01", "2026-12-31")
                if df_full.empty:
                    continue
                btc_c, btc_s = c199.align_btc_to_symbol(
                    df_full, df_btc_full, BTC_SMA_PERIOD)
                esp, vm, ap = c199.precompute_indicators(df_full)
                r = _adaptive_exit_backtest(
                    df_full, th, tl, ss,
                    btc_c, btc_s, esp, vm, ap, slippage=slip,
                )
                sym_results.append(r)
            pooled = c199.pool_results(sym_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            print(f"  slip={slip*100:.2f}% Sharpe={sh:+.3f} "
                  f"WR={pooled['wr']:.1%} n={pooled['trades']}")

    # 최종 요약
    print(f"\n{'=' * 80}\n=== 최종 요약 ===")
    print(f"★ OOS 최적: TP_HI_MULT={best['tp_hi_mult']:.2f} "
          f"TP_LO_MULT={best['tp_lo_mult']:.2f} "
          f"SL_LO_SCALE={best['sl_lo_scale']:.2f}")
    print(f"  (진입 고정: VPIN_HI={FIXED_VPIN_HI} VPIN_LO={FIXED_VPIN_LO} "
          f"ATR_HI_TH={FIXED_ATR_HI_TH} RSI_DELTA={FIXED_RSI_DELTA})")
    print(f"  c205 baseline avg_OOS=+{C205_BASELINE_OOS:.3f} → "
          f"c206 avg_OOS={best['avg_oos_sharpe']:+.3f} "
          f"(Δ {best['avg_oos_sharpe']-C205_BASELINE_OOS:+.3f})")
    for i, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][i]
        print(f"  Fold {i+1}: Sharpe={sh:+.3f} WR={fd['wr']:.1%} "
              f"trades={best['oos_trades'][i]} avg={fd['avg_ret']*100:+.2f}% "
              f"MDD={fd['max_dd']*100:+.2f}%")

    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))
    print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr*100:.1f}%")
    print(f"trades: {best['total_oos_trades']}")


if __name__ == "__main__":
    main()
