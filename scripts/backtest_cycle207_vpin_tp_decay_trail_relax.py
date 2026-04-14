"""
vpin_multi 사이클 207 — TP 시간감쇠 + 트레일링 최소이익 완화

배경:
- c206 최적: TP_HI=1.40 TP_LO=0.70 SL_SC=1.00
  avg_OOS=+37.875, WR=63.9%, trades=23
- 슬리피지 0.20%에서 WR 44.3%로 급락 → 출구 타이밍 문제
- TP에 도달 못 하고 max_hold 또는 SL로 빠지는 거래 비율 높음

가설:
- 보유 바 증가 시 TP를 점진 축소 → "거의 이익"인 거래 확정
- 트레일링 최소이익(MIN_PROFIT_ATR) 완화 → 조기 수익 확정
- 두 메커니즘 결합 시 슬리피지 내성 향상 + WR 개선

탐색 그리드 (3×3×3 = 27 combos, c206 최적 고정):
  TP_DECAY_START: [4, 6, 8]    — 감쇠 시작 바 (이후부터 TP 축소)
  TP_DECAY_RATE:  [0.03, 0.05, 0.08] — 바당 TP 축소 비율
  MIN_PROFIT_SCALE: [0.5, 0.75, 1.0]  — MIN_PROFIT_ATR 스케일러

고정 (c206 최적):
  TP_HI=1.40, TP_LO=0.70, SL_SC=1.00
  VPIN_HI=0.36, VPIN_LO=0.30, ATR_HI_TH=50, RSI_DELTA=7, MOM=0.0003
검증: 3-fold WF, slippage stress Top 3
목표: avg_OOS Sharpe > 37.875 OR slippage(0.20%) WR > 50%
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

# 심볼 (c206 동일)
SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE", "KRW-AVAX"]

# c206 최적 출구 파라미터 (고정)
FIXED_TP_HI_MULT = 1.40
FIXED_TP_LO_MULT = 0.70
FIXED_SL_LO_SCALE = 1.00

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

# 탐색 그리드 — TP 감쇠 + 트레일링 완화
TP_DECAY_START_LIST = [4, 6, 8]       # 감쇠 시작 바
TP_DECAY_RATE_LIST = [0.03, 0.05, 0.08]  # 바당 TP 축소율
MIN_PROFIT_SCALE_LIST = [0.5, 0.75, 1.0]  # MIN_PROFIT_ATR 스케일러

WF_FOLDS = c199.WF_FOLDS
SLIPPAGE_LEVELS = c199.SLIPPAGE_LEVELS
BTC_SMA_PERIOD = c199.BTC_SMA_PERIOD

C206_BASELINE_OOS = 37.875


def _tp_decay_trail_backtest(
    df, tp_decay_start, tp_decay_rate, min_profit_scale,
    btc_c, btc_s, esp, vol_mom, atr_pctile,
    slippage=0.0005,
):
    """c206 adaptive exit + TP 시간감쇠 + 트레일링 최소이익 완화.

    TP 감쇠: bars_held >= tp_decay_start 이후 매 바마다
      effective_tp = tp_price * (1 - tp_decay_rate * (bars_held - tp_decay_start))
      최소 한도: 진입가 + 0.5 * ATR (손실 방지)
    트레일링: MIN_PROFIT_ATR * min_profit_scale로 활성화 문턱 낮춤
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
            effective_vpin_low = (FIXED_VPIN_LO
                                 + (FIXED_VPIN_HI - FIXED_VPIN_LO) * ratio)

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
                body_ok = (body_val >= c199.BODY_RATIO_MIN
                           and c_arr[i] >= o_arr[i])
        vol_pctile_ok = (not np.isnan(vol_pctile_val)
                         and vol_pctile_val >= c199.VOL_PCTILE_TH)
        esp_val = esp[i]
        ema_slope_ok = (not np.isnan(esp_val)
                        and esp_val >= c199.EMA_SLOPE_PCTILE_TH)
        vm_val = vol_mom[i]
        vol_mom_ok = True
        if c199.VOL_MOM_MIN > 0:
            vol_mom_ok = not np.isnan(vm_val) and vm_val >= c199.VOL_MOM_MIN

        if not (vpin_ok and btc_ok and rsi_velocity_ok and vol_ok
                and atr_pctile_ok and body_ok and vol_pctile_ok
                and ema_slope_ok and vol_mom_ok):
            i += 1
            continue

        buy = o_arr[i + 1] * (1 + FEE + slippage)
        peak_price = buy
        atr_at_entry = atr_val
        entry_bar = i + 1

        rsi_ratio = ((c199.RSI_CEILING - rsi_val)
                     / (c199.RSI_CEILING - c199.RSI_FLOOR))
        rsi_ratio = max(0.0, min(1.0, rsi_ratio))

        slope_tp_extra = 0.0
        if c199.TP_SLOPE_BONUS > 0 and not np.isnan(esp_val):
            if esp_val >= 70.0:
                slope_tp_extra = c199.TP_SLOPE_BONUS
            elif esp_val >= 60.0:
                slope_tp_extra = c199.TP_SLOPE_BONUS * 0.5

        # === c206 adaptive exit 스케일러 (고정) ===
        if np.isnan(atr_pctile_val) or atr_pctile_val >= FIXED_ATR_HI_TH:
            eff_tp_scale = FIXED_TP_HI_MULT
            eff_sl_scale = 1.0
        elif atr_pctile_val <= atr_lo_th:
            eff_tp_scale = FIXED_TP_LO_MULT
            eff_sl_scale = FIXED_SL_LO_SCALE
        else:
            interp = (atr_pctile_val - atr_lo_th) / ATR_OFFSET
            eff_tp_scale = (FIXED_TP_LO_MULT
                            + (FIXED_TP_HI_MULT - FIXED_TP_LO_MULT) * interp)
            eff_sl_scale = (FIXED_SL_LO_SCALE
                            + (1.0 - FIXED_SL_LO_SCALE) * interp)

        base_tp_mult = (c199.TP_BASE_ATR + c199.TP_BONUS_ATR * rsi_ratio
                        + slope_tp_extra)
        original_tp_price = buy + atr_at_entry * base_tp_mult * eff_tp_scale

        base_sl_mult = c199.SL_BASE_ATR - c199.SL_BONUS_ATR * rsi_ratio
        base_sl_mult = max(0.15, base_sl_mult)
        sl_price = buy - atr_at_entry * base_sl_mult * eff_sl_scale

        base_trail_mult = (c199.TRAIL_BASE_ATR
                           + c199.TRAIL_BONUS_ATR * (1.0 - rsi_ratio))
        # c207: 완화된 최소이익 거리
        min_profit_dist = atr_at_entry * c199.MIN_PROFIT_ATR * min_profit_scale
        max_hold = c199.MAX_HOLD_BASE

        # TP 감쇠 하한: 진입가 + 0.5 ATR (최소 이익 보장)
        tp_floor = buy + atr_at_entry * 0.5

        exit_ret = None
        for j in range(i + 2, min(i + 1 + max_hold, n)):
            current_price = c_arr[j]
            bars_held = j - entry_bar

            # === c207 핵심: TP 시간감쇠 ===
            if bars_held >= tp_decay_start:
                decay = tp_decay_rate * (bars_held - tp_decay_start)
                effective_tp = original_tp_price * (1.0 - decay)
                effective_tp = max(effective_tp, tp_floor)
            else:
                effective_tp = original_tp_price

            if current_price >= effective_tp:
                exit_ret = (effective_tp / buy - 1) - FEE - slippage
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

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak_cum = np.maximum.accumulate(cum)
    dd = cum - peak_cum
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
        {"tp_decay_start": ds, "tp_decay_rate": dr,
         "min_profit_scale": mps}
        for ds, dr, mps in product(
            TP_DECAY_START_LIST, TP_DECAY_RATE_LIST, MIN_PROFIT_SCALE_LIST)
    ]


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 207 — TP 시간감쇠 + 트레일링 최소이익 완화 ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"목표: OOS Sharpe > {C206_BASELINE_OOS:.3f} OR "
          f"slippage(0.20%) WR > 50%")
    print("핵심: c206 adaptive exit 고정 + TP decay + trail min-profit relax")
    print(f"고정: TP_HI={FIXED_TP_HI_MULT} TP_LO={FIXED_TP_LO_MULT} "
          f"SL_SC={FIXED_SL_LO_SCALE}")
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
        btc_c, btc_s = c199.align_btc_to_symbol(
            df_tr, df_btc_full, BTC_SMA_PERIOD)
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
            r = _tp_decay_trail_backtest(
                df_tr, combo["tp_decay_start"], combo["tp_decay_rate"],
                combo["min_profit_scale"],
                btc_c, btc_s, esp, vm, ap,
            )
            sym_results.append(r)
        pooled = c199.pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 9 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    valid = [r for r in results
             if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")
    print("\n=== Train Top 10 ===")
    print(f"{'dcSt':>5} {'dcRt':>5} {'mpSc':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'n':>5}")
    for r in valid[:10]:
        print(f"{r['tp_decay_start']:>5} {r['tp_decay_rate']:>5.2f} "
              f"{r['min_profit_scale']:>5.2f} | "
              f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} "
              f"{r['avg_ret']*100:>+6.2f}% {r['max_dd']*100:>+6.2f}% "
              f"{r['trades']:>5}")

    if not valid:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # Phase 2: 3-fold OOS WF
    seen, top = set(), []
    for r in valid:
        k = (r["tp_decay_start"], r["tp_decay_rate"],
             r["min_profit_scale"])
        if k not in seen:
            seen.add(k)
            top.append(r)
        if len(top) >= 10:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(top)}) ===")

    wf_results = []
    for rank, params in enumerate(top, 1):
        ds = params["tp_decay_start"]
        dr = params["tp_decay_rate"]
        mps = params["min_profit_scale"]
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
                r = _tp_decay_trail_backtest(
                    df_test, ds, dr, mps,
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
        print(f"  #{rank}: dcSt={ds} dcRt={dr:.2f} mpSc={mps:.2f} | "
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
    wf_sorted = sorted(
        wf_pool, key=lambda x: x["avg_oos_sharpe"], reverse=True)
    best = wf_sorted[0]

    # Phase 3: slippage stress Top 3
    print(f"\n{'=' * 80}\n=== 슬리피지 스트레스 (Top 3) ===")
    for rank, p in enumerate(wf_sorted[:3], 1):
        ds = p["tp_decay_start"]
        dr = p["tp_decay_rate"]
        mps = p["min_profit_scale"]
        print(f"\n--- #{rank}: dcSt={ds} dcRt={dr:.2f} mpSc={mps:.2f} ---")
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
                r = _tp_decay_trail_backtest(
                    df_full, ds, dr, mps,
                    btc_c, btc_s, esp, vm, ap, slippage=slip,
                )
                sym_results.append(r)
            pooled = c199.pool_results(sym_results)
            sh = (pooled["sharpe"]
                  if not np.isnan(pooled["sharpe"]) else 0.0)
            print(f"  slip={slip*100:.2f}% Sharpe={sh:+.3f} "
                  f"WR={pooled['wr']:.1%} n={pooled['trades']}")

    # 최종 요약
    print(f"\n{'=' * 80}\n=== 최종 요약 ===")
    print(f"★ OOS 최적: TP_DECAY_START={best['tp_decay_start']} "
          f"TP_DECAY_RATE={best['tp_decay_rate']:.2f} "
          f"MIN_PROFIT_SCALE={best['min_profit_scale']:.2f}")
    print(f"  (출구 고정: TP_HI={FIXED_TP_HI_MULT} TP_LO={FIXED_TP_LO_MULT} "
          f"SL_SC={FIXED_SL_LO_SCALE})")
    print(f"  (진입 고정: VPIN_HI={FIXED_VPIN_HI} VPIN_LO={FIXED_VPIN_LO} "
          f"ATR_HI_TH={FIXED_ATR_HI_TH} RSI_DELTA={FIXED_RSI_DELTA})")
    print(f"  c206 baseline avg_OOS=+{C206_BASELINE_OOS:.3f} → "
          f"c207 avg_OOS={best['avg_oos_sharpe']:+.3f} "
          f"(Δ {best['avg_oos_sharpe']-C206_BASELINE_OOS:+.3f})")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi+1}: Sharpe={sh:+.3f} WR={fd['wr']:.1%} "
              f"trades={best['oos_trades'][fi]} "
              f"avg={fd['avg_ret']*100:+.2f}% "
              f"MDD={fd['max_dd']*100:+.2f}%")

    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))
    print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr*100:.1f}%")
    print(f"trades: {best['total_oos_trades']}")


if __name__ == "__main__":
    main()
