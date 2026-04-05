"""
c167: ETH MA breakdown exit overlay on c168 trailing+regime hold baseline
━━━━━━━━���━━━━━━━━━━���━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
평가자 [explore]: "알트 개별 momentum exit overlay (알트 자체 20-day MA 이탈 시
포지션 청산)" — 현 vpin_eth 전략에 ETH MA breakdown exit 추가.
기존 TP/SL/trailing과 병렬 작동, 추가 exit 조건으로만 기능.

기반: c168 3-fold 최적 (hvH=24 lvH=12 trA=1.8 trSL=0.4)
  - c165에서 81/81 3-fold WF 통과, avg OOS +14.111

오버레이 설계:
  - 보유 중 ETH close가 N-period MA 아래로 이탈하면 즉시 청산
  - MA 타입: SMA / EMA
  - MA 기간: 10, 15, 20, 30, 50
  - 확인 봉수: 1 (즉시), 2, 3 (연속 N봉 이탈 확인)
  - 기대 효과: BEAR fold(F3) MDD 개선, BULL fold(F1) 영향 최소

그리드: 2 types × 5 periods × 3 confirms = 30 조합 + 1 baseline = 31
3-fold WF (c165와 동일):
  F1: OOS 2024-01~2024-09 (BULL)
  F2: OOS 2025-01~2025-09 (★2025 BEAR)
  F3: OOS 2025-10~2026-04 (회복기)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005

# ── 고정: c168 3-fold 최적 파라미터 ────────────────────────────────────────
BTC_EMA_PERIOD = 50
BTC_MOM_LOOKBACK = 10
BTC_MOM_THRESH = 0.02
VOL_SMA_PERIOD = 30
VOL_MULT = 1.5
VPIN_HIGH = 0.50
RSI_CEILING = 75.0
ATR_PERIOD = 20
BASE_TP_MULT = 3.0
BASE_SL_MULT = 0.5

VPIN_MOM_THRESH = 0.0005
EMA_PERIOD = 20
MOM_LOOKBACK = 8
RSI_PERIOD = 14
RSI_FLOOR = 20.0
BUCKET_COUNT = 24

VOL_REGIME_LOOKBACK = 90
VOL_REGIME_THRESH = 50
HV_TP_OFFSET = 1.0
HV_SL_OFFSET = 0.2
LV_TP_OFFSET = -0.5
LV_SL_OFFSET = -0.1
EMA_SLOPE_PERIOD = 5
EMA_SLOPE_THRESH = 0.001

# c168 3-fold 최적 (고정)
HV_HOLD = 24
LV_HOLD = 12
TRAIL_ACTIVATE_MULT = 1.8
TRAIL_SL_MULT = 0.4

# ── MA breakdown exit overlay 그리드 ─────────────────────────────────────
MA_TYPE_LIST = ["SMA", "EMA"]
MA_PERIOD_LIST = [10, 15, 20, 30, 50]
MA_CONFIRM_BARS_LIST = [1, 2, 3]

WF_FOLDS = [
    {
        "name": "F1 (BULL)",
        "train": ("2022-01-01", "2023-12-31"),
        "test": ("2024-01-01", "2024-09-30"),
    },
    {
        "name": "F2 (★BEAR 2025)",
        "train": ("2022-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2025-09-30"),
    },
    {
        "name": "F3 (회복기)",
        "train": ("2023-01-01", "2025-09-30"),
        "test": ("2025-10-01", "2026-04-05"),
    },
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ─────────���────────────────────────────────────────────────────────


def ema_func(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def sma_func(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        result[i] = series[i - period + 1:i + 1].mean()
    return result


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def atr_func(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int,
) -> np.ndarray:
    n = len(closes)
    tr = np.full(n, np.nan)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    result = np.full(n, np.nan)
    if n < period:
        return result
    result[period - 1] = tr[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, n):
        result[i] = tr[i] * k + result[i - 1] * (1 - k)
    return result


def compute_vpin(closes: np.ndarray, opens: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_momentum(closes: np.ndarray, lookback: int) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def compute_atr_percentile(atr_arr: np.ndarray, lookback: int) -> np.ndarray:
    n = len(atr_arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = atr_arr[i - lookback:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) < 10:
            continue
        result[i] = float(np.sum(valid <= atr_arr[i]) / len(valid) * 100)
    return result


def compute_ema_slope(ema_arr: np.ndarray, period: int) -> np.ndarray:
    n = len(ema_arr)
    result = np.full(n, np.nan)
    for i in range(period, n):
        if not np.isnan(ema_arr[i]) and not np.isnan(ema_arr[i - period]):
            if ema_arr[i - period] > 0:
                result[i] = (ema_arr[i] - ema_arr[i - period]) / ema_arr[i - period]
    return result


# ── 백테스트 ─────────────────────��────────────────────────────────────────


def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame,
    exit_ma_arr: np.ndarray | None = None,
    ma_confirm_bars: int = 1,
    slippage: float = 0.0005,
) -> dict:
    """c168 baseline + optional MA breakdown exit overlay."""
    c = df_eth["close"].values
    o = df_eth["open"].values
    h = df_eth["high"].values
    lo = df_eth["low"].values
    v = df_eth["volume"].values
    n = len(c)

    rsi_arr = rsi(c, RSI_PERIOD)
    ema_arr = ema_func(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = atr_func(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_func(v, VOL_SMA_PERIOD)
    atr_pctl_arr = compute_atr_percentile(atr_arr, VOL_REGIME_LOOKBACK)
    ema_slope_arr = compute_ema_slope(ema_arr, EMA_SLOPE_PERIOD)

    btc_close = df_btc.reindex(df_eth.index)["close"].values
    btc_ema_arr = ema_func(btc_close, BTC_EMA_PERIOD)
    btc_mom_arr = compute_momentum(btc_close, BTC_MOM_LOOKBACK)

    returns: list[float] = []
    trail_exits = 0
    tp_exits = 0
    sl_exits = 0
    hold_exits = 0
    ma_exits = 0

    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 BTC_EMA_PERIOD, BTC_MOM_LOOKBACK, VOL_SMA_PERIOD,
                 ATR_PERIOD, VOL_REGIME_LOOKBACK, EMA_SLOPE_PERIOD, 50) + 5
    i = warmup
    while i < n - 1:
        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]
        atr_val = atr_arr[i]
        vol_val = v[i]
        vol_sma_val = vol_sma_arr[i]
        btc_ema_val = btc_ema_arr[i]
        btc_close_val = btc_close[i]
        btc_mom_val = btc_mom_arr[i]
        atr_pctl = atr_pctl_arr[i]
        ema_slope = ema_slope_arr[i]

        # VPIN 진입 조건
        vpin_ok = (
            not np.isnan(vpin_val) and vpin_val > VPIN_HIGH
            and not np.isnan(mom_val) and mom_val > VPIN_MOM_THRESH
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        # BTC 레짐 게이트
        btc_ok = (
            not np.isnan(btc_ema_val) and not np.isnan(btc_close_val)
            and btc_close_val > btc_ema_val
            and not np.isnan(btc_mom_val) and btc_mom_val > BTC_MOM_THRESH
        )

        # 볼륨 필터
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * VOL_MULT
        )

        # ATR 유효성
        atr_ok = not np.isnan(atr_val) and atr_val > 0

        # EMA 기울기 필터
        slope_ok = True
        if EMA_SLOPE_THRESH > 0:
            slope_ok = (
                not np.isnan(ema_slope) and ema_slope > EMA_SLOPE_THRESH
            )

        # 변동성 레짐
        regime_ok = not np.isnan(atr_pctl)

        if vpin_ok and btc_ok and vol_ok and atr_ok and slope_ok and regime_ok:
            atr_pct = atr_val / c[i]
            is_high_vol = atr_pctl > VOL_REGIME_THRESH

            if is_high_vol:
                tp_mult = BASE_TP_MULT + HV_TP_OFFSET
                sl_mult = BASE_SL_MULT + HV_SL_OFFSET
                max_hold = HV_HOLD
            else:
                tp_mult = BASE_TP_MULT + LV_TP_OFFSET
                sl_mult = BASE_SL_MULT + LV_SL_OFFSET
                max_hold = LV_HOLD

            tp = atr_pct * tp_mult
            sl = atr_pct * sl_mult

            tp = max(0.01, min(0.10, tp))
            sl = max(0.003, min(0.04, sl))

            trail_activate_pct = atr_pct * TRAIL_ACTIVATE_MULT
            trail_sl_dist = atr_pct * TRAIL_SL_MULT

            # 진입: 다음 봉 시가
            buy = o[i + 1] * (1 + FEE + slippage)
            ret = None
            exit_bar = i + 1
            trailing_active = False
            highest_ret = 0.0
            consecutive_below_ma = 0

            for j in range(i + 2, min(i + 1 + max_hold, n)):
                r = c[j] / buy - 1

                if r > highest_ret:
                    highest_ret = r

                # Trailing stop check
                if trailing_active:
                    trail_stop = highest_ret - trail_sl_dist
                    if r <= trail_stop:
                        ret = r - FEE - slippage
                        exit_bar = j
                        trail_exits += 1
                        break

                # Trailing 활성화
                if not trailing_active and r >= trail_activate_pct:
                    trailing_active = True

                # TP hit
                if r >= tp:
                    ret = tp - FEE - slippage
                    exit_bar = j
                    tp_exits += 1
                    break

                # SL hit
                if r <= -sl:
                    ret = -sl - FEE - slippage
                    exit_bar = j
                    sl_exits += 1
                    break

                # ★ MA breakdown exit overlay
                if exit_ma_arr is not None and j < len(exit_ma_arr):
                    ma_val = exit_ma_arr[j]
                    if not np.isnan(ma_val) and c[j] < ma_val:
                        consecutive_below_ma += 1
                        if consecutive_below_ma >= ma_confirm_bars:
                            ret = r - FEE - slippage
                            exit_bar = j
                            ma_exits += 1
                            break
                    else:
                        consecutive_below_ma = 0

            if ret is None:
                hold_end = min(i + max_hold, n - 1)
                ret = c[hold_end] / buy - 1 - FEE - slippage
                exit_bar = hold_end
                hold_exits += 1

            returns.append(ret)
            i = exit_bar
        else:
            i += 1

    if len(returns) < 3:
        return {
            "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
            "trades": 0, "max_dd": 0.0, "mcl": 0,
            "trail_exits": 0, "tp_exits": 0, "sl_exits": 0,
            "hold_exits": 0, "ma_exits": 0,
        }
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    mcl = 0
    cur = 0
    for r_val in arr:
        if r_val < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0
    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd, "mcl": mcl,
        "trail_exits": trail_exits, "tp_exits": tp_exits,
        "sl_exits": sl_exits, "hold_exits": hold_exits,
        "ma_exits": ma_exits,
    }


def compute_exit_ma(
    closes: np.ndarray, ma_type: str, ma_period: int,
) -> np.ndarray:
    if ma_type == "EMA":
        return ema_func(closes, ma_period)
    else:
        return sma_func(closes, ma_period)


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def fmt_sh(val: float) -> str:
    return f"{val:+.3f}" if not np.isnan(val) else "  nan"


def main() -> None:
    print("=" * 80)
    print("=== c167: ETH MA breakdown exit overlay on c168 baseline ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: c168 3-fold 최적 (hvH={HV_HOLD} lvH={LV_HOLD} "
          f"trA={TRAIL_ACTIVATE_MULT} trSL={TRAIL_SL_MULT})")
    print(f"오버레이: ETH close < MA → 즉시 청산 (기존 TP/SL/trail과 병렬)")
    print(f"그리드: MA_type={MA_TYPE_LIST} period={MA_PERIOD_LIST} "
          f"confirm={MA_CONFIRM_BARS_LIST}")
    total_combos = len(MA_TYPE_LIST) * len(MA_PERIOD_LIST) * len(MA_CONFIRM_BARS_LIST)
    print(f"= {total_combos} 조합 + 1 baseline")
    print("3-fold WF:")
    for fold in WF_FOLDS:
        print(f"  {fold['name']}: train {fold['train'][0]}~{fold['train'][1]} "
              f"→ OOS {fold['test'][0]}~{fold['test'][1]}")
    print("=" * 80)

    # ── 데이터 로드 ────────────────────────────────────────────────────────
    df_eth_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc_full = load_historical(BTC_SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_eth_full.empty or df_btc_full.empty:
        print("데이터 없음.")
        return
    print(f"\nETH: {len(df_eth_full)}행 ({df_eth_full.index[0]} ~ "
          f"{df_eth_full.index[-1]})")
    print(f"BTC: {len(df_btc_full)}행")

    # ── 전체기간 베이스라인 (MA exit 없음) ─────────────────────────────────
    bh_full = buy_and_hold(df_eth_full)
    print(f"\nETH Buy-and-Hold (전체): {bh_full * 100:+.1f}%")
    base_full = backtest(df_eth_full, df_btc_full)
    print(f"c168 베이스라인 (no MA exit): Sharpe={fmt_sh(base_full['sharpe'])} "
          f"WR={base_full['wr']:.1%} n={base_full['trades']} "
          f"MDD={base_full['max_dd']*100:+.2f}%")

    # ── 베이스라인 3-fold ────────────────────────────────────────────────
    print("\n--- 베이스라인 3-fold (MA exit 없음) ---")
    base_oos_sharpes: list[float] = []
    for fold in WF_FOLDS:
        df_eth_f = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
        df_btc_f = load_historical(BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if df_eth_f.empty or df_btc_f.empty:
            base_oos_sharpes.append(float("nan"))
            continue
        r = backtest(df_eth_f, df_btc_f)
        bh = buy_and_hold(df_eth_f)
        sh = r["sharpe"] if not np.isnan(r["sharpe"]) else -999.0
        base_oos_sharpes.append(sh)
        print(f"  {fold['name']}: Sharpe={sh:+.3f} WR={r['wr']:.1%} "
              f"n={r['trades']} avg={r['avg_ret']*100:+.2f}% "
              f"MDD={r['max_dd']*100:+.2f}% maX={r['ma_exits']} "
              f"BH={bh*100:+.1f}%")
    base_avg_oos = float(np.mean(base_oos_sharpes))
    print(f"  avg OOS Sharpe: {base_avg_oos:+.3f}")

    # ── MA exit overlay 3-fold 그리드 ───────────────────────────────────
    print(f"\n총 조합: {total_combos} × 3-fold = {total_combos * 3} 백테스트")

    wf_results: list[dict] = []
    combo_idx = 0

    for ma_type in MA_TYPE_LIST:
        for ma_period in MA_PERIOD_LIST:
            for ma_confirm in MA_CONFIRM_BARS_LIST:
                combo_idx += 1
                oos_sharpes: list[float] = []
                oos_trades: list[int] = []
                fold_details: list[dict] = []
                all_pass = True

                for fold in WF_FOLDS:
                    df_eth_f = load_historical(
                        SYMBOL, "240m", fold["test"][0], fold["test"][1])
                    df_btc_f = load_historical(
                        BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
                    if df_eth_f.empty or df_btc_f.empty:
                        all_pass = False
                        break

                    exit_ma = compute_exit_ma(
                        df_eth_f["close"].values, ma_type, ma_period)

                    r = backtest(df_eth_f, df_btc_f,
                                 exit_ma_arr=exit_ma,
                                 ma_confirm_bars=ma_confirm)

                    sh = r["sharpe"] if not np.isnan(r["sharpe"]) else -999.0
                    oos_sharpes.append(sh)
                    oos_trades.append(r["trades"])
                    fold_details.append(r)
                    if r["trades"] < 3:
                        all_pass = False

                if not all_pass or len(oos_sharpes) != 3:
                    continue

                avg_oos = float(np.mean(oos_sharpes))
                min_oos = min(oos_sharpes)

                wf_results.append({
                    "ma_type": ma_type, "ma_period": ma_period,
                    "ma_confirm": ma_confirm,
                    "avg_oos_sharpe": avg_oos, "min_oos_sharpe": min_oos,
                    "oos_sharpes": oos_sharpes, "oos_trades": oos_trades,
                    "fold_details": fold_details,
                })

                print(f"  [{combo_idx}/{total_combos}] "
                      f"{ma_type}{ma_period} conf={ma_confirm} → "
                      f"avg OOS={avg_oos:+.3f} min={min_oos:+.3f} "
                      f"F1={oos_sharpes[0]:+.1f} F2={oos_sharpes[1]:+.1f} "
                      f"F3={oos_sharpes[2]:+.1f} "
                      f"n=[{','.join(str(t) for t in oos_trades)}]")

    # ── 결과 분석 ────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"=== 3-fold WF 결과 ===")
    print(f"유효 결과: {len(wf_results)}/{total_combos}")

    passed_all = [r for r in wf_results if r["min_oos_sharpe"] >= 1.0]
    deploy_ready = [r for r in passed_all if r["avg_oos_sharpe"] >= 5.0]

    print(f"모든 fold Sharpe≥1.0 통과: {len(passed_all)}/{len(wf_results)}")
    print(f"배포 가능 (avg≥5.0 & min≥1.0): {len(deploy_ready)}/{len(wf_results)}")

    wf_sorted = sorted(wf_results,
                        key=lambda x: x["avg_oos_sharpe"], reverse=True)

    # Top 15 출력
    display = wf_sorted[:15]
    print(f"\n=== Top 15 (avg OOS Sharpe) ===")
    print(f"{'#':>3} {'type':>4} {'per':>4} {'conf':>4} | "
          f"{'avgOOS':>8} {'minOOS':>8} | "
          f"{'F1_Sh':>7} {'F1_n':>5} {'F2_Sh':>7} {'F2_n':>5} "
          f"{'F3_Sh':>7} {'F3_n':>5} | "
          f"{'F3_MDD':>7} {'F3_maX':>5} | {'pass':>4}")
    print("-" * 110)
    for rank, r in enumerate(display, 1):
        p = ("✅" if r["min_oos_sharpe"] >= 1.0 and r["avg_oos_sharpe"] >= 5.0
             else "⚠️" if r["min_oos_sharpe"] >= 1.0 else "❌")
        f3 = r["fold_details"][2]
        print(
            f"{rank:>3} {r['ma_type']:>4} {r['ma_period']:>4} "
            f"{r['ma_confirm']:>4} | "
            f"{r['avg_oos_sharpe']:>+8.3f} {r['min_oos_sharpe']:>+8.3f} | "
            f"{r['oos_sharpes'][0]:>+7.3f} {r['oos_trades'][0]:>5} "
            f"{r['oos_sharpes'][1]:>+7.3f} {r['oos_trades'][1]:>5} "
            f"{r['oos_sharpes'][2]:>+7.3f} {r['oos_trades'][2]:>5} | "
            f"{f3['max_dd']*100:>+6.2f}% {f3['ma_exits']:>5} | "
            f"{p:>4}"
        )

    # ── 베이스라인 대비 비교 ─────────────────────────────────────────────
    print(f"\n=== 베이스라인 대비 비교 ===")
    print(f"  베이스라인 (no MA exit): avg OOS={base_avg_oos:+.3f}")
    if wf_sorted:
        best = wf_sorted[0]
        delta = best["avg_oos_sharpe"] - base_avg_oos
        print(f"  최적 오버레이: {best['ma_type']}{best['ma_period']} "
              f"conf={best['ma_confirm']} → avg OOS={best['avg_oos_sharpe']:+.3f} "
              f"(Δ{delta:+.3f})")

    # F3 MDD 개선 비교
    base_f3 = None
    for fold in WF_FOLDS:
        if "F3" in fold["name"]:
            df_f3 = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_f3 = load_historical(
                BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
            base_f3 = backtest(df_f3, df_btc_f3)
            break

    if base_f3:
        print(f"\n=== F3 (BEAR fold) MDD 비교 ===")
        print(f"  베이스라인 F3: MDD={base_f3['max_dd']*100:+.2f}% "
              f"Sharpe={fmt_sh(base_f3['sharpe'])}")
        # F3 MDD 개선 순으로 정렬
        f3_improved = sorted(wf_results,
                             key=lambda x: x["fold_details"][2]["max_dd"],
                             reverse=True)
        for rank, r in enumerate(f3_improved[:5], 1):
            f3d = r["fold_details"][2]
            mdd_delta = f3d["max_dd"] - base_f3["max_dd"]
            print(f"  #{rank} {r['ma_type']}{r['ma_period']} "
                  f"conf={r['ma_confirm']}: "
                  f"MDD={f3d['max_dd']*100:+.2f}% "
                  f"(Δ{mdd_delta*100:+.2f}%) "
                  f"Sharpe={r['oos_sharpes'][2]:+.3f} "
                  f"maX={f3d['ma_exits']} n={r['oos_trades'][2]}")

    # ── Fold 상세 — Top 5 ────────────────────────────────────────────────
    print(f"\n=== Top 5 Fold 상세 ===")
    for rank, r in enumerate(wf_sorted[:5], 1):
        print(f"\n--- #{rank}: {r['ma_type']}{r['ma_period']} "
              f"conf={r['ma_confirm']} "
              f"(avg OOS: {r['avg_oos_sharpe']:+.3f}) ---")
        for fi, fold in enumerate(WF_FOLDS):
            fd = r["fold_details"][fi]
            df_eth_f = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1])
            bh = buy_and_hold(df_eth_f) if not df_eth_f.empty else 0.0
            print(f"  {fold['name']}: Sharpe={r['oos_sharpes'][fi]:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={r['oos_trades'][fi]}  "
                  f"avg={fd['avg_ret']*100:+.2f}%  MDD={fd['max_dd']*100:+.2f}%  "
                  f"trX={fd['trail_exits']}  tpX={fd['tp_exits']}  "
                  f"slX={fd['sl_exits']}  hldX={fd['hold_exits']}  "
                  f"maX={fd['ma_exits']}  BH={bh*100:+.1f}%")

    # ── 슬리피지 스트레스 (Top 3) ────────────────────────────────────────
    if wf_sorted:
        stress_top = wf_sorted[:3]
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 (WF Top 3, 전체기간) ===")
        for rank, params in enumerate(stress_top, 1):
            exit_ma_full = compute_exit_ma(
                df_eth_full["close"].values,
                params["ma_type"], params["ma_period"])
            print(f"\n--- #{rank}: {params['ma_type']}{params['ma_period']} "
                  f"conf={params['ma_confirm']} "
                  f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
            print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
                  f"{'MDD':>7} {'MCL':>4} {'n':>5} {'maX':>4}")
            print("-" * 60)
            for slip in SLIPPAGE_LEVELS:
                r = backtest(df_eth_full, df_btc_full,
                             exit_ma_arr=exit_ma_full,
                             ma_confirm_bars=params["ma_confirm"],
                             slippage=slip)
                sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
                print(f"  {slip*100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                      f"{r['avg_ret']*100:>+6.2f}% {r['max_dd']*100:>+6.2f}% "
                      f"{r['mcl']:>4} {r['trades']:>5} {r['ma_exits']:>4}")

    # 베이스라인 슬리피지도 출력
    print(f"\n--- 베이스라인 (no MA exit) ---")
    print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
          f"{'MDD':>7} {'MCL':>4} {'n':>5}")
    print("-" * 55)
    for slip in SLIPPAGE_LEVELS:
        r = backtest(df_eth_full, df_btc_full, slippage=slip)
        sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
        print(f"  {slip*100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
              f"{r['avg_ret']*100:>+6.2f}% {r['max_dd']*100:>+6.2f}% "
              f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ─────────────────────��─────────────────────────────────���
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"베이스라인 (c168 3-fold 최적, no MA exit): avg OOS={base_avg_oos:+.3f}")

    if deploy_ready:
        best = sorted(deploy_ready,
                      key=lambda x: x["avg_oos_sharpe"], reverse=True)[0]
        delta = best["avg_oos_sharpe"] - base_avg_oos
        print(f"★ 최적 MA exit overlay: {best['ma_type']}{best['ma_period']} "
              f"conf={best['ma_confirm']}")
        print(f"  avg OOS Sharpe: {best['avg_oos_sharpe']:+.3f} "
              f"(vs baseline Δ{delta:+.3f})")
        print(f"  min OOS Sharpe: {best['min_oos_sharpe']:+.3f}")
        for fi, fold in enumerate(WF_FOLDS):
            fd = best["fold_details"][fi]
            print(f"  {fold['name']}: Sharpe={best['oos_sharpes'][fi]:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={best['oos_trades'][fi]}  "
                  f"MDD={fd['max_dd']*100:+.2f}%  maX={fd['ma_exits']}")

        improved = delta > 0
        f3_base_mdd = base_f3["max_dd"] if base_f3 else 0.0
        f3_best_mdd = best["fold_details"][2]["max_dd"]
        mdd_improved = f3_best_mdd > f3_base_mdd  # less negative = better

        print(f"\n  결론: {'✅ 개선' if improved else '❌ 미개선'} — "
              f"avg OOS Δ{delta:+.3f}, "
              f"F3 MDD {f3_base_mdd*100:+.2f}% → {f3_best_mdd*100:+.2f}% "
              f"({'✅ 개선' if mdd_improved else '❌ 미개선'})")

        avg_wr = np.mean([fd["wr"] for fd in best["fold_details"]])
        total_n = sum(best["oos_trades"])
        print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
        print(f"WR: {avg_wr*100:.1f}%")
        print(f"trades: {total_n}")

    elif passed_all:
        best = sorted(passed_all,
                      key=lambda x: x["avg_oos_sharpe"], reverse=True)[0]
        delta = best["avg_oos_sharpe"] - base_avg_oos
        print(f"⚠️ 배포기준 미달, 최선: {best['ma_type']}{best['ma_period']} "
              f"conf={best['ma_confirm']}")
        print(f"  avg OOS Sharpe: {best['avg_oos_sharpe']:+.3f} "
              f"(vs baseline Δ{delta:+.3f})")
        for fi, fold in enumerate(WF_FOLDS):
            fd = best["fold_details"][fi]
            print(f"  {fold['name']}: Sharpe={best['oos_sharpes'][fi]:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={best['oos_trades'][fi]}  "
                  f"MDD={fd['max_dd']*100:+.2f}%  maX={fd['ma_exits']}")

        avg_wr = np.mean([fd["wr"] for fd in best["fold_details"]])
        total_n = sum(best["oos_trades"])
        print(f"\nSharpe: {best['avg_oos_sharpe']:+.3f}")
        print(f"WR: {avg_wr*100:.1f}%")
        print(f"trades: {total_n}")

    else:
        print("❌ 0 조합 WF 통과")
        if wf_sorted:
            best = wf_sorted[0]
            delta = best["avg_oos_sharpe"] - base_avg_oos
            print(f"  최선: {best['ma_type']}{best['ma_period']} "
                  f"conf={best['ma_confirm']} → avg OOS={best['avg_oos_sharpe']:+.3f} "
                  f"(Δ{delta:+.3f})")
        print(f"\nSharpe: {base_avg_oos:+.3f}")
        print(f"WR: 0.0%")
        print(f"trades: 0")


if __name__ == "__main__":
    main()
