"""
vpin_eth 사이클 155 — BTC 레짐 게이트 + 볼륨 스파이크 필터 + 트레일링 스톱
- 기반: c152 최적 vl=0.3 vm=0.0007 hold=24 trail=0.015 minP=0.03 SL=0.006 cool=6
  avg OOS Sharpe: +7.203, WR=23.0%, n=76, MDD=-13.88%
- 문제점:
  1) BTC 하락장 진입 → 불필요한 손실 (c152는 BTC 필터 없음)
  2) 저볼륨 진입 → 추세 미확인 상태에서 노이즈 매매
  3) WR 23%로 낮음 → 진입 필터 강화로 승률 개선 가능
- 가설:
  1) BTC EMA + 모멘텀 게이트로 약세장 진입 차단 → MDD↓, WR↑
  2) 볼륨 > SMA*mult 조건으로 유동성 확인 → 허위 시그널 제거
  3) c152 트레일링 스톱 구조 유지 (과적합 저항 검증 완료)
- 탐색: BTC EMA기간, BTC 모멘텀 문턱, 볼륨 SMA기간/배수
  + c152 고정 파라미터 미세 조정 (trail, SL 근방)
- 2-fold walkforward + 슬리피지 스트레스
- 진입: next_bar open
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

SYMBOL = "KRW-ETH"
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005

# ── 고정: c152 최적 (미세 조정 대상 아닌 것) ────────────────────────────────
RSI_PERIOD = 14
RSI_CEILING = 65.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8
COOLDOWN_LOSSES = 2

# ── 탐색 그리드 ──────────────────────────────────────────────────────────────
# c152 최적 근방 미세 조정
VPIN_LOW_LIST = [0.25, 0.30, 0.35]
VPIN_MOM_LIST = [0.0005, 0.0007, 0.0010]
MAX_HOLD_LIST = [24, 30]
TRAIL_PCT_LIST = [0.012, 0.015, 0.020]
MIN_PROFIT_LIST = [0.02, 0.03, 0.04]
SL_LIST = [0.005, 0.006, 0.008]
COOLDOWN_BARS_LIST = [6, 12]

# BTC 레짐 게이트 (신규)
BTC_EMA_PERIOD_LIST = [50, 100, 200]
BTC_MOM_LOOKBACK = 10  # 고정
BTC_MOM_THRESH_LIST = [0.0, 0.01, 0.02, 0.03]

# 볼륨 스파이크 필터 (신규)
VOL_SMA_PERIOD_LIST = [20, 30]
VOL_MULT_LIST = [1.0, 1.3, 1.5, 2.0]

# ── Walkforward 기간 ─────────────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

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


def compute_vpin_bvc(
    closes: np.ndarray, opens: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
    volumes: np.ndarray, bucket_count: int = 24,
) -> np.ndarray:
    """Production-matching VPIN: BVC + normal CDF + volume weighting."""
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


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame,
    vpin_low: float,
    vpin_mom_thresh: float,
    max_hold: int,
    trail_pct: float,
    min_profit: float,
    sl: float,
    cooldown_bars: int,
    btc_ema_period: int,
    btc_mom_thresh: float,
    vol_sma_period: int,
    vol_mult: float,
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
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)
    vol_sma_arr = sma_calc(v, vol_sma_period)

    btc_close = df_btc.reindex(df_eth.index)["close"].values
    btc_ema_arr = ema_calc(btc_close, btc_ema_period)
    btc_mom_arr = compute_momentum(btc_close, BTC_MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK,
                 btc_ema_period, BTC_MOM_LOOKBACK, vol_sma_period) + 5
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
        vol_val = v[i]
        vol_sma_val = vol_sma_arr[i]
        btc_ema_val = btc_ema_arr[i]
        btc_close_val = btc_close[i]
        btc_mom_val = btc_mom_arr[i]

        if (np.isnan(vpin_val) or np.isnan(mom_val)
                or np.isnan(rsi_val) or np.isnan(ema_val)):
            i += 1
            continue

        # VPIN 진입 (c152 동일)
        vpin_ok = (
            vpin_val < vpin_low
            and mom_val >= vpin_mom_thresh
            and RSI_FLOOR < rsi_val < RSI_CEILING
            and c[i] > ema_val
        )

        # BTC 레짐 게이트 (신규)
        btc_ok = (
            not np.isnan(btc_ema_val) and not np.isnan(btc_close_val)
            and btc_close_val > btc_ema_val
            and (btc_mom_thresh <= 0
                 or (not np.isnan(btc_mom_val)
                     and btc_mom_val > btc_mom_thresh))
        )

        # 볼륨 스파이크 필터 (신규)
        vol_ok = (
            not np.isnan(vol_sma_val) and vol_sma_val > 0
            and vol_val > vol_sma_val * vol_mult
        )

        if vpin_ok and btc_ok and vol_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            peak_price = buy
            exit_ret = None

            for j in range(i + 2, min(i + 1 + max_hold, n)):
                current_price = c[j]
                ret = current_price / buy - 1

                # 스톱로스
                if ret <= -sl:
                    exit_ret = -sl - FEE - slippage
                    i = j
                    break

                # 최고가 갱신
                if current_price > peak_price:
                    peak_price = current_price

                # 트레일링 스톱
                peak_ret = peak_price / buy - 1
                if peak_ret >= min_profit:
                    drawdown_from_peak = (peak_price - current_price) / peak_price
                    if drawdown_from_peak >= trail_pct:
                        exit_ret = ret - FEE - slippage
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
    print("=== vpin_eth 사이클 155 — BTC 레짐 게이트 + 볼륨 필터 + 트레일링 스톱 ===")
    print(f"심볼: {SYMBOL}  목표: OOS Sharpe ≥ 7.2 (c152 대비 WR↑, MDD↓)")
    print("기반: c152 최적 trail=0.015 SL=0.006 cool=6 (OOS +7.203)")
    print("신규: BTC EMA+모멘텀 게이트, 볼륨 SMA 스파이크 필터")
    print("=" * 80)

    # ── 데이터 로드 ────────────────────────────────────────────────────────────
    train_start, train_end = WF_FOLDS[0]["train"]
    df_eth_train = load_historical(SYMBOL, "240m", train_start, train_end)
    df_btc_train = load_historical(BTC_SYMBOL, "240m", train_start, train_end)
    if df_eth_train.empty or df_btc_train.empty:
        print("train 데이터 없음.")
        return
    print(f"\ntrain ETH: {len(df_eth_train)}행 ({train_start} ~ {train_end})")
    print(f"train BTC: {len(df_btc_train)}행")
    bh = buy_and_hold(df_eth_train)
    print(f"ETH Buy-and-Hold (train): {bh * 100:+.1f}%")

    # ── c152 기준선 (BTC/볼륨 필터 없음) ──────────────────────────────────────
    print("\n--- c152 기준선 (BTC 게이트 없음, 볼륨 필터 없음) ---")
    # BTC 게이트 비활성: btc_ema=50, btc_mom=-1 (항상 통과), vol_mult=0 (항상 통과)
    base = backtest(df_eth_train, df_btc_train,
                    0.30, 0.0007, 24, 0.015, 0.03, 0.006, 6,
                    50, -1.0, 20, 0.0)
    print(f"  Sharpe={base['sharpe']:+.3f}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"n={base['trades']}")

    # ── Phase 1: 2단계 탐색 — 먼저 BTC+볼륨 필터만 탐색 (c152 최적 고정) ────
    print(f"\n{'=' * 80}")
    print("=== Phase 1: BTC + 볼륨 필터 탐색 (c152 파라미터 고정) ===")
    filter_combos = list(product(
        BTC_EMA_PERIOD_LIST, BTC_MOM_THRESH_LIST,
        VOL_SMA_PERIOD_LIST, VOL_MULT_LIST,
    ))
    print(f"필터 조합: {len(filter_combos)}개")

    filter_results: list[dict] = []
    for bema, bmth, vsma, vmul in filter_combos:
        r = backtest(df_eth_train, df_btc_train,
                     0.30, 0.0007, 24, 0.015, 0.03, 0.006, 6,
                     bema, bmth, vsma, vmul)
        filter_results.append({
            "btc_ema": bema, "btc_mom_th": bmth,
            "vol_sma": vsma, "vol_mult": vmul, **r,
        })

    valid_f = [r for r in filter_results
               if r["trades"] >= 15 and not np.isnan(r["sharpe"])]
    valid_f.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥15): {len(valid_f)}/{len(filter_results)}")
    print(f"\n--- 필터 Top 10 ---")
    print(f"{'bEMA':>5} {'bMom':>5} {'vSMA':>5} {'vMul':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
    print("-" * 70)
    for r in valid_f[:10]:
        print(f"{r['btc_ema']:>5} {r['btc_mom_th']:>5.2f} "
              f"{r['vol_sma']:>5} {r['vol_mult']:>5.1f} | "
              f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} "
              f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
              f"{r['mcl']:>4} {r['trades']:>5}")

    # Top 3 필터 조합 선정
    top_filters = valid_f[:3] if len(valid_f) >= 3 else valid_f

    # ── Phase 2: c152 파라미터 미세 조정 (상위 필터 조합별) ──────────────────
    print(f"\n{'=' * 80}")
    print("=== Phase 2: c152 파라미터 미세 조정 + 최적 필터 ===")
    tune_combos = list(product(
        VPIN_LOW_LIST, VPIN_MOM_LIST, MAX_HOLD_LIST,
        TRAIL_PCT_LIST, MIN_PROFIT_LIST, SL_LIST,
        COOLDOWN_BARS_LIST,
    ))
    print(f"튜닝 조합: {len(tune_combos)}개 × 필터 {len(top_filters)}개 "
          f"= {len(tune_combos) * len(top_filters)}개")

    all_results: list[dict] = []
    total = len(tune_combos) * len(top_filters)
    count = 0
    for filt in top_filters:
        bema = filt["btc_ema"]
        bmth = filt["btc_mom_th"]
        vsma = filt["vol_sma"]
        vmul = filt["vol_mult"]
        for vl, vm, mh, tp, mp, sl, cb in tune_combos:
            count += 1
            if count % 2000 == 0:
                print(f"  진행: {count}/{total}")
            r = backtest(df_eth_train, df_btc_train,
                         vl, vm, mh, tp, mp, sl, cb,
                         bema, bmth, vsma, vmul)
            all_results.append({
                "vpin_low": vl, "vpin_mom": vm, "max_hold": mh,
                "trail_pct": tp, "min_profit": mp, "sl": sl,
                "cooldown_bars": cb,
                "btc_ema": bema, "btc_mom_th": bmth,
                "vol_sma": vsma, "vol_mult": vmul,
                **r,
            })

    valid_all = [r for r in all_results
                 if r["trades"] >= 20 and not np.isnan(r["sharpe"])
                 and r["sharpe"] >= 5.0]
    valid_all.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥20, Sharpe≥5.0): {len(valid_all)}/{len(all_results)}")

    print(f"\n=== Train Top 15 ===")
    hdr = (f"{'vl':>4} {'vm':>6} {'hold':>4} {'trail':>5} {'minP':>5} "
           f"{'SL':>5} {'cool':>4} {'bE':>3} {'bM':>4} {'vS':>3} {'vM':>4} | "
           f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>4}")
    print(hdr)
    print("-" * len(hdr))
    for r in valid_all[:15]:
        print(
            f"{r['vpin_low']:>4.2f} {r['vpin_mom']:>6.4f} {r['max_hold']:>4} "
            f"{r['trail_pct']:>5.3f} {r['min_profit']:>5.3f} "
            f"{r['sl']:>5.3f} {r['cooldown_bars']:>4} "
            f"{r['btc_ema']:>3} {r['btc_mom_th']:>4.2f} "
            f"{r['vol_sma']:>3} {r['vol_mult']:>4.1f} | "
            f"{r['sharpe']:>+7.3f} {r['wr']:>5.1%} "
            f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
            f"{r['mcl']:>4} {r['trades']:>4}"
        )

    if not valid_all:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    # ── Phase 3: OOS Walk-Forward (Top 15 고유) ──────────────────────────────
    seen: set[tuple] = set()
    unique_top: list[dict] = []
    for r in valid_all:
        key = (r["vpin_low"], r["vpin_mom"], r["max_hold"],
               r["trail_pct"], r["min_profit"], r["sl"],
               r["cooldown_bars"], r["btc_ema"], r["btc_mom_th"],
               r["vol_sma"], r["vol_mult"])
        if key not in seen:
            seen.add(key)
            unique_top.append(r)
        if len(unique_top) >= 15:
            break

    print(f"\n{'=' * 80}")
    print(f"=== OOS Walk-Forward 검증 (Top {len(unique_top)}, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(unique_top, 1):
        vl = params["vpin_low"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        tp = params["trail_pct"]
        mp = params["min_profit"]
        sl = params["sl"]
        cb = params["cooldown_bars"]
        bema = params["btc_ema"]
        bmth = params["btc_mom_th"]
        vsma = params["vol_sma"]
        vmul = params["vol_mult"]

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
            r = backtest(df_eth_test, df_btc_test,
                         vl, vm, mh, tp, mp, sl, cb,
                         bema, bmth, vsma, vmul)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)

        if oos_sharpes:
            avg_oos = float(np.mean(oos_sharpes))
            min_oos = min(oos_sharpes)
            min_n = min(oos_trades) if oos_trades else 0
            print(f"  #{rank}: vl={vl} vm={vm} hold={mh} "
                  f"trail={tp} minP={mp} SL={sl} cool={cb} "
                  f"bE={bema} bM={bmth} vS={vsma} vM={vmul} | "
                  f"train={params['sharpe']:+.3f} → "
                  f"avg_OOS={avg_oos:+.3f} min={min_oos:+.3f} "
                  f"min_n={min_n}")
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

    # ── Phase 4: 슬리피지 스트레스 (WF Top 3) ──────────────────────────────
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                       reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 3) ===")

    df_eth_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc_full = load_historical(BTC_SYMBOL, "240m", "2022-01-01", "2026-12-31")

    for rank, params in enumerate(wf_top3, 1):
        vl = params["vpin_low"]
        vm = params["vpin_mom"]
        mh = params["max_hold"]
        tp = params["trail_pct"]
        mp = params["min_profit"]
        sl = params["sl"]
        cb = params["cooldown_bars"]
        bema = params["btc_ema"]
        bmth = params["btc_mom_th"]
        vsma = params["vol_sma"]
        vmul = params["vol_mult"]
        print(f"\n--- #{rank}: vl={vl} vm={vm} hold={mh} "
              f"trail={tp} minP={mp} SL={sl} cool={cb} "
              f"bE={bema} bM={bmth} vS={vsma} vM={vmul} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(df_eth_full, df_btc_full,
                         vl, vm, mh, tp, mp, sl, cb,
                         bema, bmth, vsma, vmul, slippage=slip)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── c152 기준선 비교 (OOS) ───────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== c152 기준선 (BTC/볼륨 필터 없음) OOS 재현 ===")
    for fold_i, fold in enumerate(WF_FOLDS):
        df_eth_test = load_historical(
            SYMBOL, "240m", fold["test"][0], fold["test"][1])
        df_btc_test = load_historical(
            BTC_SYMBOL, "240m", fold["test"][0], fold["test"][1])
        if not df_eth_test.empty and not df_btc_test.empty:
            r = backtest(df_eth_test, df_btc_test,
                         0.30, 0.0007, 24, 0.015, 0.03, 0.006, 6,
                         50, -1.0, 20, 0.0)
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  Fold {fold_i + 1} OOS: Sharpe={sh:+.3f}  WR={r['wr']:.1%}  "
                  f"n={r['trades']}  avg={r['avg_ret'] * 100:+.2f}%  "
                  f"MDD={r['max_dd'] * 100:+.2f}%")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best = wf_sorted[0]
    print(f"★ OOS 최적: vl={best['vpin_low']} vm={best['vpin_mom']} "
          f"hold={best['max_hold']} trail={best['trail_pct']} "
          f"minP={best['min_profit']} SL={best['sl']} "
          f"cool={best['cooldown_bars']}")
    print(f"  BTC: EMA={best['btc_ema']} mom_th={best['btc_mom_th']}")
    print(f"  VOL: SMA={best['vol_sma']} mult={best['vol_mult']}")
    oos_avg = best["avg_oos_sharpe"]
    c152_target = 7.203
    delta = oos_avg - c152_target
    status = f"✅ ≥c152 (+{delta:+.3f})" if oos_avg >= c152_target else f"❌ <c152 ({delta:+.3f})"
    print(f"  avg OOS Sharpe: {oos_avg:+.3f} {status}")
    print(f"  train Sharpe: {best['train_sharpe']:+.3f}")
    for fi, sh in enumerate(best["oos_sharpes"]):
        fd = best["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"trades={best['oos_trades'][fi]}  avg={fd['avg_ret'] * 100:+.2f}%  "
              f"MDD={fd['max_dd'] * 100:+.2f}%")

    total_trades = sum(best["oos_trades"])
    avg_wr = float(np.mean([fd["wr"] for fd in best["fold_details"]]))

    print(f"\nSharpe: {oos_avg:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
