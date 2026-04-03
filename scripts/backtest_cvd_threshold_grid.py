from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.historical_loader import load_historical

INTERVAL = "240m"
START = "2022-01-01"
END = "2026-12-31"
ALT_SYMBOLS = [
    "KRW-ETH",
    "KRW-SOL",
    "KRW-XRP",
    "KRW-ADA",
    "KRW-AVAX",
    "KRW-LINK",
    "KRW-DOT",
    "KRW-ATOM",
]
W = 24
THRESHOLDS = [-0.5, -0.3, -0.1, 0.0, 0.1, 0.2, 0.3, 0.5]

TP = 0.15
SL = -0.03
MAX_HOLD = 36
COMMISSION = 0.001  # round-trip 0.10%


@dataclass
class SeriesPack:
    close: np.ndarray
    volume: np.ndarray
    vpin: np.ndarray
    cvd: np.ndarray
    acc: np.ndarray
    cvd_slope: np.ndarray
    ret24: np.ndarray
    sma20: np.ndarray


def compute_vpin(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < 2:
        return out
    direction = np.where(close[1:] >= close[:-1], 1.0, -1.0)
    buy_vol = np.where(direction > 0, volume[1:], 0.0)
    out[1:] = buy_vol / (volume[1:] + 1e-9)
    return out


def rolling_mean_np(x: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(x).rolling(window=window, min_periods=window).mean().to_numpy(dtype=np.float64)


def build_pack(df: pd.DataFrame) -> SeriesPack:
    close = df["close"].to_numpy(dtype=np.float64)
    open_ = df["open"].to_numpy(dtype=np.float64)
    volume = df["volume"].to_numpy(dtype=np.float64)

    vpin = compute_vpin(close, volume)

    # CVD from signed bar volume using sign(close-open)
    bar_sign = np.sign(close - open_)
    signed_volume = bar_sign * volume
    cvd = np.cumsum(signed_volume)

    n = len(close)
    acc = np.full(n, np.nan, dtype=np.float64)
    cvd_slope = np.full(n, np.nan, dtype=np.float64)
    ret24 = np.full(n, np.nan, dtype=np.float64)

    for t in range(n):
        if t >= 2 * W:
            cur = np.nanmean(vpin[t - W : t])
            prev = np.nanmean(vpin[t - 2 * W : t - W])
            if np.isfinite(cur) and np.isfinite(prev) and abs(prev) > 1e-12:
                acc[t] = cur / prev

        if t >= 11:
            recent = np.sum(cvd[t - 5 : t + 1])
            prev = np.sum(cvd[t - 11 : t - 5])
            vol_mean = np.mean(volume[t - 11 : t + 1])
            if np.isfinite(vol_mean) and vol_mean > 1e-12:
                cvd_slope[t] = (recent - prev) / vol_mean

        if t >= 24 and abs(close[t - 24]) > 1e-12:
            ret24[t] = close[t] / close[t - 24] - 1.0

    sma20 = rolling_mean_np(close, 20)

    return SeriesPack(
        close=close,
        volume=volume,
        vpin=vpin,
        cvd=cvd,
        acc=acc,
        cvd_slope=cvd_slope,
        ret24=ret24,
        sma20=sma20,
    )


def align_alt_with_btc(btc_df: pd.DataFrame, alt_df: pd.DataFrame) -> pd.DataFrame:
    if btc_df.empty or alt_df.empty:
        return pd.DataFrame()
    merged = pd.DataFrame(index=btc_df.index)
    merged["btc_close"] = btc_df["close"]
    merged["btc_open"] = btc_df["open"]
    merged["btc_volume"] = btc_df["volume"]

    alt_cols = alt_df[["open", "high", "low", "close", "volume"]].copy()
    alt_cols.columns = [f"alt_{c}" for c in alt_cols.columns]
    merged = merged.join(alt_cols, how="inner")
    merged = merged.dropna()
    return merged


def simulate_threshold(merged_by_symbol: dict[str, pd.DataFrame], threshold: float) -> list[float]:
    all_returns: list[float] = []

    for _symbol, merged in merged_by_symbol.items():
        if len(merged) < max(2 * W + 1, 60):
            continue

        btc_pack = build_pack(
            merged.rename(
                columns={
                    "btc_open": "open",
                    "btc_close": "close",
                    "btc_volume": "volume",
                }
            )[["open", "close", "volume"]].assign(high=np.nan, low=np.nan)
        )
        alt_pack = build_pack(
            merged.rename(
                columns={
                    "alt_open": "open",
                    "alt_close": "close",
                    "alt_volume": "volume",
                }
            )[["open", "close", "volume"]].assign(high=np.nan, low=np.nan)
        )

        alt_close = alt_pack.close
        btc_close = btc_pack.close
        n = len(merged)

        ratio = alt_close / (btc_close + 1e-9)
        ratio_mean_24 = rolling_mean_np(ratio, 24)
        rs = ratio / (ratio_mean_24 + 1e-9)

        start_t = max(2 * W, 24, 19, 11)

        for t in range(start_t, n - 1):
            btc_stealth = (
                np.isfinite(btc_pack.ret24[t])
                and btc_pack.ret24[t] < 0.0
                and np.isfinite(btc_pack.acc[t])
                and btc_pack.acc[t] > 1.0
                and np.isfinite(btc_pack.cvd_slope[t])
                and btc_pack.cvd_slope[t] > threshold
            )
            if not btc_stealth:
                continue

            entry_ok = (
                np.isfinite(rs[t])
                and 0.5 <= rs[t] < 1.0
                and np.isfinite(alt_pack.acc[t])
                and alt_pack.acc[t] > 1.0
                and np.isfinite(alt_pack.cvd_slope[t])
                and alt_pack.cvd_slope[t] > 0.0
                and np.isfinite(alt_pack.sma20[t])
                and alt_close[t] < alt_pack.sma20[t]
            )
            if not entry_ok:
                continue

            entry_price = alt_close[t]
            if not np.isfinite(entry_price) or entry_price <= 0:
                continue

            exit_price = None
            max_j = min(MAX_HOLD, n - 1 - t)
            for j in range(1, max_j + 1):
                px = alt_close[t + j]
                if not np.isfinite(px) or px <= 0:
                    continue
                ret = px / entry_price - 1.0
                if ret >= TP or ret <= SL:
                    exit_price = px
                    break

            if exit_price is None:
                if max_j <= 0:
                    continue
                exit_price = alt_close[t + max_j]
                if not np.isfinite(exit_price) or exit_price <= 0:
                    continue

            trade_ret = exit_price / entry_price - 1.0 - COMMISSION
            all_returns.append(float(trade_ret))

    return all_returns


def summarize_returns(rets: list[float]) -> tuple[int, float, float, float]:
    if not rets:
        return 0, 0.0, 0.0, 0.0

    arr = np.array(rets, dtype=np.float64)
    trades = len(arr)
    wr = float(np.mean(arr > 0.0))
    avg_ret_pct = float(np.mean(arr) * 100.0)
    sharpe = float((np.mean(arr) / (np.std(arr) + 1e-9)) * math.sqrt(252 * 6))
    return trades, wr, avg_ret_pct, sharpe


def main() -> None:
    btc = load_historical("KRW-BTC", INTERVAL, START, END)
    if btc.empty:
        raise RuntimeError("BTC historical data not found for requested period")

    merged_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in ALT_SYMBOLS:
        alt = load_historical(symbol, INTERVAL, START, END)
        if alt.empty:
            continue
        merged = align_alt_with_btc(btc, alt)
        if len(merged) < 100:
            continue
        merged_by_symbol[symbol] = merged

    results: list[tuple[float, int, float, float, float]] = []
    for threshold in THRESHOLDS:
        rets = simulate_threshold(merged_by_symbol, threshold)
        trades, wr, avg_ret_pct, sharpe = summarize_returns(rets)
        results.append((threshold, trades, wr, avg_ret_pct, sharpe))

    print("=== BTC CVD Threshold Grid ===")
    print(f"{'threshold':>9} | {'trades':>6} | {'WR':>6} | {'avg%':>7} | {'Sharpe':>7}")
    for threshold, trades, wr, avg_ret_pct, sharpe in results:
        print(
            f"{threshold:>9.1f} | {trades:>6d} | {wr*100:>5.1f}% | "
            f"{avg_ret_pct:+6.2f}% | {sharpe:+7.3f}"
        )

    print()
    best = max(results, key=lambda x: x[4]) if results else (0.0, 0, 0.0, 0.0, 0.0)
    print(
        f"★ best: threshold={best[0]:.1f} → Sharpe={best[4]:.3f}, "
        f"WR={best[2]*100:.1f}%, avg={best[3]:+,.2f}%"
    )


if __name__ == "__main__":
    main()
