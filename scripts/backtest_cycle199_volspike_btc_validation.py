"""
사이클 199 — volspike_btc daemon 파라미터 정밀 WF 재검증

목적: daemon에 ₩1M 배치된 volspike_btc_wallet의 존속 판단
- 기존 백테스트는 엔진 편향 이전 수치 (⚠️ 신뢰불가)
- 현재 daemon 파라미터: spike=2.0, adx=20, body=0.2, TP=6%, SL=2%, mh=36
- Sharpe < 2.0이면 자본을 bb_squeeze_eth(Sharpe +17.9, 100% 로버스트)로 이전 권고

3-fold expanding WF + 슬리피지 스트레스
진입: next_bar open | ★슬리피지포함
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-BTC"
FEE = 0.0005

# daemon 파라미터 그대로
SPIKE_MULT = 2.0
VOLUME_WINDOW = 20
MIN_BODY_RATIO = 0.2
MOM_LOOKBACK = 12
RSI_PERIOD = 14
RSI_OVERBOUGHT = 72.0
MAX_HOLD = 36
ADX_THRESHOLD = 20.0
TP_PCT = 0.06
SL_PCT = 0.02

BTC_SMA_PERIOD = 200

# 3-fold expanding WF
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-02-28"), "test": ("2024-03-01", "2024-11-30")},
    {"train": ("2022-01-01", "2024-11-30"), "test": ("2024-12-01", "2025-08-31")},
    {"train": ("2022-01-01", "2025-05-31"), "test": ("2025-06-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


def sma_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    cumsum = np.cumsum(series)
    result[period - 1:] = (
        cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))
    ) / period
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


def compute_adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
) -> np.ndarray:
    n = len(closes)
    adx = np.full(n, np.nan)
    if n < period * 2:
        return adx

    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    atr = np.full(n, np.nan)
    smooth_plus = np.full(n, np.nan)
    smooth_minus = np.full(n, np.nan)
    atr[period] = np.mean(tr[1:period + 1])
    smooth_plus[period] = np.mean(plus_dm[1:period + 1])
    smooth_minus[period] = np.mean(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        smooth_plus[i] = (smooth_plus[i - 1] * (period - 1) + plus_dm[i]) / period
        smooth_minus[i] = (smooth_minus[i - 1] * (period - 1)
                           + minus_dm[i]) / period

    plus_di = np.where(atr > 0, smooth_plus / atr * 100, 0.0)
    minus_di = np.where(atr > 0, smooth_minus / atr * 100, 0.0)
    dx = np.where(
        (plus_di + minus_di) > 0,
        np.abs(plus_di - minus_di) / (plus_di + minus_di) * 100,
        0.0,
    )

    adx_start = period * 2
    if adx_start < n:
        adx[adx_start] = np.mean(
            dx[period + 1:adx_start + 1][~np.isnan(dx[period + 1:adx_start + 1])]
        )
        for i in range(adx_start + 1, n):
            if not np.isnan(adx[i - 1]):
                adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def backtest(
    df: pd.DataFrame,
    btc_close: np.ndarray,
    btc_sma: np.ndarray,
    slippage: float = 0.0005,
    require_bull: bool = True,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    vol_sma = sma_calc(v, VOLUME_WINDOW)
    rsi_arr = rsi_calc(c, RSI_PERIOD)
    mom_arr = np.full(n, np.nan)
    for i in range(MOM_LOOKBACK, n):
        mom_arr[i] = c[i] / c[i - MOM_LOOKBACK] - 1
    adx_arr = compute_adx(h, lo, c)

    returns: list[float] = []
    warmup = max(VOLUME_WINDOW, RSI_PERIOD + 1, MOM_LOOKBACK, 30) + 5
    i = warmup

    while i < n - 1:
        vol_sma_val = vol_sma[i]
        rsi_val = rsi_arr[i]
        mom_val = mom_arr[i]
        adx_val = adx_arr[i]

        if (np.isnan(vol_sma_val) or vol_sma_val <= 0
                or np.isnan(rsi_val) or np.isnan(mom_val)
                or np.isnan(adx_val)):
            i += 1
            continue

        # Volume spike detection
        spike_ok = v[i] >= vol_sma_val * SPIKE_MULT

        # Body ratio
        candle_range = h[i] - lo[i]
        body_ok = (
            candle_range > 0
            and abs(c[i] - o[i]) / candle_range >= MIN_BODY_RATIO
            and c[i] >= o[i]  # bullish candle
        )

        # Momentum positive
        mom_ok = mom_val > 0

        # RSI not overbought
        rsi_ok = rsi_val < RSI_OVERBOUGHT

        # ADX threshold
        adx_ok = adx_val >= ADX_THRESHOLD

        # BTC > SMA200 (bull regime)
        btc_bull = True
        if require_bull:
            btc_bull = (
                not np.isnan(btc_close[i])
                and not np.isnan(btc_sma[i])
                and btc_close[i] > btc_sma[i]
            )

        # 3-of-4 OR entry (daemon config)
        sub_checks = [body_ok, mom_ok, rsi_ok, adx_ok]
        sub_pass = sum(sub_checks)

        if spike_ok and sub_pass >= 3 and btc_bull:
            buy = o[i + 1] * (1 + FEE + slippage)

            exit_ret = None
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1

                if ret >= TP_PCT:
                    exit_ret = TP_PCT - FEE - slippage
                    i = j
                    break

                if ret <= -SL_PCT:
                    exit_ret = -SL_PCT - FEE - slippage
                    i = j
                    break

            if exit_ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                exit_ret = c[hold_end] / buy - 1 - FEE - slippage
                i = hold_end

            returns.append(exit_ret)
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd}


def main() -> None:
    print("=" * 80)
    print("=== 사이클 199 — volspike_btc daemon 파라미터 WF 재검증 ===")
    print(f"심볼: {SYMBOL} | spike={SPIKE_MULT} adx={ADX_THRESHOLD} "
          f"body={MIN_BODY_RATIO} TP={TP_PCT:.0%} SL={SL_PCT:.0%}")
    print("목적: Sharpe < 2.0 → 자본 bb_squeeze_eth로 이전 판단")
    print("=" * 80)

    df_btc = load_historical("KRW-BTC", "240m", "2021-01-01", "2026-12-31")
    df_btc_full = df_btc.copy()
    btc_close_full = df_btc["close"].values
    btc_sma_full = sma_calc(btc_close_full, BTC_SMA_PERIOD)

    # Align BTC to each test window
    btc_close_s = pd.Series(btc_close_full, index=df_btc.index)
    btc_sma_s = pd.Series(btc_sma_full, index=df_btc.index)

    print("\n--- 3-fold Walk-Forward ---")
    fold_results = []
    for fi, fold in enumerate(WF_FOLDS):
        t_start, t_end = fold["test"]
        df_test = load_historical(SYMBOL, "240m", t_start, t_end)
        if df_test.empty:
            print(f"  F{fi + 1}: 데이터 없음")
            continue

        btc_c = btc_close_s.reindex(df_test.index, method="ffill").values
        btc_s = btc_sma_s.reindex(df_test.index, method="ffill").values
        res = backtest(df_test, btc_c, btc_s)
        fold_results.append(res)

        # B&H
        bh = df_test["close"].iloc[-1] / df_test["close"].iloc[0] - 1

        print(f"  F{fi + 1} ({t_start}~{t_end}): "
              f"Sharpe {res['sharpe']:+.3f} WR {res['wr']:.1%} "
              f"n={res['trades']} MDD {res['max_dd']:.2%} | B&H {bh:+.1%}")

    # Average
    valid = [r for r in fold_results if r["trades"] > 0
             and not np.isnan(r["sharpe"])]
    if valid:
        avg_sh = float(np.mean([r["sharpe"] for r in valid]))
        avg_wr = float(np.mean([r["wr"] for r in valid]))
        total_n = sum(r["trades"] for r in valid)
        avg_mdd = float(np.mean([r["max_dd"] for r in valid]))
    else:
        avg_sh = float("nan")
        avg_wr = 0.0
        total_n = 0
        avg_mdd = 0.0

    print(f"\n  Average: Sharpe {avg_sh:+.3f} WR {avg_wr:.1%} "
          f"n={total_n} MDD {avg_mdd:.2%}")

    # -- Also test without bull regime filter (all regimes) --
    print("\n--- All Regimes (BTC gate OFF) ---")
    fold_results_all = []
    for fi, fold in enumerate(WF_FOLDS):
        t_start, t_end = fold["test"]
        df_test = load_historical(SYMBOL, "240m", t_start, t_end)
        if df_test.empty:
            continue
        btc_c = btc_close_s.reindex(df_test.index, method="ffill").values
        btc_s = btc_sma_s.reindex(df_test.index, method="ffill").values
        res = backtest(df_test, btc_c, btc_s, require_bull=False)
        fold_results_all.append(res)
        print(f"  F{fi + 1} ({t_start}~{t_end}): "
              f"Sharpe {res['sharpe']:+.3f} WR {res['wr']:.1%} "
              f"n={res['trades']} MDD {res['max_dd']:.2%}")

    valid_all = [r for r in fold_results_all if r["trades"] > 0
                 and not np.isnan(r["sharpe"])]
    if valid_all:
        avg_sh_all = float(np.mean([r["sharpe"] for r in valid_all]))
        total_n_all = sum(r["trades"] for r in valid_all)
        print(f"  Average: Sharpe {avg_sh_all:+.3f} n={total_n_all}")

    # -- Slippage stress (bull regime) --
    if valid:
        print(f"\n--- 슬리피지 스트레스 ---")
        print(f"{'slip':>6} {'Sharpe':>8} {'WR':>6} {'n':>4}")
        for slip in SLIPPAGE_LEVELS:
            slip_results = []
            for fi, fold in enumerate(WF_FOLDS):
                t_start, t_end = fold["test"]
                df_test = load_historical(SYMBOL, "240m", t_start, t_end)
                if df_test.empty:
                    continue
                btc_c = btc_close_s.reindex(df_test.index, method="ffill").values
                btc_s = btc_sma_s.reindex(df_test.index, method="ffill").values
                res = backtest(df_test, btc_c, btc_s, slip)
                slip_results.append(res)
            vs = [r for r in slip_results if r["trades"] > 0
                  and not np.isnan(r["sharpe"])]
            if vs:
                ss = float(np.mean([r["sharpe"] for r in vs]))
                sw = float(np.mean([r["wr"] for r in vs]))
                sn = sum(r["trades"] for r in vs)
                print(f"{slip:.2%} {ss:>+8.3f} {sw:>5.1%} {sn:>4}")

    # -- 판정 --
    print(f"\n{'=' * 80}")
    if not np.isnan(avg_sh):
        if avg_sh >= 5.0:
            print(f"판정: ✅ volspike_btc PASS (Sharpe {avg_sh:+.3f} ≥ 5.0)")
        elif avg_sh >= 2.0:
            print(f"판정: ⚠️ volspike_btc MARGINAL (Sharpe {avg_sh:+.3f})")
        else:
            print(f"판정: ❌ volspike_btc FAIL (Sharpe {avg_sh:+.3f} < 2.0) "
                  f"→ 자본 ₩1M을 bb_squeeze_eth로 이전 권고")
    else:
        print("판정: ❌ volspike_btc FAIL (유효 결과 없음)")
    print(f"{'=' * 80}")

    print(f"\nSharpe: {avg_sh:+.3f}")
    print(f"WR: {avg_wr:.1%}")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
