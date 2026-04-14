"""
vpin_multi 사이클 205 — ATR-adaptive VPIN 임계값

배경:
- c204 최적: MOM=0.0001 rsiD=7 VPIN_LOW=0.34, avg_OOS=+36.088
- 핵심 문제: Fold 1 = 0 trades (저변동성 구간에서 VPIN 0.34 고정이 너무 높음)
- VPIN < 0.34 고정은 trades=0 (0.30, 0.32 전멸)
- MOM 비구속 확인 (0.0001~0.0005 동일) → MOM 고정 0.0003

가설:
- VPIN 임계값이 고정이면 저변동성 구간(ATR pctile 낮음)에서 진입 불가
- ATR pctile 기반으로 VPIN_LOW를 동적 조절:
  ATR pctile >= hi_atr → VPIN_LOW = vpin_hi (현행 유지, 0.34~0.38)
  ATR pctile <= lo_atr → VPIN_LOW = vpin_lo (완화, 0.28~0.34)
  중간 구간 → 선형 보간
- 저변동성 구간에서 VPIN 문턱을 낮춰 진입 기회 확보
- 고변동성 구간에서는 기존 수준 유지

탐색 그리드 (3×3×3×2 = 54 combos):
  VPIN_HI:    [0.34, 0.36, 0.38]    — 고변동 구간 VPIN 임계값
  VPIN_LO:    [0.28, 0.30, 0.32]    — 저변동 구간 VPIN 임계값 (완화)
  ATR_HI_TH:  [50, 60, 70]          — 고변동 판정 ATR pctile
  RSI_DELTA:   [6, 7]               — c204 최적(7) + 하나 완화(6)

고정: MOM=0.0003, c192 출구 (regime 비활성), SYMBOLS = c204 동일
검증: 3-fold WF, slippage stress Top 3
목표: avg_OOS Sharpe > 36.088 AND total_trades >= 20 (Fold별 >= 3)
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

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]

# c199 고정 파라미터 (regime 비활성)
FIXED_REGIME_TH = 100
FIXED_HI_TP_BONUS = 0.0
FIXED_HI_TRAIL_RELAX = 1.0
FIXED_LO_SL_TIGHTEN = 0.0

# c204 확정: MOM 비구속 → 고정
FIXED_MOM = 0.0003

# 탐색 그리드
VPIN_HI_LIST = [0.34, 0.36, 0.38]
VPIN_LO_LIST = [0.28, 0.30, 0.32]
ATR_HI_TH_LIST = [50, 60, 70]
RSI_DELTA_LIST = [6, 7]

# ATR 적응 시 lo_atr = hi_atr - 20 (고정 오프셋)
ATR_OFFSET = 20

WF_FOLDS = c199.WF_FOLDS
SLIPPAGE_LEVELS = c199.SLIPPAGE_LEVELS
BTC_SMA_PERIOD = c199.BTC_SMA_PERIOD

C204_BASELINE_OOS = 36.088


def _adaptive_vpin_backtest(
    df, vpin_hi, vpin_lo, atr_hi_th, rsi_delta_min,
    btc_c, btc_s, esp, vol_mom, atr_pctile,
    slippage=0.0005,
):
    """ATR pctile 기반 동적 VPIN 임계값으로 c199.backtest를 래핑.

    매 바마다 ATR pctile → effective VPIN_LOW 계산 후 진입 판정.
    c199.backtest 내부 VPIN_LOW를 최대 완화값(vpin_lo)으로 설정하고,
    진입 후보 중 adaptive threshold 미통과건은 필터링.
    → c199 backtest를 직접 수정하지 않고, 사전/사후 필터로 구현.

    구현: c199 전역변수를 vpin_lo로 설정(최대 완화) 후 backtest 실행,
    그 결과에서 adaptive threshold 미통과 건을 제거할 수 없음(내부 루프).
    → 대안: c199 backtest 함수를 복사+수정하여 adaptive 로직 삽입.
    """
    import math

    c_arr = df["close"].values
    o_arr = df["open"].values
    h_arr = df["high"].values
    lo_arr = df["low"].values
    v_arr = df["volume"].values
    n = len(c_arr)

    rsi_arr = c199.rsi_calc(c_arr, c199.RSI_PERIOD)
    ema_arr = c199.ema_calc(c_arr, c199.EMA_PERIOD)
    vpin_arr = c199.compute_vpin_bvc(c_arr, o_arr, h_arr, lo_arr, v_arr, c199.BUCKET_COUNT)
    mom_arr = c199.compute_momentum(c_arr, c199.MOM_LOOKBACK)
    atr_arr = c199.compute_atr(h_arr, lo_arr, c_arr, c199.ATR_PERIOD)
    vol_sma_arr = c199.sma_calc(v_arr, c199.VOL_SMA_PERIOD)
    body_ratio_arr = c199.compute_body_ratio(o_arr, c_arr, h_arr, lo_arr)
    vol_pctile_arr = c199.compute_vol_percentile(v_arr, c199.VOL_PCTILE_LB)

    atr_lo_th = atr_hi_th - ATR_OFFSET

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

        # === c205 핵심: ATR-adaptive VPIN threshold ===
        if np.isnan(atr_pctile_val):
            effective_vpin_low = vpin_hi  # fallback: 보수적
        elif atr_pctile_val >= atr_hi_th:
            effective_vpin_low = vpin_hi
        elif atr_pctile_val <= atr_lo_th:
            effective_vpin_low = vpin_lo
        else:
            # 선형 보간
            ratio = (atr_pctile_val - atr_lo_th) / ATR_OFFSET
            effective_vpin_low = vpin_lo + (vpin_hi - vpin_lo) * ratio

        # 진입 조건
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
        rsi_velocity_ok = rsi_delta >= rsi_delta_min
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

            # regime 비활성 (고정)
            effective_tp_mult = (c199.TP_BASE_ATR + c199.TP_BONUS_ATR * rsi_ratio
                                 + slope_tp_extra)
            tp_price = buy + atr_at_entry * effective_tp_mult

            effective_sl_mult = c199.SL_BASE_ATR - c199.SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.15, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

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
                if consecutive_losses >= c199.COOLDOWN_LOSSES and c199.COOLDOWN_BARS > 0:
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
        {"vpin_hi": vh, "vpin_lo": vl, "atr_hi_th": ath, "rsi_delta_min": rd}
        for vh, vl, ath, rd in product(
            VPIN_HI_LIST, VPIN_LO_LIST, ATR_HI_TH_LIST, RSI_DELTA_LIST)
        if vl < vh  # vpin_lo는 반드시 vpin_hi보다 작아야 의미 있음
    ]


def main() -> None:
    print("=" * 80)
    print("=== vpin_multi 사이클 205 — ATR-adaptive VPIN 임계값 ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"목표: OOS Sharpe > {C204_BASELINE_OOS:.3f} AND trades >= 20")
    print("핵심: 저변동성 구간 VPIN 완화 → Fold 1 진입 0건 해결")
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
            r = _adaptive_vpin_backtest(
                df_tr, combo["vpin_hi"], combo["vpin_lo"],
                combo["atr_hi_th"], combo["rsi_delta_min"],
                btc_c, btc_s, esp, vm, ap,
            )
            sym_results.append(r)
        pooled = c199.pool_results(sym_results)
        results.append({**combo, **pooled})
        if (idx + 1) % 10 == 0:
            print(f"  [{idx + 1}/{len(combos)}] 완료")

    valid = [r for r in results if r["trades"] >= 6 and not np.isnan(r["sharpe"])]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n유효 조합 (n>=6): {len(valid)}/{len(results)}")
    print("\n=== Train Top 10 ===")
    print(f"{'vpHi':>5} {'vpLo':>5} {'atrTh':>5} {'rsiD':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'n':>5}")
    for r in valid[:10]:
        print(f"{r['vpin_hi']:>5.2f} {r['vpin_lo']:>5.2f} "
              f"{r['atr_hi_th']:>5} {r['rsi_delta_min']:>5} | "
              f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} "
              f"{r['avg_ret']*100:>+6.2f}% {r['max_dd']*100:>+6.2f}% "
              f"{r['trades']:>5}")

    if not valid:
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # Phase 2: 3-fold OOS WF
    seen, top = set(), []
    for r in valid:
        k = (r["vpin_hi"], r["vpin_lo"], r["atr_hi_th"], r["rsi_delta_min"])
        if k not in seen:
            seen.add(k)
            top.append(r)
        if len(top) >= 10:
            break

    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward 검증 (Top {len(top)}) ===")

    wf_results = []
    for rank, params in enumerate(top, 1):
        vh = params["vpin_hi"]
        vl = params["vpin_lo"]
        ath = params["atr_hi_th"]
        rd = params["rsi_delta_min"]
        oos_sharpes, oos_trades, fold_details = [], [], []

        for fold in WF_FOLDS:
            sym_fold = []
            for sym in sym_data_ok:
                df_test = load_historical(sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    continue
                btc_c, btc_s = c199.align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                esp, vm, ap = c199.precompute_indicators(df_test)
                r = _adaptive_vpin_backtest(
                    df_test, vh, vl, ath, rd,
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
        # 모든 Fold >= 3 trades AND avg_OOS >= 5
        fold_min_trades = min(oos_trades)
        all_pass = (all(s >= 3.0 for s in oos_sharpes)
                    and avg_oos >= 5.0
                    and fold_min_trades >= 3)
        print(f"  #{rank}: vpHi={vh:.2f} vpLo={vl:.2f} atrTh={ath} rsiD={rd} | "
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

    # 정렬: Fold별 최소 거래수 >= 3인 것 우선, 그 내에서 avg_OOS 순
    eligible = [w for w in wf_results if w["fold_min_trades"] >= 3]
    wf_pool = eligible if eligible else wf_results
    wf_sorted = sorted(wf_pool, key=lambda x: x["avg_oos_sharpe"], reverse=True)
    best = wf_sorted[0]

    # Phase 3: slippage stress Top 3
    print(f"\n{'=' * 80}\n=== 슬리피지 스트레스 (Top 3) ===")
    for rank, p in enumerate(wf_sorted[:3], 1):
        vh, vl = p["vpin_hi"], p["vpin_lo"]
        ath, rd = p["atr_hi_th"], p["rsi_delta_min"]
        print(f"\n--- #{rank}: vpHi={vh:.2f} vpLo={vl:.2f} "
              f"atrTh={ath} rsiD={rd} ---")
        for slip in SLIPPAGE_LEVELS:
            sym_results = []
            for sym in sym_data_ok:
                df_full = load_historical(sym, "240m", "2022-01-01", "2026-12-31")
                if df_full.empty:
                    continue
                btc_c, btc_s = c199.align_btc_to_symbol(
                    df_full, df_btc_full, BTC_SMA_PERIOD)
                esp, vm, ap = c199.precompute_indicators(df_full)
                r = _adaptive_vpin_backtest(
                    df_full, vh, vl, ath, rd,
                    btc_c, btc_s, esp, vm, ap, slippage=slip,
                )
                sym_results.append(r)
            pooled = c199.pool_results(sym_results)
            sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            print(f"  slip={slip*100:.2f}% Sharpe={sh:+.3f} "
                  f"WR={pooled['wr']:.1%} n={pooled['trades']}")

    # 최종 요약
    print(f"\n{'=' * 80}\n=== 최종 요약 ===")
    print(f"★ OOS 최적: VPIN_HI={best['vpin_hi']:.2f} "
          f"VPIN_LO={best['vpin_lo']:.2f} "
          f"ATR_HI_TH={best['atr_hi_th']} "
          f"RSI_DELTA={best['rsi_delta_min']}")
    print(f"  c204 baseline avg_OOS=+{C204_BASELINE_OOS:.3f} → "
          f"c205 avg_OOS={best['avg_oos_sharpe']:+.3f} "
          f"(Δ {best['avg_oos_sharpe']-C204_BASELINE_OOS:+.3f})")
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
