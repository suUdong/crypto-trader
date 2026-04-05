"""
vpin 사이클 171 — 심볼 확장 스크리닝 (DOGE/AVAX/ADA/SUI/LINK)
- 기반: c165 3-fold WF 최적 파라미터 고정 (VPIN=0.35 MOM=0.0007 Hold=20 CD=4)
- c165 결과: SOL avg OOS +13.254, XRP +8.707, ETH +11.290 — 멀티심볼 일반화 검증됨
- 가설:
  A) Upbit 거래량 상위 알트(DOGE/AVAX/ADA/SUI/LINK)도 VPIN 기반 진입이 유효할 수 있음
  B) 심볼별 독립 3-fold WF — Sharpe >= 5.0 && 전 fold pass 심볼만 후속 wallet 후보
  C) 소규모 진입 그리드(VPIN 0.30/0.35/0.40 × MOM 0.0005/0.0007) 포함 — 심볼 특성 적응
- 진입: next_bar open
- 슬리피지 스트레스 포함
"""
from __future__ import annotations

import math
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

# -- 스크리닝 대상 (ETH/SOL/XRP 제외 Upbit 거래대금 상위) --
SYMBOLS = ["KRW-DOGE", "KRW-AVAX", "KRW-ADA", "KRW-SUI", "KRW-LINK"]
FEE = 0.0005

# -- 고정값 (c152/c157/c163/c164/c165 검증 완료) --
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

# -- c164 최적 고정 --
RSI_DELTA_LB = 3
RSI_DELTA_MIN = 0.0
SL_BASE_ATR = 0.4
SL_BONUS_ATR = 0.2
VOL_MULT = 0.8
ATR_PERIOD = 20
VOL_SMA_PERIOD = 20

# -- c163 최적 고정 (TP/Trail) --
BTC_SMA_PERIOD = 200
TP_BASE_ATR = 4.0
TP_BONUS_ATR = 2.0
TRAIL_BASE_ATR = 0.3
TRAIL_BONUS_ATR = 0.2
MIN_PROFIT_ATR = 1.5

# -- 소규모 진입 그리드 (심볼 특성 적응) --
VPIN_LOW_LIST = [0.30, 0.35, 0.40]
MOM_THRESH_LIST = [0.0005, 0.0007]
MAX_HOLD_LIST = [20]
COOLDOWN_BARS_LIST = [4]

# -- 3-fold Walkforward (c165 동일 구조, 신규 심볼이라 OOS 윈도우 미사용) --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# -- 지표 (c165 동일) --

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def ema_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def sma_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    cumsum = np.cumsum(series)
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate(
        ([0.0], cumsum[:-period]))) / period
    return result


def rsi_calc(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def compute_vpin_bvc(
    closes: np.ndarray, opens: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray, bucket_count: int = 24,
) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(bucket_count, n):
        total_vol = 0.0
        abs_imbalance = 0.0
        for j in range(i - bucket_count, i):
            price_range = highs[j] - lows[j]
            if price_range <= 0:
                buy_frac = 0.5
            else:
                z = (closes[j] - opens[j]) / price_range
                buy_frac = _normal_cdf(z)
            bv = volumes[j] * buy_frac
            sv = volumes[j] * (1.0 - buy_frac)
            abs_imbalance += abs(bv - sv)
            total_vol += volumes[j]
        if total_vol > 0:
            result[i] = abs_imbalance / total_vol
        else:
            result[i] = 0.5
    return result


def compute_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def compute_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 20,
) -> np.ndarray:
    n = len(closes)
    tr = np.full(n, np.nan)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n < period:
        return atr
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def align_btc_to_symbol(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame, btc_sma_period: int,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].values
    btc_sma = sma_calc(btc_close, btc_sma_period)
    btc_close_s = pd.Series(btc_close, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma, index=df_btc.index)
    btc_close_aligned = btc_close_s.reindex(df_sym.index, method="ffill").values
    btc_sma_aligned = btc_sma_s.reindex(df_sym.index, method="ffill").values
    return btc_close_aligned, btc_sma_aligned


# -- 백테스트 --

def backtest(
    df: pd.DataFrame,
    vpin_low: float,
    mom_thresh: float,
    max_hold: int,
    cooldown_bars: int,
    btc_close_aligned: np.ndarray,
    btc_sma_aligned: np.ndarray,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, ATR_PERIOD, VOL_SMA_PERIOD, 50) + 5
    i = warmup
    consecutive_losses = 0
    cooldown_until = 0

    while i < n - 1:
        if cooldown_bars > 0 and i < cooldown_until:
            i += 1
            continue

        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_sma_val = vol_sma_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)
                or np.isnan(atr_val) or atr_val <= 0
                or np.isnan(vol_sma_val) or vol_sma_val <= 0):
            i += 1
            continue

        # RSI velocity
        rsi_prev_idx = i - RSI_DELTA_LB
        if rsi_prev_idx < 0 or np.isnan(rsi_arr[rsi_prev_idx]):
            i += 1
            continue
        rsi_delta = rsi_val - rsi_arr[rsi_prev_idx]

        # 진입 조건
        vpin_ok = (
            vpin_val < vpin_low
            and mom_val >= mom_thresh
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )
        btc_ok = (
            not np.isnan(btc_close_aligned[i])
            and not np.isnan(btc_sma_aligned[i])
            and btc_close_aligned[i] > btc_sma_aligned[i]
        )
        rsi_velocity_ok = rsi_delta >= RSI_DELTA_MIN
        vol_ok = v[i] >= vol_sma_val * VOL_MULT

        if vpin_ok and btc_ok and rsi_velocity_ok and vol_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            atr_at_entry = atr_val

            # RSI 기반 동적 스케일링
            rsi_ratio = (RSI_CEILING - rsi_val) / (RSI_CEILING - RSI_FLOOR)
            rsi_ratio = max(0.0, min(1.0, rsi_ratio))

            # TP/SL/Trail (c163/c164 검증)
            effective_tp_mult = TP_BASE_ATR + TP_BONUS_ATR * rsi_ratio
            tp_price = buy + atr_at_entry * effective_tp_mult

            effective_sl_mult = SL_BASE_ATR - SL_BONUS_ATR * rsi_ratio
            effective_sl_mult = max(0.2, effective_sl_mult)
            sl_price = buy - atr_at_entry * effective_sl_mult

            effective_trail_mult = (
                TRAIL_BASE_ATR + TRAIL_BONUS_ATR * (1.0 - rsi_ratio)
            )
            trail_dist = atr_at_entry * effective_trail_mult
            min_profit_dist = atr_at_entry * MIN_PROFIT_ATR

            exit_ret = None
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]

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

                unrealized = peak_price - buy
                if unrealized >= min_profit_dist:
                    if peak_price - current_price >= trail_dist:
                        exit_ret = (current_price / buy - 1) - FEE - slippage
                        i = j
                        break

            if exit_ret is None:
                hold_end = min(i + max_hold, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)

            if exit_ret < 0:
                consecutive_losses += 1
                if consecutive_losses >= COOLDOWN_LOSSES and cooldown_bars > 0:
                    cooldown_until = i + cooldown_bars
                    consecutive_losses = 0
            else:
                consecutive_losses = 0
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0, "returns": []}
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
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl,
            "returns": returns}


def compute_buy_and_hold(df: pd.DataFrame) -> float:
    """단순 보유(buy-and-hold) 수익률 계산."""
    if df.empty or len(df) < 2:
        return 0.0
    return float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)


def main() -> None:
    print("=" * 80)
    print("=== vpin 사이클 171 — 심볼 확장 스크리닝 (DOGE/AVAX/ADA/SUI/LINK) ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print("가설: c165 최적 VPIN 파라미터가 추가 알트에서도 유효한지 스크리닝")
    print(f"기준선: c165 SOL avg +13.254, XRP +8.707, ETH +11.290")
    print(f"고정: dLB={RSI_DELTA_LB} dMin={RSI_DELTA_MIN} "
          f"SL={SL_BASE_ATR}-{SL_BONUS_ATR} vMul={VOL_MULT}")
    print(f"TP/Trail: TP={TP_BASE_ATR}+{TP_BONUS_ATR} "
          f"Trail={TRAIL_BASE_ATR}+{TRAIL_BONUS_ATR} minP={MIN_PROFIT_ATR}")
    print(f"진입 그리드: VPIN {VPIN_LOW_LIST} × MOM {MOM_THRESH_LIST} = "
          f"{len(VPIN_LOW_LIST) * len(MOM_THRESH_LIST)} combos")
    print("=" * 80)

    # -- BTC 데이터 --
    df_btc_full = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    # -- 심볼별 데이터 확인 --
    print("\n--- 심볼별 데이터 확인 ---")
    sym_data_ok: list[str] = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df_check.empty or len(df_check) < 500:
            print(f"  {sym}: 데이터 부족 ({len(df_check) if not df_check.empty else 0}행) → 제외")
        else:
            print(f"  {sym}: {len(df_check)}행 OK")
            sym_data_ok.append(sym)

    if not sym_data_ok:
        print("유효 심볼 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    combos = list(product(VPIN_LOW_LIST, MOM_THRESH_LIST, MAX_HOLD_LIST,
                          COOLDOWN_BARS_LIST))
    print(f"\n총 조합: {len(combos)}개 × {len(sym_data_ok)} 심볼")

    # -- 심볼별 개별 3-fold WF --
    print(f"\n{'=' * 80}")
    print("=== 심볼별 개별 3-fold Walk-Forward ===")

    all_symbol_results: dict[str, list[dict]] = {}

    for sym in sym_data_ok:
        print(f"\n--- {sym} ---")

        # Buy-and-hold 기준선
        df_full = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        bh_ret = compute_buy_and_hold(df_full)
        print(f"  Buy-and-Hold (2022~2026): {bh_ret * 100:+.1f}%")

        sym_wf_results: list[dict] = []

        for vl, mt, mh, cb in combos:
            oos_sharpes: list[float] = []
            oos_trades: list[int] = []
            fold_details: list[dict] = []

            for fold_i, fold in enumerate(WF_FOLDS):
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty:
                    oos_sharpes.append(0.0)
                    oos_trades.append(0)
                    fold_details.append(
                        {"sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0,
                         "trades": 0, "max_dd": 0.0, "mcl": 0})
                    continue
                btc_c, btc_s = align_btc_to_symbol(
                    df_test, df_btc_full, BTC_SMA_PERIOD)
                r = backtest(df_test, vl, mt, mh, cb, btc_c, btc_s)
                sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
                oos_sharpes.append(sh)
                oos_trades.append(r["trades"])
                fold_details.append(r)

            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            total_n = sum(oos_trades)
            all_pass = (all(s >= 3.0 for s in oos_sharpes)
                        and avg_oos >= 5.0 and total_n >= 20)

            sym_wf_results.append({
                "vpin_low": vl, "mom_thresh": mt,
                "max_hold": mh, "cooldown_bars": cb,
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "total_oos_trades": total_n,
                "all_pass": all_pass,
                "fold_details": fold_details,
            })

        # 심볼별 결과 정렬
        sym_wf_results.sort(key=lambda x: x["avg_oos_sharpe"], reverse=True)
        all_symbol_results[sym] = sym_wf_results

        # 상위 3개 출력
        print(f"  {'VPIN':>5} {'MOM':>7} | {'avg_OOS':>8} {'min_OOS':>8} "
              f"{'F1':>7} {'F2':>7} {'F3':>7} {'n':>4} {'Pass':>5}")
        print(f"  {'-' * 70}")
        for r in sym_wf_results[:6]:
            f_strs = [f"{s:+.1f}" for s in r["oos_sharpes"]]
            while len(f_strs) < 3:
                f_strs.append("  n/a")
            status = "PASS" if r["all_pass"] else "FAIL"
            print(f"  {r['vpin_low']:>5.2f} {r['mom_thresh']:>7.4f} | "
                  f"{r['avg_oos_sharpe']:>+8.3f} {r['min_oos_sharpe']:>+8.3f} "
                  f"{f_strs[0]:>7} {f_strs[1]:>7} {f_strs[2]:>7} "
                  f"{r['total_oos_trades']:>4} {status:>5}")

    # -- 슬리피지 스트레스 (PASS 심볼만) --
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (PASS 심볼 × 최적 파라미터) ===")

    pass_symbols: list[tuple[str, dict]] = []
    for sym, results in all_symbol_results.items():
        best = results[0]
        if best["all_pass"]:
            pass_symbols.append((sym, best))

    if not pass_symbols:
        print("  PASS 심볼 없음 — 슬리피지 테스트 스킵")
        # 최선의 결과라도 출력
        print(f"\n{'=' * 80}")
        print("=== 전체 심볼 요약 (best per symbol) ===")
        best_sharpe = float("-inf")
        best_sym = ""
        best_n = 0
        best_wr = 0.0
        for sym, results in all_symbol_results.items():
            best = results[0]
            avg_wr = float(np.mean(
                [fd["wr"] for fd in best["fold_details"] if fd["trades"] > 0]))
            status = "PASS" if best["all_pass"] else "FAIL"
            print(f"  {sym}: avg OOS Sharpe={best['avg_oos_sharpe']:+.3f} "
                  f"WR={avg_wr:.1%} n={best['total_oos_trades']} "
                  f"VPIN={best['vpin_low']} MOM={best['mom_thresh']} [{status}]")
            if best["avg_oos_sharpe"] > best_sharpe:
                best_sharpe = best["avg_oos_sharpe"]
                best_sym = sym
                best_n = best["total_oos_trades"]
                best_wr = avg_wr

        # Fold 상세 (전 심볼)
        print(f"\n--- Fold 상세 (전 심볼 best 파라미터) ---")
        for sym, results in all_symbol_results.items():
            best = results[0]
            print(f"  {sym} (VPIN={best['vpin_low']} MOM={best['mom_thresh']}):")
            for fi, fd in enumerate(best["fold_details"]):
                sh = fd["sharpe"] if not np.isnan(fd.get("sharpe", 0)) else 0.0
                print(f"    F{fi+1}: Sharpe={sh:+.3f} WR={fd['wr']:.1%} "
                      f"n={fd['trades']} avg={fd['avg_ret']*100:+.2f}% "
                      f"MDD={fd['max_dd']*100:+.2f}%")

        print(f"\nSharpe: {best_sharpe:+.3f}")
        print(f"WR: {best_wr * 100:.1f}%")
        print(f"trades: {best_n}")
        return

    for sym, best in pass_symbols:
        vl = best["vpin_low"]
        mt = best["mom_thresh"]
        mh = best["max_hold"]
        cb = best["cooldown_bars"]
        print(f"\n--- {sym}: VPIN={vl} MOM={mt} Hold={mh} CD={cb} "
              f"(avg OOS: {best['avg_oos_sharpe']:+.3f}) ---")
        print(f"  {'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print(f"  {'-' * 55}")

        # Buy-and-hold 비교용
        df_full = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        bh_ret = compute_buy_and_hold(df_full)

        for slip in SLIPPAGE_LEVELS:
            df_full = load_historical(sym, "240m", "2022-01-01", "2026-12-31")
            if df_full.empty:
                continue
            btc_c, btc_s = align_btc_to_symbol(
                df_full, df_btc_full, BTC_SMA_PERIOD)
            r = backtest(df_full, vl, mt, mh, cb, btc_c, btc_s, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% "
                  f"{r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

        # 전략 수익률 vs Buy-and-Hold
        r_base = backtest(df_full, vl, mt, mh, cb,
                          *align_btc_to_symbol(df_full, df_btc_full, BTC_SMA_PERIOD))
        strat_ret = sum(r_base.get("returns", []))
        print(f"  전략 누적수익률: {strat_ret * 100:+.1f}% vs "
              f"Buy-and-Hold: {bh_ret * 100:+.1f}%")

    # -- Fold 상세 (PASS 심볼) --
    print(f"\n{'=' * 80}")
    print("=== Fold 상세 (PASS 심볼) ===")
    for sym, best in pass_symbols:
        vl = best["vpin_low"]
        mt = best["mom_thresh"]
        print(f"\n  {sym} (VPIN={vl} MOM={mt}):")
        for fi, fd in enumerate(best["fold_details"]):
            sh = fd["sharpe"] if not np.isnan(fd.get("sharpe", 0)) else 0.0
            print(f"    F{fi+1}: Sharpe={sh:+.3f} WR={fd['wr']:.1%} "
                  f"n={fd['trades']} avg={fd['avg_ret']*100:+.2f}% "
                  f"MDD={fd['max_dd']*100:+.2f}%")

    # -- 전체 요약 --
    print(f"\n{'=' * 80}")
    print("=== 전체 심볼 요약 ===")
    total_pass = 0
    best_sharpe = float("-inf")
    best_sym = ""
    best_n = 0
    best_wr = 0.0

    for sym, results in all_symbol_results.items():
        best = results[0]
        avg_wr = float(np.mean(
            [fd["wr"] for fd in best["fold_details"] if fd["trades"] > 0]))
        status = "✅ PASS" if best["all_pass"] else "❌ FAIL"
        if best["all_pass"]:
            total_pass += 1
        print(f"  {sym}: avg OOS Sharpe={best['avg_oos_sharpe']:+.3f} "
              f"WR={avg_wr:.1%} n={best['total_oos_trades']} "
              f"VPIN={best['vpin_low']} MOM={best['mom_thresh']} [{status}]")
        if best["avg_oos_sharpe"] > best_sharpe:
            best_sharpe = best["avg_oos_sharpe"]
            best_sym = sym
            best_n = best["total_oos_trades"]
            best_wr = avg_wr

    print(f"\n  PASS: {total_pass}/{len(sym_data_ok)} 심볼")
    print(f"  최우수: {best_sym} Sharpe={best_sharpe:+.3f}")

    # 최종 출력
    if pass_symbols:
        # PASS 심볼 중 최우수
        pass_best = max(pass_symbols, key=lambda x: x[1]["avg_oos_sharpe"])
        sym, best = pass_best
        avg_wr = float(np.mean(
            [fd["wr"] for fd in best["fold_details"] if fd["trades"] > 0]))
        print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
        print(f"WR: {avg_wr * 100:.1f}%")
        print(f"trades: {best['total_oos_trades']}")
    else:
        print(f"\nSharpe: {best_sharpe:+.3f}")
        print(f"WR: {best_wr * 100:.1f}%")
        print(f"trades: {best_n}")


if __name__ == "__main__":
    main()
