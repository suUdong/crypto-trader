#!/usr/bin/env python3
"""
Cycle 213: Cross-Asset Lead-Lag Analysis
BTC 240m returns → ETH/SOL/XRP returns cross-correlation at lag 1~20 bars (4h~80h).

Phase 1: Statistical analysis — find significant lead-lag relationships
Phase 2: If significant lag found, design BTC-gated entry signal and backtest with 3-fold WF

평가자 지시: [explore] Cross-asset lead-lag (BTC→ALT 선행지표)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd
from scipy import stats
from historical_loader import load_historical

# ── Config ──────────────────────────────────────────────────────────────────
SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP"]
ALT_SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]
CTYPE = "240m"  # 4-hour candles
START = "2023-01-01"
END = "2026-04-05"
MAX_LAG = 20  # bars = 80 hours max
SIGNIFICANCE_LEVEL = 0.05
MIN_BARS_FOR_SIGNIFICANCE = 500

# Also test 60m for finer resolution
CTYPE_60M = "60m"
MAX_LAG_60M = 48  # 48 hours max at 60m resolution


def load_returns(ctype: str, start: str, end: str) -> pd.DataFrame:
    """Load aligned close prices and compute returns."""
    closes: dict[str, pd.Series] = {}
    for sym in SYMBOLS:
        try:
            df = load_historical(sym, ctype, start, end)
            closes[sym] = df["close"]
            print(f"  {sym} @ {ctype}: {len(df)} rows "
                  f"({df.index[0].date()} ~ {df.index[-1].date()})")
        except Exception as e:
            print(f"  {sym} @ {ctype}: FAILED — {e}")
    df_closes = pd.DataFrame(closes).dropna(how="all").ffill()
    returns = df_closes.pct_change().dropna()
    return returns


def cross_correlation_analysis(
    leader_ret: np.ndarray,
    follower_ret: np.ndarray,
    max_lag: int,
) -> list[dict]:
    """Compute cross-correlation at lags 0..max_lag with p-values."""
    results = []
    n = min(len(leader_ret), len(follower_ret))
    for lag in range(max_lag + 1):
        if lag == 0:
            x = leader_ret[:n]
            y = follower_ret[:n]
        else:
            x = leader_ret[:n - lag]
            y = follower_ret[lag:n]
        if len(x) < 30:
            break
        r, p = stats.pearsonr(x, y)
        results.append({
            "lag": lag,
            "corr": round(float(r), 5),
            "p_value": float(p),
            "n": len(x),
            "significant": p < SIGNIFICANCE_LEVEL,
        })
    return results


def directional_lead_lag(
    leader_ret: np.ndarray,
    follower_ret: np.ndarray,
    max_lag: int,
) -> list[dict]:
    """Test: when BTC moves >1σ, does ALT follow at lag k?
    More actionable than raw correlation — measures conditional probability.
    """
    results = []
    n = min(len(leader_ret), len(follower_ret))
    leader_std = np.std(leader_ret[:n])

    for lag in range(1, max_lag + 1):
        if lag >= n:
            break
        # BTC big move up (>1σ) at t → ALT return at t+lag
        big_up_mask = leader_ret[:n - lag] > leader_std
        big_down_mask = leader_ret[:n - lag] < -leader_std

        if big_up_mask.sum() < 10 or big_down_mask.sum() < 10:
            continue

        # After BTC big up: ALT avg return and win rate
        alt_after_up = follower_ret[lag:n][big_up_mask]
        alt_after_down = follower_ret[lag:n][big_down_mask]

        up_wr = float((alt_after_up > 0).mean())
        up_avg = float(alt_after_up.mean())
        down_wr = float((alt_after_down < 0).mean())
        down_avg = float(alt_after_down.mean())

        # Statistical test: is ALT return after BTC big move different from 0?
        t_up, p_up = stats.ttest_1samp(alt_after_up, 0)
        t_down, p_down = stats.ttest_1samp(alt_after_down, 0)

        results.append({
            "lag": lag,
            "n_big_up": int(big_up_mask.sum()),
            "up_wr": round(up_wr, 3),
            "up_avg_ret": round(up_avg * 100, 4),
            "up_p": round(float(p_up), 5),
            "n_big_down": int(big_down_mask.sum()),
            "down_wr": round(down_wr, 3),
            "down_avg_ret": round(down_avg * 100, 4),
            "down_p": round(float(p_down), 5),
        })
    return results


def rolling_lead_lag(
    returns: pd.DataFrame,
    leader: str,
    follower: str,
    lag: int,
    window: int = 90,
) -> pd.Series:
    """Rolling correlation at a fixed lag to check regime stability."""
    n = len(returns)
    corrs = []
    dates = []
    for i in range(window, n - lag):
        x = returns[leader].values[i - window:i]
        y = returns[follower].values[i - window + lag:i + lag]
        r, _ = stats.pearsonr(x, y)
        corrs.append(r)
        dates.append(returns.index[i])
    return pd.Series(corrs, index=dates)


def main():
    print("=" * 80)
    print("Cycle 213: Cross-Asset Lead-Lag Analysis")
    print("BTC 240m → ETH/SOL/XRP 선행지표 탐색")
    print("=" * 80)

    # ── Phase 1A: 240m Cross-Correlation ─────────────────────────────────
    print("\n" + "=" * 80)
    print("Phase 1A: 240m (4h) Cross-Correlation Analysis")
    print("=" * 80)
    returns_240m = load_returns(CTYPE, START, END)
    n_bars = len(returns_240m)
    print(f"\n  Aligned bars: {n_bars}")

    btc_ret = returns_240m["KRW-BTC"].values

    best_lags_240m: dict[str, dict] = {}

    for alt in ALT_SYMBOLS:
        alt_ret = returns_240m[alt].values
        print(f"\n--- BTC → {alt} @ 240m ---")

        # Raw cross-correlation
        cc_results = cross_correlation_analysis(btc_ret, alt_ret, MAX_LAG)
        sig_results = [r for r in cc_results if r["significant"] and r["lag"] > 0]

        if sig_results:
            best = max(sig_results, key=lambda x: abs(x["corr"]))
            print(f"  Best significant lag: {best['lag']} bars "
                  f"({best['lag']*4}h), r={best['corr']:.4f}, "
                  f"p={best['p_value']:.5f}")
            best_lags_240m[alt] = best
        else:
            print("  No significant lead-lag found at 240m")

        # Show top 5 lags by |corr|
        sorted_cc = sorted(cc_results, key=lambda x: abs(x["corr"]), reverse=True)
        print("  Top 5 lags by |corr|:")
        for r in sorted_cc[:5]:
            sig = "✓" if r["significant"] else "✗"
            print(f"    lag={r['lag']:2d} ({r['lag']*4:3d}h): "
                  f"r={r['corr']:+.4f} p={r['p_value']:.4f} [{sig}]")

        # Directional analysis
        print(f"\n  Directional Lead-Lag (BTC >1σ → {alt} at lag):")
        dir_results = directional_lead_lag(btc_ret, alt_ret, MAX_LAG)
        actionable = [r for r in dir_results
                      if (r["up_wr"] > 0.55 and r["up_p"] < 0.10)
                      or (r["down_wr"] > 0.55 and r["down_p"] < 0.10)]

        if actionable:
            for r in actionable[:5]:
                print(f"    lag={r['lag']:2d}: "
                      f"after BTC↑ WR={r['up_wr']:.1%} "
                      f"avg={r['up_avg_ret']:+.3f}% "
                      f"(n={r['n_big_up']}, p={r['up_p']:.3f}) | "
                      f"after BTC↓ WR={r['down_wr']:.1%} "
                      f"avg={r['down_avg_ret']:+.3f}% "
                      f"(n={r['n_big_down']}, p={r['down_p']:.3f})")
        else:
            print("    No actionable directional signals found")

    # ── Phase 1B: 60m Cross-Correlation ──────────────────────────────────
    print("\n" + "=" * 80)
    print("Phase 1B: 60m (1h) Cross-Correlation Analysis")
    print("=" * 80)

    try:
        returns_60m = load_returns(CTYPE_60M, START, END)
        n_bars_60m = len(returns_60m)
        print(f"\n  Aligned bars: {n_bars_60m}")

        btc_ret_60m = returns_60m["KRW-BTC"].values

        best_lags_60m: dict[str, dict] = {}

        for alt in ALT_SYMBOLS:
            alt_ret_60m = returns_60m[alt].values
            print(f"\n--- BTC → {alt} @ 60m ---")

            cc_results_60m = cross_correlation_analysis(
                btc_ret_60m, alt_ret_60m, MAX_LAG_60M
            )
            sig_results_60m = [
                r for r in cc_results_60m if r["significant"] and r["lag"] > 0
            ]

            if sig_results_60m:
                best = max(sig_results_60m, key=lambda x: abs(x["corr"]))
                print(f"  Best significant lag: {best['lag']} bars "
                      f"({best['lag']}h), r={best['corr']:.4f}, "
                      f"p={best['p_value']:.5f}")
                best_lags_60m[alt] = best
            else:
                print("  No significant lead-lag found at 60m")

            sorted_cc_60m = sorted(
                cc_results_60m, key=lambda x: abs(x["corr"]), reverse=True
            )
            print("  Top 5 lags by |corr|:")
            for r in sorted_cc_60m[:5]:
                sig = "✓" if r["significant"] else "✗"
                print(f"    lag={r['lag']:2d} ({r['lag']:3d}h): "
                      f"r={r['corr']:+.4f} p={r['p_value']:.4f} [{sig}]")

            # Directional analysis at 60m
            print(f"\n  Directional Lead-Lag (BTC >1σ → {alt} at lag):")
            dir_results_60m = directional_lead_lag(
                btc_ret_60m, alt_ret_60m, MAX_LAG_60M
            )
            actionable_60m = [
                r for r in dir_results_60m
                if (r["up_wr"] > 0.55 and r["up_p"] < 0.10)
                or (r["down_wr"] > 0.55 and r["down_p"] < 0.10)
            ]
            if actionable_60m:
                for r in actionable_60m[:5]:
                    print(f"    lag={r['lag']:2d}: "
                          f"after BTC↑ WR={r['up_wr']:.1%} "
                          f"avg={r['up_avg_ret']:+.3f}% "
                          f"(n={r['n_big_up']}, p={r['up_p']:.3f}) | "
                          f"after BTC↓ WR={r['down_wr']:.1%} "
                          f"avg={r['down_avg_ret']:+.3f}% "
                          f"(n={r['n_big_down']}, p={r['down_p']:.3f})")
            else:
                print("    No actionable directional signals found")
    except FileNotFoundError:
        print("  60m data not available — skipping")
        best_lags_60m = {}

    # ── Phase 1C: Regime-Conditional Analysis ────────────────────────────
    print("\n" + "=" * 80)
    print("Phase 1C: Regime-Conditional Lead-Lag (Bull vs Bear)")
    print("=" * 80)

    # Define regimes: BTC SMA200 for 240m
    btc_close = pd.DataFrame(
        {"close": load_historical("KRW-BTC", CTYPE, START, END)["close"]}
    )
    btc_close["sma200"] = btc_close["close"].rolling(200).mean()
    btc_close["regime"] = np.where(
        btc_close["close"] > btc_close["sma200"], "bull", "bear"
    )
    btc_close = btc_close.dropna()

    # Align with returns
    common_idx = returns_240m.index.intersection(btc_close.index)
    regime_aligned = btc_close.loc[common_idx, "regime"]
    returns_aligned = returns_240m.loc[common_idx]

    for regime in ["bull", "bear"]:
        mask = regime_aligned == regime
        n_regime = mask.sum()
        print(f"\n  === {regime.upper()} regime (n={n_regime}) ===")

        btc_r = returns_aligned.loc[mask, "KRW-BTC"].values

        for alt in ALT_SYMBOLS:
            alt_r = returns_aligned.loc[mask, alt].values
            dir_results = directional_lead_lag(btc_r, alt_r, 12)
            actionable = [
                r for r in dir_results
                if (r["up_wr"] > 0.55 and r["up_p"] < 0.10)
                or (r["down_wr"] > 0.55 and r["down_p"] < 0.10)
            ]
            if actionable:
                for r in actionable[:3]:
                    print(f"    BTC→{alt.split('-')[1]} lag={r['lag']}: "
                          f"↑WR={r['up_wr']:.1%}(n={r['n_big_up']}) "
                          f"↓WR={r['down_wr']:.1%}(n={r['n_big_down']})")
            else:
                print(f"    BTC→{alt.split('-')[1]}: no actionable signal")

    # ── Phase 1D: Summary ────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("=== SUMMARY ===")
    print("=" * 80)

    any_significant = bool(best_lags_240m) or bool(best_lags_60m)

    print(f"\n  240m significant lead-lags: {len(best_lags_240m)}")
    for alt, info in best_lags_240m.items():
        print(f"    {alt}: lag={info['lag']} ({info['lag']*4}h), "
              f"r={info['corr']:+.4f}")

    print(f"\n  60m significant lead-lags: {len(best_lags_60m)}")
    for alt, info in best_lags_60m.items():
        print(f"    {alt}: lag={info['lag']} ({info['lag']}h), "
              f"r={info['corr']:+.4f}")

    if any_significant:
        print("\n  ✓ Significant lead-lag detected — "
              "BTC-gated entry signal design warranted")
        print("  Next: Phase 2 backtest with BTC lead signal as entry gate")
    else:
        print("\n  ✗ No significant lead-lag detected — "
              "BTC does not reliably lead ALTs at tested timeframes")
        print("  Next: explore alternative alpha axes "
              "(multi-TF ensemble or Kelly sizing)")


if __name__ == "__main__":
    main()
