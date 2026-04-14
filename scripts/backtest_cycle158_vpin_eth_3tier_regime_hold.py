"""
vpin_eth 사이클 158 — 3단계 변동성 레짐 + 레짐별 적응형 보유기간
- 기반: cycle 154 최적 vLB=60 vTH=40 hvTP=+1.0 hvSL=+0.2 lvTP=+0.0 lvSL=-0.2
         sP=10 sTH=0.003 (기반: ATR=20 baseTpM=3.0 baseSlM=0.5)
         avg OOS Sharpe: +13.686, WR=41.1%, n=48
- 개선 방향:
  1) 2단계(high/low) → 3단계(high/mid/low) 레짐 세분화
     → mid 구간에 별도 TP/SL 오프셋 → 더 정밀한 변동성 적응
  2) 레짐별 적응형 보유기간(max_hold)
     → high_vol: 짧은 보유(변동성 소진 전 이익실현)
     → low_vol: 긴 보유(작은 움직임 누적 대기)
  3) 거래수(48건) 확보: c155 교훈 — 필터 과다 = 거래수 파괴
     → 기존 진입 조건 유지, 청산(exit) 측면만 개선
- 탐색: 3단계 레짐 경계, mid TP/SL 오프셋, 레짐별 hold 기간
- 2-fold walkforward + 슬리피지 스트레스
- 진입: next_bar open
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005

# ── 고정: cycle 151/154 검증 완료 파라미터 ──────────────────────────────────
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

# ── c154 최적값 고정 ────────────────────────────────────────────────────────
VOL_REGIME_LB = 60           # ATR percentile lookback
EMA_SLOPE_PERIOD = 10
EMA_SLOPE_THRESH = 0.003

# ── 탐색 그리드: 3단계 레짐 ─────────────────────────────────────────────────
# low: pctl ≤ low_th, mid: low_th < pctl ≤ high_th, high: pctl > high_th
VOL_LOW_TH_LIST = [25, 30, 35, 40]          # low/mid 경계
VOL_HIGH_TH_LIST = [55, 60, 65, 70, 75]     # mid/high 경계

# high_vol TP/SL 오프셋 (c154 최적 근방 확장)
HV_TP_OFFSET_LIST = [0.5, 1.0, 1.5, 2.0]
HV_SL_OFFSET_LIST = [0.1, 0.2, 0.3]

# mid_vol TP/SL 오프셋 (새 탐색 — base 근처)
MV_TP_OFFSET_LIST = [0.0, 0.3, 0.5]
MV_SL_OFFSET_LIST = [0.0, 0.1]

# low_vol TP/SL 오프셋 (c154 최적 근방)
LV_TP_OFFSET_LIST = [-0.5, 0.0, 0.5]
LV_SL_OFFSET_LIST = [-0.2, -0.1, 0.0]

# 레짐별 적응형 보유기간
BASE_HOLD = 18  # c154 기준
HV_HOLD_LIST = [12, 15, 18]        # high_vol: 짧게
MV_HOLD_LIST = [18, 21]            # mid_vol: 기준
LV_HOLD_LIST = [18, 24, 30]        # low_vol: 길게

# ── Walkforward 기간 ─────────────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

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
    for i in range(period - 1, len(series)):
        result[i] = series[i - period + 1:i + 1].mean()
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


def atr_calc(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
             period: int) -> np.ndarray:
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


# ── 백테스트 (3단계 레짐 + 적응형 보유기간) ─────────────────────────────────

def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame,
    vol_low_th: int,
    vol_high_th: int,
    hv_tp_off: float,
    hv_sl_off: float,
    mv_tp_off: float,
    mv_sl_off: float,
    lv_tp_off: float,
    lv_sl_off: float,
    hv_hold: int,
    mv_hold: int,
    lv_hold: int,
    slippage: float = 0.0005,
) -> dict:
    c = df_eth["close"].values
    o = df_eth["open"].values
    h = df_eth["high"].values
    lo = df_eth["low"].values
    v = df_eth["volume"].values
    n = len(c)

    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    atr_arr = atr_calc(h, lo, c, ATR_PERIOD)
    vol_sma_arr = sma_calc(v, VOL_SMA_PERIOD)
    atr_pctl_arr = compute_atr_percentile(atr_arr, VOL_REGIME_LB)
    ema_slope_arr = compute_ema_slope(ema_arr, EMA_SLOPE_PERIOD)

    btc_close = df_btc.reindex(df_eth.index)["close"].values
    btc_ema_arr = ema_calc(btc_close, BTC_EMA_PERIOD)
    btc_mom_arr = compute_momentum(btc_close, BTC_MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 BTC_EMA_PERIOD, BTC_MOM_LOOKBACK, VOL_SMA_PERIOD,
                 ATR_PERIOD, VOL_REGIME_LB, EMA_SLOPE_PERIOD) + 5
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
        slope_ok = (
            not np.isnan(ema_slope) and ema_slope > EMA_SLOPE_THRESH
        )

        # 레짐 유효성
        regime_ok = not np.isnan(atr_pctl)

        if vpin_ok and btc_ok and vol_ok and atr_ok and slope_ok and regime_ok:
            atr_pct = atr_val / c[i]

            # ★ 3단계 변동성 레짐 분류
            if atr_pctl > vol_high_th:
                # high volatility
                tp_mult = BASE_TP_MULT + hv_tp_off
                sl_mult = BASE_SL_MULT + hv_sl_off
                max_hold = hv_hold
            elif atr_pctl > vol_low_th:
                # mid volatility
                tp_mult = BASE_TP_MULT + mv_tp_off
                sl_mult = BASE_SL_MULT + mv_sl_off
                max_hold = mv_hold
            else:
                # low volatility
                tp_mult = BASE_TP_MULT + lv_tp_off
                sl_mult = BASE_SL_MULT + lv_sl_off
                max_hold = lv_hold

            tp = atr_pct * tp_mult
            sl = atr_pct * sl_mult

            # 안전장치: TP 1%~10%, SL 0.3%~4%
            tp = max(0.01, min(0.10, tp))
            sl = max(0.003, min(0.04, sl))

            buy = o[i + 1] * (1 + FEE + slippage)
            for j in range(i + 2, min(i + 1 + max_hold, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE - slippage)
                    i = j
                    break
                if ret <= -sl:
                    returns.append(-sl - FEE - slippage)
                    i = j
                    break
            else:
                hold_end = min(i + max_hold, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE - slippage)
                i = hold_end
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


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def main() -> None:
    print("=" * 80)
    print("=== vpin_eth 사이클 158 — 3단계 변동성 레짐 + 적응형 보유기간 ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: c154 최적 vLB=60 sTH=0.003 sP=10")
    print(f"  ATR=20 baseTpM=3.0 baseSlM=0.5 VH=0.5 RSIc=75 bTH=0.02 hold=18")
    print(f"탐색: 3단계 레짐 경계, mid TP/SL 오프셋, 레짐별 보유기간")
    print(f"목표: avg OOS Sharpe > +13.686 (c154), MDD ≤ -8%")
    print("=" * 80)

    # ── 데이터 로드 ────────────────────────────────────────────────────────────
    df_eth = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC_SYMBOL, "240m", "2022-01-01", "2026-12-31")
    if df_eth.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"\nETH: {len(df_eth)}행 ({df_eth.index[0]} ~ {df_eth.index[-1]})")
    print(f"BTC: {len(df_btc)}행 ({df_btc.index[0]} ~ {df_btc.index[-1]})")
    bh = buy_and_hold(df_eth)
    print(f"ETH Buy-and-Hold: {bh * 100:+.1f}%")

    # ── Phase 0: c154 베이스라인 (2단계 레짐, 고정 hold=18) ──────────────────
    print(f"\n--- c154 베이스라인 (2단계: vTH=40, hvTP=+1.0 hvSL=+0.2 "
          f"lvTP=+0.0 lvSL=-0.2, hold=18) ---")
    # 2단계를 3단계로 재현: low_th=0 (low 미사용), high_th=40
    base = backtest(df_eth, df_btc,
                    vol_low_th=0, vol_high_th=40,
                    hv_tp_off=1.0, hv_sl_off=0.2,
                    mv_tp_off=0.0, mv_sl_off=-0.2,  # mid = c154의 low
                    lv_tp_off=0.0, lv_sl_off=-0.2,
                    hv_hold=18, mv_hold=18, lv_hold=18)
    print(f"  Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"n={base['trades']}")

    # ── Phase 1: 전체기간 그리드 서치 ──────────────────────────────────────────
    combos = list(product(
        VOL_LOW_TH_LIST, VOL_HIGH_TH_LIST,
        HV_TP_OFFSET_LIST, HV_SL_OFFSET_LIST,
        MV_TP_OFFSET_LIST, MV_SL_OFFSET_LIST,
        LV_TP_OFFSET_LIST, LV_SL_OFFSET_LIST,
        HV_HOLD_LIST, MV_HOLD_LIST, LV_HOLD_LIST,
    ))

    # low_th >= high_th 조합 제거
    combos = [(lt, ht, htp, hsl, mtp, msl, ltp, lsl, hh, mh, lh)
              for lt, ht, htp, hsl, mtp, msl, ltp, lsl, hh, mh, lh in combos
              if lt + 15 <= ht]  # 최소 15pt 간격

    print(f"\n총 조합: {len(combos)}개")
    if len(combos) > 50000:
        print("조합 과다 — 랜덤 샘플링 50000개")
        rng = np.random.default_rng(42)
        idx = rng.choice(len(combos), size=50000, replace=False)
        combos = [combos[i] for i in idx]
        print(f"샘플: {len(combos)}개")

    results: list[dict] = []
    for idx, (lt, ht, htp, hsl, mtp, msl, ltp, lsl, hh, mh, lh) in enumerate(combos):
        if idx % 2000 == 0 and idx > 0:
            print(f"  진행: {idx}/{len(combos)}")

        # TP/SL 배수 유효성 검사
        if BASE_TP_MULT + ltp < 1.0 or BASE_SL_MULT + lsl < 0.1:
            continue
        if BASE_TP_MULT + mtp < 1.5 or BASE_SL_MULT + msl < 0.2:
            continue

        r = backtest(df_eth, df_btc, lt, ht, htp, hsl, mtp, msl,
                     ltp, lsl, hh, mh, lh)
        results.append({
            "vol_low_th": lt, "vol_high_th": ht,
            "hv_tp": htp, "hv_sl": hsl,
            "mv_tp": mtp, "mv_sl": msl,
            "lv_tp": ltp, "lv_sl": lsl,
            "hv_hold": hh, "mv_hold": mh, "lv_hold": lh,
            **r,
        })

    valid = [r for r in results
             if r["trades"] >= 30
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 5.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥30, Sharpe≥5.0): {len(valid)}/{len(results)}")

    if not valid:
        # 완화 기준 재시도
        valid = [r for r in results
                 if r["trades"] >= 20
                 and not np.isnan(r["sharpe"])
                 and r["sharpe"] >= 3.0]
        valid.sort(key=lambda x: x["sharpe"], reverse=True)
        print(f"완화 조합 (n≥20, Sharpe≥3.0): {len(valid)}/{len(results)}")

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    print(f"\n=== 전체기간 Top 15 (Sharpe 기준) ===")
    hdr = (f"{'lTH':>4} {'hTH':>4} {'hvTP':>5} {'hvSL':>5} "
           f"{'mvTP':>5} {'mvSL':>5} {'lvTP':>5} {'lvSL':>5} "
           f"{'hH':>3} {'mH':>3} {'lH':>3} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid[:15]:
        print(
            f"{r['vol_low_th']:>4} {r['vol_high_th']:>4} "
            f"{r['hv_tp']:>+5.1f} {r['hv_sl']:>+5.1f} "
            f"{r['mv_tp']:>+5.1f} {r['mv_sl']:>+5.1f} "
            f"{r['lv_tp']:>+5.1f} {r['lv_sl']:>+5.1f} "
            f"{r['hv_hold']:>3} {r['mv_hold']:>3} {r['lv_hold']:>3} | "
            f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} "
            f"{r['avg_ret'] * 100:>+6.2f}% "
            f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} {r['trades']:>5}"
        )

    # ── Phase 2: OOS Walk-Forward (Top 15 고유) ──────────────────────────────
    seen = set()
    unique_top: list[dict] = []
    for r in valid:
        key = (r["vol_low_th"], r["vol_high_th"],
               r["hv_tp"], r["hv_sl"], r["mv_tp"], r["mv_sl"],
               r["lv_tp"], r["lv_sl"], r["hv_hold"], r["mv_hold"], r["lv_hold"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 15:
            break

    print(f"\n{'=' * 80}")
    print(f"=== OOS Walk-Forward 검증 (Top {len(unique_top)}, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        lt = params["vol_low_th"]
        ht = params["vol_high_th"]
        htp = params["hv_tp"]
        hsl_ = params["hv_sl"]
        mtp = params["mv_tp"]
        msl_ = params["mv_sl"]
        ltp = params["lv_tp"]
        lsl_ = params["lv_sl"]
        hh = params["hv_hold"]
        mh = params["mv_hold"]
        lh = params["lv_hold"]

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_eth_test = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_test = load_historical(
                BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
            if df_eth_test.empty or df_btc_test.empty:
                continue
            r = backtest(df_eth_test, df_btc_test, lt, ht, htp, hsl_,
                         mtp, msl_, ltp, lsl_, hh, mh, lh)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)
            bh_fold = buy_and_hold(df_eth_test)
            print(f"  #{rank} Fold {fold_i + 1} [{fold['test'][0]}~{fold['test'][1]}]: "
                  f"Sharpe={sh:+.3f}  WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%  "
                  f"BH={bh_fold * 100:+.1f}%")

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            min_n = min(oos_trades) if oos_trades else 0
            print(f"  #{rank}: lTH={lt} hTH={ht} hvTP={htp:+.1f} hvSL={hsl_:+.1f} "
                  f"mvTP={mtp:+.1f} mvSL={msl_:+.1f} "
                  f"lvTP={ltp:+.1f} lvSL={lsl_:+.1f} "
                  f"hH={hh} mH={mh} lH={lh} | "
                  f"avg_OOS={avg_oos:+.3f} min={min_oos:+.3f} min_n={min_n}")
            wf_results.append({
                **params,
                "train_sharpe": params["sharpe"],
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "fold_details": fold_details,
            })

    if not wf_results:
        print("\nWF 검증 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # ── Phase 3: 슬리피지 스트레스 (WF Top 3) ──────────────────────────────
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                        reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 3) ===")

    for rank, params in enumerate(wf_top3, 1):
        lt = params["vol_low_th"]
        ht = params["vol_high_th"]
        htp = params["hv_tp"]
        hsl_ = params["hv_sl"]
        mtp = params["mv_tp"]
        msl_ = params["mv_sl"]
        ltp = params["lv_tp"]
        lsl_ = params["lv_sl"]
        hh = params["hv_hold"]
        mh = params["mv_hold"]
        lh = params["lv_hold"]
        print(f"\n--- #{rank}: lTH={lt} hTH={ht} hvTP={htp:+.1f} hvSL={hsl_:+.1f} "
              f"mvTP={mtp:+.1f} mvSL={msl_:+.1f} "
              f"lvTP={ltp:+.1f} lvSL={lsl_:+.1f} "
              f"hH={hh} mH={mh} lH={lh} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_eth, df_btc, lt, ht, htp, hsl_, mtp, msl_,
                         ltp, lsl_, hh, mh, lh, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: lTH={best_wf['vol_low_th']} hTH={best_wf['vol_high_th']} "
          f"hvTP={best_wf['hv_tp']:+.1f} hvSL={best_wf['hv_sl']:+.1f} "
          f"mvTP={best_wf['mv_tp']:+.1f} mvSL={best_wf['mv_sl']:+.1f} "
          f"lvTP={best_wf['lv_tp']:+.1f} lvSL={best_wf['lv_sl']:+.1f} "
          f"hH={best_wf['hv_hold']} mH={best_wf['mv_hold']} "
          f"lH={best_wf['lv_hold']}")
    print(f"  (기반: ATR={ATR_PERIOD} baseTpM={BASE_TP_MULT} baseSlM={BASE_SL_MULT} "
          f"VH={VPIN_HIGH} RSIc={RSI_CEILING} bTH={BTC_MOM_THRESH} "
          f"vLB={VOL_REGIME_LB} sP={EMA_SLOPE_PERIOD} sTH={EMA_SLOPE_THRESH})")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  MDD={fd['max_dd'] * 100:+.2f}%")

    print(f"\n  vs c154 베이스라인 (2단계 레짐, hold=18): "
          f"Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")

    avg_wr = float(np.mean([fd["wr"] for fd in best_wf["fold_details"]]))
    total_n = sum(best_wf["oos_trades"])
    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
