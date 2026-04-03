"""
backtest_bear_filter.py — Bear/Fear 구간 진입 허용 vs 차단 비교

질문: F&G 극도공포 / BTC 베어 레짐에서 진입하면 수익이 날까?

방법:
  - momentum_sol + vpin_eth 전략
  - BTC SMA20 기반 레짐 분류 (bull/bear)
  - BTC RSI14를 F&G 프록시로 사용
    RSI < 30 ≈ F&G 극도공포 (0~24)
    RSI < 45 ≈ F&G 공포 (25~49)
  - 필터 조합별 Sharpe/WR/trades 비교

결론:
  - 베어+극도공포 구간 진입이 수익이면 → 필터 완화
  - 베어+극도공포 구간 진입이 손실이면 → 필터 유지
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

START  = "2022-01-01"
END    = "2026-12-31"
FEE    = 0.0005

# momentum_sol 최적 파라미터 (백테스트 확정값)
SOL_LOOKBACK  = 20
SOL_ADX       = 25.0
SOL_VOL       = 2.0
SOL_TP        = 0.12
SOL_SL        = 0.04
SOL_ENTRY_THR = 0.005
SOL_MAX_HOLD  = 48

# vpin_eth 최적 파라미터
ETH_VH        = 0.55
ETH_VM        = 0.0005
ETH_HOLD      = 18
ETH_TP        = 0.06
ETH_SL        = 0.008


# ── 지표 ──────────────────────────────────────────────────────────────────────

def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i-1] * (period-1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period-1) + losses[i-1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def adx_series(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    if n < period * 2:
        return result
    tr = np.maximum(highs[1:] - lows[1:],
         np.maximum(np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1])))
    pdm = np.where((highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
                   np.maximum(highs[1:] - highs[:-1], 0), 0)
    ndm = np.where((lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
                   np.maximum(lows[:-1] - lows[1:], 0), 0)

    def smooth(arr, p):
        out = np.full(len(arr) + 1, np.nan)
        out[p] = arr[:p].sum()
        for i in range(p, len(arr)):
            out[i+1] = out[i] - out[i]/p + arr[i]
        return out[1:]

    atr_s = smooth(tr, period)
    pdm_s = smooth(pdm, period)
    ndm_s = smooth(ndm, period)

    with np.errstate(invalid='ignore', divide='ignore'):
        pdi = 100 * pdm_s / atr_s
        ndi = 100 * ndm_s / atr_s
        dx  = 100 * np.abs(pdi - ndi) / (pdi + ndi + 1e-9)

    adx_val = np.full(n - 1, np.nan)
    start = period * 2 - 1
    if start < len(dx):
        adx_val[start] = np.nanmean(dx[period:start+1])
        for i in range(start + 1, len(dx)):
            adx_val[i] = (adx_val[i-1] * (period-1) + dx[i]) / period

    out = np.full(n, np.nan)
    out[1:] = adx_val
    return out


# ── BTC 레짐 계산 ─────────────────────────────────────────────────────────────

def compute_btc_regime(df_btc: pd.DataFrame, sma_period: int = 20) -> pd.Series:
    """BTC SMA{sma_period} 기준 bull/bear 레짐."""
    sma = df_btc["close"].rolling(sma_period).mean()
    return (df_btc["close"] > sma).rename("btc_bull")


def compute_btc_rsi_proxy(df_btc: pd.DataFrame, period: int = 14) -> pd.Series:
    """BTC RSI14 — F&G 프록시. RSI < 30 ≈ 극도공포."""
    r = rsi(df_btc["close"].values, period)
    return pd.Series(r, index=df_btc.index, name="btc_rsi")


# ── momentum_sol 백테스트 ─────────────────────────────────────────────────────

def backtest_momentum(
    df: pd.DataFrame,
    btc_bull: pd.Series,
    btc_rsi: pd.Series,
    allow_bear: bool,
    rsi_threshold: float,  # 이 RSI 이상일 때만 진입 (낮을수록 완화)
) -> dict:
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    vols   = df["volume"].values
    n      = len(closes)

    rsi_arr = rsi(closes, 14)
    adx_arr = adx_series(highs, lows, closes, 14)
    vol_ma  = pd.Series(vols).rolling(SOL_LOOKBACK).mean().values

    trades = []
    in_pos = False
    entry_i = entry_p = 0

    for i in range(SOL_LOOKBACK + 20, n):
        ts = df.index[i]

        # BTC 레짐 체크
        is_bull = btc_bull.get(ts, False)
        btc_r = btc_rsi.get(ts, 50.0)

        if in_pos:
            ret = (closes[i] - entry_p) / entry_p
            hold_bars = i - entry_i
            if ret >= SOL_TP or ret <= -SOL_SL or hold_bars >= SOL_MAX_HOLD:
                pnl = ret - FEE * 2
                trades.append(pnl)
                in_pos = False
        else:
            # 필터 적용
            if not allow_bear and not is_bull:
                continue
            if btc_r < rsi_threshold:
                continue

            # 진입 조건
            if adx_arr[i] < SOL_ADX:
                continue
            if vols[i] < vol_ma[i] * SOL_VOL:
                continue
            if np.isnan(rsi_arr[i]):
                continue

            momentum = (closes[i] - closes[i - SOL_LOOKBACK]) / closes[i - SOL_LOOKBACK]
            if momentum > SOL_ENTRY_THR and rsi_arr[i] < 75:
                in_pos = True
                entry_i = i
                entry_p = closes[i] * (1 + FEE)

    if not trades:
        return {"sharpe": None, "wr": 0, "avg_ret": 0, "trades": 0}

    arr = np.array(trades)
    sharpe = (arr.mean() / (arr.std() + 1e-9)) * np.sqrt(252 * 6)
    return {
        "sharpe": round(float(sharpe), 3),
        "wr": round(float((arr > 0).mean() * 100), 1),
        "avg_ret": round(float(arr.mean() * 100), 2),
        "trades": len(trades),
    }


# ── vpin_eth 백테스트 ─────────────────────────────────────────────────────────

def backtest_vpin(
    df: pd.DataFrame,
    btc_bull: pd.Series,
    btc_rsi: pd.Series,
    allow_bear: bool,
    rsi_threshold: float,
) -> dict:
    closes = df["close"].values
    vols   = df["volume"].values
    n      = len(closes)

    bucket = 50
    vol_cum = np.cumsum(vols)
    vpin_arr = np.full(n, np.nan)

    for i in range(bucket, n):
        window_vol = vol_cum[i] - vol_cum[i - bucket]
        if window_vol == 0:
            continue
        buy_vol = sum(
            vols[j] if closes[j] > closes[j-1] else 0
            for j in range(i - bucket + 1, i + 1)
        )
        vpin_arr[i] = buy_vol / window_vol

    ema20 = pd.Series(closes).ewm(span=20).mean().values
    rsi_arr = rsi(closes, 14)

    trades = []
    in_pos = False
    entry_i = entry_p = 0

    for i in range(bucket + 20, n):
        ts = df.index[i]
        is_bull = btc_bull.get(ts, False)
        btc_r   = btc_rsi.get(ts, 50.0)

        if in_pos:
            ret = (closes[i] - entry_p) / entry_p
            hold = i - entry_i
            if ret >= ETH_TP or ret <= -ETH_SL or hold >= ETH_HOLD:
                trades.append(ret - FEE * 2)
                in_pos = False
        else:
            if not allow_bear and not is_bull:
                continue
            if btc_r < rsi_threshold:
                continue
            if np.isnan(vpin_arr[i]) or np.isnan(rsi_arr[i]):
                continue

            # vpin 진입 조건
            vpin_mom = 0.0
            if i > 0 and not np.isnan(vpin_arr[i-1]):
                vpin_mom = vpin_arr[i] - vpin_arr[i-1]

            ema_up = closes[i] > ema20[i]
            if (vpin_arr[i] > ETH_VH and vpin_mom > ETH_VM
                    and rsi_arr[i] < 70 and ema_up):
                in_pos = True
                entry_i = i
                entry_p = closes[i] * (1 + FEE)

    if not trades:
        return {"sharpe": None, "wr": 0, "avg_ret": 0, "trades": 0}

    arr = np.array(trades)
    sharpe = (arr.mean() / (arr.std() + 1e-9)) * np.sqrt(252 * 6)
    return {
        "sharpe": round(float(sharpe), 3),
        "wr": round(float((arr > 0).mean() * 100), 1),
        "avg_ret": round(float(arr.mean() * 100), 2),
        "trades": len(trades),
    }


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  Bear/Fear 구간 진입 허용 vs 차단 비교 백테스트")
    print(f"  기간: {START} ~ {END}")
    print("=" * 65)

    print("\n데이터 로딩...")
    df_sol = load_historical("KRW-SOL", "240m", START, END)
    df_eth = load_historical("KRW-ETH", "240m", START, END)
    df_btc = load_historical("KRW-BTC", "240m", START, END)

    if df_sol is None or df_eth is None or df_btc is None:
        print("ERROR: 데이터 로드 실패")
        return

    # BTC 레짐 + RSI 프록시
    btc_bull = compute_btc_regime(df_btc, sma_period=20)
    btc_rsi  = compute_btc_rsi_proxy(df_btc, period=14)

    # df를 BTC 인덱스에 맞춰 reindex
    btc_bull = btc_bull.reindex(df_sol.index, method="ffill").fillna(False)
    btc_rsi_sol = btc_rsi.reindex(df_sol.index, method="ffill").fillna(50.0)
    btc_rsi_eth = btc_rsi.reindex(df_eth.index, method="ffill").fillna(50.0)
    btc_bull_eth = compute_btc_regime(df_btc, sma_period=20)
    btc_bull_eth = btc_bull_eth.reindex(df_eth.index, method="ffill").fillna(False)

    # 레짐 통계
    bull_ratio = btc_bull.mean() * 100
    fear_ratio = (btc_rsi_sol < 30).mean() * 100
    print(f"\nBTC 레짐: bull {bull_ratio:.1f}% / bear {100-bull_ratio:.1f}%")
    print(f"극도공포 (RSI<30) 비율: {fear_ratio:.1f}%")

    # ── 필터 조합 테스트 ──────────────────────────────────────────────────────
    # (allow_bear, rsi_threshold, label)
    configs = [
        (False, 30.0, "현재 설정 (bear 차단 + RSI≥30)"),
        (True,  30.0, "bear 허용 + RSI≥30"),
        (True,  20.0, "bear 허용 + RSI≥20 (완화)"),
        (True,  15.0, "bear 허용 + RSI≥15 (적극 완화)"),
        (True,   0.0, "모든 구간 허용 (필터 없음)"),
    ]

    print("\n\n[momentum_sol / KRW-SOL]")
    print(f"  {'설정':<35} | {'Sharpe':>7} | {'WR':>6} | {'avg%':>6} | {'trades':>7}")
    print("  " + "-" * 70)
    for allow_bear, rsi_thr, label in configs:
        r = backtest_momentum(df_sol, btc_bull, btc_rsi_sol, allow_bear, rsi_thr)
        sh = f"{r['sharpe']:+.3f}" if r["sharpe"] is not None else "  N/A"
        print(f"  {label:<35} | {sh:>7} | {r['wr']:>5.1f}% | {r['avg_ret']:>+5.2f}% | {r['trades']:>7}")

    print("\n\n[vpin_eth / KRW-ETH]")
    print(f"  {'설정':<35} | {'Sharpe':>7} | {'WR':>6} | {'avg%':>6} | {'trades':>7}")
    print("  " + "-" * 70)
    for allow_bear, rsi_thr, label in configs:
        r = backtest_vpin(df_eth, btc_bull_eth, btc_rsi_eth, allow_bear, rsi_thr)
        sh = f"{r['sharpe']:+.3f}" if r["sharpe"] is not None else "  N/A"
        print(f"  {label:<35} | {sh:>7} | {r['wr']:>5.1f}% | {r['avg_ret']:>+5.2f}% | {r['trades']:>7}")

    print("\n\n결론 기준:")
    print("  Sharpe 증가 & WR 유지 → 필터 완화 권장")
    print("  Sharpe 감소 또는 WR 하락 → 현재 필터 유지")


if __name__ == "__main__":
    main()
