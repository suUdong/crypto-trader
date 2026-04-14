#!/usr/bin/env python
"""Follow-up to GPU tournament 2026-04-07: expand stealth_3gate parameters.

Sweeps BTC regime lookback, alt RSI ceiling, and volume ratio floor
across full 2025-2026 4h history to confirm robustness of Sharpe +6.195.
"""
from __future__ import annotations

import glob
import io
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("/home/wdsr88/workspace/crypto-trader/data/historical/monthly/240m")
YEARS = ["2025", "2026"]
HOLD_BARS = 6  # 24h hold
FEE = 0.0005


def load_symbol(sym: str) -> pd.DataFrame | None:
    frames = []
    for y in YEARS:
        for fp in sorted(glob.glob(str(DATA_DIR / y / f"{sym}_candle-240m_*.zip"))):
            with zipfile.ZipFile(fp) as z:
                with z.open(z.namelist()[0]) as f:
                    frames.append(pd.read_csv(io.TextIOWrapper(f)))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["date_time_utc"] = pd.to_datetime(df["date_time_utc"])
    df = df.sort_values("date_time_utc").drop_duplicates("date_time_utc").reset_index(drop=True)
    return df


def list_symbols() -> list[str]:
    syms: set[str] = set()
    for y in YEARS:
        for fp in glob.glob(str(DATA_DIR / y / "KRW-*_candle-240m_*.zip")):
            name = Path(fp).name
            syms.add(name.split("_candle-")[0])
    return sorted(syms)


def rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    diff = np.diff(close, prepend=close[0])
    up = np.where(diff > 0, diff, 0.0)
    dn = np.where(diff < 0, -diff, 0.0)
    ru = pd.Series(up).rolling(n).mean().to_numpy()
    rd = pd.Series(dn).rolling(n).mean().to_numpy()
    rs = np.divide(ru, rd, out=np.zeros_like(ru), where=rd > 0)
    return 100 - 100 / (1 + rs)


def simulate(
    btc_close: np.ndarray,
    sym_data: dict[str, pd.DataFrame],
    btc_lookback: int,
    rsi_max: float,
    vol_mult: float,
) -> tuple[float, float, int]:
    btc_ret = pd.Series(btc_close).pct_change(btc_lookback).to_numpy()
    rets: list[float] = []
    wins = 0
    n = len(btc_close)
    for sym, df in sym_data.items():
        if len(df) < n:
            continue
        close = df["close"].to_numpy()[:n]
        vol = df["acc_trade_volume"].to_numpy()[:n]
        r = rsi(close)
        vol_ma = pd.Series(vol).rolling(20).mean().to_numpy()
        vol_ratio = np.divide(vol, vol_ma, out=np.zeros_like(vol), where=vol_ma > 0)
        sig = (btc_ret > 0) & (r < rsi_max) & (vol_ratio > vol_mult)
        idx = np.where(sig)[0]
        last_exit = -1
        for i in idx:
            if i <= last_exit or i + HOLD_BARS >= n:
                continue
            entry = close[i]
            exit_p = close[i + HOLD_BARS]
            if entry <= 0:
                continue
            ret = (exit_p / entry - 1) - 2 * FEE
            rets.append(ret)
            if ret > 0:
                wins += 1
            last_exit = i + HOLD_BARS
    if len(rets) < 10:
        return float("nan"), 0.0, len(rets)
    arr = np.array(rets)
    sharpe = arr.mean() / (arr.std() + 1e-9) * math.sqrt(365 * 6 / HOLD_BARS)
    wr = wins / len(rets) * 100
    return sharpe, wr, len(rets)


def main() -> None:
    print("[1/3] Loading BTC reference...")
    btc = load_symbol("KRW-BTC")
    assert btc is not None
    btc_close = btc["close"].to_numpy()
    n = len(btc_close)
    print(f"  BTC bars: {n}")

    print("[2/3] Loading alt symbols...")
    syms = [s for s in list_symbols() if s != "KRW-BTC"]
    sym_data: dict[str, pd.DataFrame] = {}
    for s in syms:
        df = load_symbol(s)
        if df is not None and len(df) >= 100:
            sym_data[s] = df
    print(f"  Loaded: {len(sym_data)}")

    print("[3/3] Sweeping params...")
    grid = [
        (lb, rmax, vm)
        for lb in (10, 20, 40)
        for rmax in (35, 40, 45)
        for vm in (1.2, 1.5, 2.0)
    ]
    results = []
    for lb, rmax, vm in grid:
        sh, wr, nt = simulate(btc_close, sym_data, lb, rmax, vm)
        results.append((sh, wr, nt, lb, rmax, vm))
        print(
            f"  btc_lb={lb:>2} rsi_max={rmax} vol_mult={vm:.1f} | "
            f"Sharpe: {sh:+.2f}  WR: {wr:.1f}%  trades: {nt}"
        )

    results.sort(key=lambda r: (-r[0] if not math.isnan(r[0]) else 1e9))
    print("\n=== TOP 5 ===")
    for sh, wr, nt, lb, rmax, vm in results[:5]:
        print(
            f"  btc_lb={lb} rsi_max={rmax} vol_mult={vm} | "
            f"Sharpe: {sh:+.2f}  WR: {wr:.1f}%  trades: {nt}"
        )

    best = results[0]
    print(
        f"\nBEST → Sharpe: {best[0]:+.2f}  WR: {best[1]:.1f}%  trades: {best[2]}  "
        f"(btc_lb={best[3]}, rsi_max={best[4]}, vol_mult={best[5]})"
    )


if __name__ == "__main__":
    main()
