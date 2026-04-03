"""
Bear Regime Alt Stealth Signal Backtest (사이클 104)

가설: BTC BEAR 레짐(BTC < SMA20)에서 alt-side stealth signal만으로도 유효한 엣지가 있는가?

현재 stealth_3gate는 Gate 1(BTC > SMA20)을 필수로 요구.
→ BEAR 레짐에서는 신호 없음. 하지만 일부 alts는 독립적으로 accumulation 진행 가능.

측정:
  - BEAR 레짐에서 alt stealth signal (CVD>0 + acc>1.0 + RS∈[0.5,1.0)) 진입 성과
  - BULL 레짐 동일 조건 대조군
  - 전체 기간 결과 비교

결론 기대:
  - BULL >> BEAR → Gate 1은 필수 (현재 설계 유효)
  - BULL ≈ BEAR → Gate 1 제거 검토 가능 (BEAR 모드 stealth 가능)
  - BEAR > BULL → 역발상 진입 기회 존재
"""
from __future__ import annotations

import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical, get_available_symbols

INTERVAL = "240m"
START = "2022-01-01"
END = "2026-04-03"
BTC_SYMBOL = "KRW-BTC"

# Stealth parameters (from daemon.toml confirmed optimal)
W = 36          # stealth lookback
SMA_P = 20      # BTC SMA period
RS_LOW = 0.5
RS_HIGH = 1.0
CVD_THRESH = 0.0

FWD = 6         # 24h forward (6 * 4h candles)
FEE = 0.0005    # 0.05% per side

# Symbols to test (diverse set)
SYMBOLS = [
    "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-AVAX",
    "KRW-DOT", "KRW-LINK", "KRW-ATOM", "KRW-NEAR",
    "KRW-SUI", "KRW-APT", "KRW-TRX",
    "KRW-INJ", "KRW-STX", "KRW-MANA",
    "KRW-BNB", "KRW-LTC", "KRW-BCH",
]

MIN_TRADES = 5  # minimum trades to include in result


def load_df(symbol: str) -> tuple[str, pd.DataFrame | None]:
    try:
        df = load_historical(symbol, INTERVAL, START, END)
        if df is None or len(df) < W * 3:
            return symbol, None
        return symbol, df
    except Exception as e:
        return symbol, None


def compute_sma(closes: np.ndarray, period: int) -> np.ndarray:
    sma = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        sma[i] = closes[i - period + 1 : i + 1].mean()
    return sma


def compute_cvd_slope(closes: np.ndarray, volumes: np.ndarray, window: int) -> np.ndarray:
    direction = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy_vols = np.where(direction > 0, volumes[1:], 0.0)
    cvd = np.cumsum(buy_vols - volumes[1:] / 2)
    cvd = np.concatenate([[0.0], cvd])
    slopes = np.full(len(closes), np.nan)
    avg_vol = np.mean(volumes)
    for i in range(window, len(closes)):
        slopes[i] = (cvd[i] - cvd[i - window]) / (avg_vol + 1e-9)
    return slopes


def compute_acc(closes: np.ndarray, volumes: np.ndarray, window: int) -> np.ndarray:
    direction = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy_vols = np.where(direction > 0, volumes[1:], 0.0)
    vpin = np.concatenate([[np.nan], buy_vols / (volumes[1:] + 1e-9)])
    acc = np.full(len(closes), np.nan)
    for i in range(window * 2, len(closes)):
        recent = np.nanmean(vpin[i - window : i])
        older = np.nanmean(vpin[i - window * 2 : i - window])
        acc[i] = recent / (older + 1e-9)
    return acc


def compute_rs_score(closes: np.ndarray, btc_closes: np.ndarray, window: int) -> np.ndarray:
    rs = np.full(len(closes), np.nan)
    for i in range(window, len(closes)):
        alt_ret = closes[i] / closes[i - window] - 1.0
        btc_ret = btc_closes[i] / btc_closes[i - window] - 1.0
        # RS sigma score (normalized alt return relative to BTC)
        # Simple proxy: alt_ret - btc_ret normalized by abs(btc_ret)
        rs[i] = (alt_ret - btc_ret) / (abs(btc_ret) + 0.05)
    return rs


def backtest_symbol(
    symbol: str,
    df: pd.DataFrame,
    btc_closes: np.ndarray,
    btc_sma: np.ndarray,
) -> dict:
    closes = df["close"].values
    volumes = df["volume"].values
    n = len(closes)

    cvd_slope = compute_cvd_slope(closes, volumes, W)
    acc = compute_acc(closes, volumes, W)
    rs = compute_rs_score(closes, btc_closes[: n], W)

    results = {"bull": [], "bear": []}

    for i in range(W * 2, n - FWD):
        # BTC regime
        if np.isnan(btc_sma[i]):
            continue
        btc_in_bull = btc_closes[i] > btc_sma[i]

        # Alt stealth signal
        if np.isnan(cvd_slope[i]) or np.isnan(acc[i]) or np.isnan(rs[i]):
            continue

        cvd_ok = cvd_slope[i] > CVD_THRESH
        acc_ok = acc[i] > 1.0
        rs_ok = RS_LOW <= rs[i] < RS_HIGH

        signal = cvd_ok and acc_ok and rs_ok

        if not signal:
            continue

        # Forward return
        fwd_ret = closes[i + FWD] / closes[i] - 1.0 - 2 * FEE

        regime = "bull" if btc_in_bull else "bear"
        results[regime].append(fwd_ret)

    return {"symbol": symbol, "bull": results["bull"], "bear": results["bear"]}


def summarize(returns: list[float], label: str) -> dict:
    if not returns:
        return {"label": label, "n": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0}
    arr = np.array(returns)
    wr = float(np.mean(arr > 0))
    avg = float(np.mean(arr)) * 100
    sharpe = float(np.mean(arr) / (np.std(arr) + 1e-9) * np.sqrt(252 * 6)) if len(arr) > 1 else 0.0
    return {"label": label, "n": len(arr), "wr": wr, "avg": avg, "sharpe": sharpe}


def main() -> None:
    print("=== Bear Regime Alt Stealth Signal Backtest ===")
    print(f"Period: {START} ~ {END}, Interval: {INTERVAL}, FWD: {FWD} candles (24h)")
    print(f"Stealth params: W={W}, RS=[{RS_LOW},{RS_HIGH}), CVD>{CVD_THRESH}, acc>1.0")
    print()

    # Load BTC
    print("Loading BTC data...")
    btc_df = load_historical(BTC_SYMBOL, INTERVAL, START, END)
    if btc_df is None:
        print("ERROR: BTC data not found")
        return

    btc_closes = btc_df["close"].values
    btc_sma = compute_sma(btc_closes, SMA_P)

    bull_mask = btc_closes > btc_sma
    bull_pct = np.nanmean(bull_mask[SMA_P:]) * 100
    print(f"BTC BULL regime: {bull_pct:.1f}% of candles")
    print()

    # Load alt data
    print(f"Loading {len(SYMBOLS)} symbols...")
    symbol_data: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(load_df, s): s for s in SYMBOLS}
        for fut in as_completed(futures):
            sym, df = fut.result()
            if df is not None:
                symbol_data[sym] = df

    print(f"Loaded: {len(symbol_data)} symbols")
    print()

    # Run backtests
    all_bull: list[float] = []
    all_bear: list[float] = []
    symbol_results = []

    for sym, df in symbol_data.items():
        n_btc = len(btc_closes)
        n_alt = len(df)
        aligned_len = min(n_btc, n_alt)

        btc_c = btc_closes[-aligned_len:]
        btc_s = btc_sma[-aligned_len:]
        df_aligned = df.iloc[-aligned_len:].copy()

        res = backtest_symbol(sym, df_aligned, btc_c, btc_s)
        bull_r = res["bull"]
        bear_r = res["bear"]
        all_bull.extend(bull_r)
        all_bear.extend(bear_r)

        if len(bull_r) + len(bear_r) >= MIN_TRADES:
            symbol_results.append({
                "symbol": sym,
                "bull_n": len(bull_r),
                "bull_wr": np.mean(np.array(bull_r) > 0) if bull_r else 0,
                "bull_avg": np.mean(bull_r) * 100 if bull_r else 0,
                "bear_n": len(bear_r),
                "bear_wr": np.mean(np.array(bear_r) > 0) if bear_r else 0,
                "bear_avg": np.mean(bear_r) * 100 if bear_r else 0,
            })

    print("=" * 70)
    print("AGGREGATE RESULTS")
    print("=" * 70)

    bull_sum = summarize(all_bull, "BULL Regime")
    bear_sum = summarize(all_bear, "BEAR Regime")

    print(f"\n{'Regime':<15} {'Trades':>8} {'WR':>8} {'Avg%':>8} {'Sharpe':>10}")
    print("-" * 55)
    for s in [bull_sum, bear_sum]:
        print(
            f"{s['label']:<15} {s['n']:>8} {s['wr']:>7.1%} {s['avg']:>8.2f}% {s['sharpe']:>10.3f}"
        )

    print("\n" + "=" * 70)
    print("PER-SYMBOL RESULTS (sorted by bear avg)")
    print("=" * 70)
    symbol_results.sort(key=lambda x: x["bear_avg"], reverse=True)
    print(
        f"{'Symbol':<18} {'BullN':>6} {'BullWR':>7} {'BullAvg':>8} {'BearN':>6} {'BearWR':>7} {'BearAvg':>8}"
    )
    print("-" * 70)
    for r in symbol_results:
        print(
            f"{r['symbol']:<18} {r['bull_n']:>6} {r['bull_wr']:>6.1%} {r['bull_avg']:>8.2f}% "
            f"{r['bear_n']:>6} {r['bear_wr']:>6.1%} {r['bear_avg']:>8.2f}%"
        )

    print()
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    if bear_sum["sharpe"] > 3.0 and bear_sum["n"] >= 20:
        print("✅ BEAR stealth signal has edge! → Consider BEAR-mode stealth_3gate")
        print(f"   Bear Sharpe={bear_sum['sharpe']:.3f}, WR={bear_sum['wr']:.1%}, n={bear_sum['n']}")
    elif bear_sum["sharpe"] > 1.0 and bear_sum["n"] >= 10:
        print("⚠️  BEAR stealth marginal edge — deeper validation needed")
        print(f"   Bear Sharpe={bear_sum['sharpe']:.3f}, WR={bear_sum['wr']:.1%}, n={bear_sum['n']}")
    else:
        print("❌ BEAR stealth no edge → Gate 1(BTC regime) is ESSENTIAL")
        print(f"   Bear Sharpe={bear_sum['sharpe']:.3f}, WR={bear_sum['wr']:.1%}, n={bear_sum['n']}")
    print()
    if bull_sum["sharpe"] > bear_sum["sharpe"]:
        print(f"ℹ️  Bull >> Bear: Δ Sharpe = {bull_sum['sharpe'] - bear_sum['sharpe']:.3f} (Gate 1 adds value)")
    else:
        print(f"ℹ️  Bear >= Bull: Δ Sharpe = {bear_sum['sharpe'] - bull_sum['sharpe']:.3f} (Gate 1 not needed)")


if __name__ == "__main__":
    main()
