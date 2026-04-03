"""
신규 심볼 BULL stealth_3gate walk-forward 스크리닝 (사이클 109)

가설: 미탐색 심볼(POL/TRX/AAVE/NEAR + RENDER/SUI) 에서
      stealth_3gate BULL 조건이 유효한 엣지를 갖는가?

현재 daemon stealth_3gate_wallet_1 심볼: AVAX, LINK, APT, XRP, ADA, DOT, ATOM
→ 이 스크립트는 추가 후보 발굴 목적

설정:
  - W=36, SMA20, RS[0.5,1.0), acc>1.0, CVD>0 (daemon 확정 파라미터)
  - Gate 1: BTC > SMA20 (BULL 레짐)
  - Gate 4: btc_trend_pos (BTC 10봉 수익률 > 0)
  - TP=15%, SL=3%, MAX_HOLD=24봉 (96h)
  - Walk-forward: 3창 (full) 또는 2창 (newer symbols)

성공 기준: Sharpe > 3.0, n >= 8, 2/3 창 이상 통과
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical

INTERVAL = "240m"
BTC_SYMBOL = "KRW-BTC"

# Daemon 확정 파라미터
W = 36
SMA_P = 20
RS_LOW = 0.5
RS_HIGH = 1.0
CVD_THRESH = 0.0
ACC_THRESH = 1.0
BTC_TREND_WINDOW = 10

TP = 0.15
SL = 0.03
MAX_HOLD = 24   # 24 * 4h = 96h
FWD = 6         # fallback forward (24h)
FEE = 0.0005    # per side

MIN_TRADES = 8
SHARPE_MIN = 3.0

# Full 3-window (2022년부터 데이터)
FULL_SYMBOLS = ["KRW-POL", "KRW-TRX", "KRW-AAVE", "KRW-NEAR"]

# Partial 2-window (2024년부터 데이터)
PARTIAL_SYMBOLS = ["KRW-RENDER", "KRW-SUI"]

# Walk-forward windows
W3_WINDOWS = [
    ("W1", "2022-01-01", "2024-03-31"),
    ("W2", "2023-06-01", "2025-03-31"),
    ("W3", "2024-06-01", "2026-04-04"),
]
W2_WINDOWS = [
    ("W2", "2023-10-01", "2025-03-31"),
    ("W3", "2024-06-01", "2026-04-04"),
]


# ─── Indicator helpers (검증된 backtest 공식 사용) ─────────────────────────

def compute_sma(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(p - 1, len(arr)):
        out[i] = arr[i - p + 1 : i + 1].mean()
    return out


def compute_acc(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    """VPIN acceleration: recent buy-vol ratio / prior buy-vol ratio."""
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    vpin = np.concatenate([[np.nan], buy / (vols[1:] + 1e-9)])
    acc = np.full(len(closes), np.nan)
    for i in range(w * 2, len(closes)):
        recent_mean = np.nanmean(vpin[i - w : i])
        older_mean = np.nanmean(vpin[i - w * 2 : i - w])
        acc[i] = recent_mean / (older_mean + 1e-9)
    return acc


def compute_cvd_slope(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
    """CVD slope normalized by avg volume."""
    dir_ = np.where(closes[1:] >= closes[:-1], 1.0, -1.0)
    buy = np.where(dir_ > 0, vols[1:], 0.0)
    cvd = np.cumsum(buy - vols[1:] / 2)
    cvd = np.concatenate([[0.0], cvd])
    slopes = np.full(len(closes), np.nan)
    avg_v = np.mean(vols)
    for i in range(w, len(closes)):
        slopes[i] = (cvd[i] - cvd[i - w]) / (avg_v + 1e-9)
    return slopes


def compute_rs(closes: np.ndarray, btc_closes: np.ndarray, w: int) -> np.ndarray:
    """Relative strength: (alt_ret - btc_ret) / (abs(btc_ret) + 0.05)"""
    rs = np.full(len(closes), np.nan)
    for i in range(w, len(closes)):
        ar = closes[i] / closes[i - w] - 1.0
        br = btc_closes[i] / btc_closes[i - w] - 1.0
        rs[i] = (ar - br) / (abs(br) + 0.05)
    return rs


# ─── Backtest per window ───────────────────────────────────────────────────

def run_window(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    start: str,
    end: str,
) -> dict:
    """Run stealth_3gate BULL backtest (TP/SL exit) on one time window."""
    # Align alt & BTC to same index
    merged_alt = alt_df[(alt_df.index >= start) & (alt_df.index <= end)]
    btc_w = btc_df[(btc_df.index >= start) & (btc_df.index <= end)]
    btc_aligned = btc_w.reindex(merged_alt.index, method="ffill")

    if len(merged_alt) < W * 3 or len(btc_aligned) < W * 3:
        return {"n": 0, "sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0}

    c = merged_alt["close"].values
    v = merged_alt["volume"].values
    bc = btc_aligned["close"].values

    btc_sma = compute_sma(bc, SMA_P)
    acc = compute_acc(c, v, W)
    cvd = compute_cvd_slope(c, v, W)
    rs = compute_rs(c, bc, W)

    trades: list[float] = []
    i = W * 2
    last_exit = 0

    while i < len(c) - FWD - 1:
        if i < last_exit:
            i += 1
            continue

        # Gate 1: BTC > SMA20
        if np.isnan(btc_sma[i]) or bc[i] <= btc_sma[i]:
            i += 1
            continue

        # Gate 4: btc_trend_pos (BTC 10봉 수익률 > 0)
        if i < BTC_TREND_WINDOW or bc[i] <= bc[i - BTC_TREND_WINDOW]:
            i += 1
            continue

        # Gate 3: alt stealth (acc > 1.0, CVD > 0, RS in [0.5, 1.0))
        if any(np.isnan(x) for x in [acc[i], cvd[i], rs[i]]):
            i += 1
            continue
        if acc[i] <= ACC_THRESH or cvd[i] <= CVD_THRESH:
            i += 1
            continue
        if not (RS_LOW <= rs[i] < RS_HIGH):
            i += 1
            continue

        entry = c[i]
        tp_p = entry * (1 + TP)
        sl_p = entry * (1 - SL)
        ret = None
        hold = 0

        for j in range(i + 1, min(i + MAX_HOLD + 1, len(c))):
            price = c[j]
            hold += 1
            if price >= tp_p:
                ret = TP - 2 * FEE
                break
            elif price <= sl_p:
                ret = -SL - 2 * FEE
                break

        if ret is None:
            # FWD return if neither TP nor SL hit
            fwd_idx = min(i + FWD, len(c) - 1)
            ret = c[fwd_idx] / entry - 1.0 - 2 * FEE

        trades.append(ret)
        last_exit = i + max(hold, 1)
        i = last_exit

    if len(trades) < MIN_TRADES:
        return {"n": len(trades), "sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0}

    arr = np.array(trades)
    sh = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6 / max(1, len(arr)))
    wr = float((arr > 0).mean()) * 100
    avg = float(arr.mean()) * 100

    return {"n": len(trades), "sharpe": sh, "wr": wr, "avg_ret": avg}


# ─── Symbol screening ─────────────────────────────────────────────────────

def screen(symbol: str, windows: list[tuple[str, str, str]], btc_df: pd.DataFrame) -> dict:
    load_start = windows[0][1]
    try:
        df = load_historical(symbol, INTERVAL, load_start, "2026-04-04")
    except Exception:
        return {"symbol": symbol, "error": "load_failed"}

    if df is None or len(df) < W * 3:
        return {"symbol": symbol, "error": "no_data"}

    results = {}
    passes = 0
    for name, start, end in windows:
        r = run_window(df, btc_df, start, end)
        results[name] = r
        if r["sharpe"] >= SHARPE_MIN and r["n"] >= MIN_TRADES:
            passes += 1

    return {
        "symbol": symbol,
        "windows": results,
        "passes": passes,
        "total": len(windows),
    }


def print_result(r: dict) -> None:
    sym = r["symbol"].replace("KRW-", "")
    if "error" in r:
        print(f"  ✗ {sym}: ERROR({r['error']})")
        return
    passes = r["passes"]
    total = r["total"]
    icon = "🏆" if passes >= 2 else ("⚠️" if passes == 1 else "❌")
    print(f"  {icon} {sym}: {passes}/{total} 창 통과")
    for wname, wr in r["windows"].items():
        flag = "✅" if wr["sharpe"] >= SHARPE_MIN and wr["n"] >= MIN_TRADES else "❌"
        print(
            f"     {flag} {wname}: Sharpe={wr['sharpe']:+.3f} WR={wr['wr']:.1f}%"
            f" avg={wr['avg_ret']:+.2f}% n={wr['n']}"
        )


def main() -> None:
    print("=" * 70)
    print("신규 심볼 BULL stealth_3gate Walk-Forward 스크리닝 (사이클 109)")
    print(f"파라미터: W={W}, SMA{SMA_P}, RS[{RS_LOW},{RS_HIGH})")
    print(f"TP={TP*100:.0f}% SL={SL*100:.0f}% | 기준: Sharpe≥{SHARPE_MIN}, n≥{MIN_TRADES}")
    print("=" * 70)

    print("\n[BTC 4h 데이터 로드 중...]")
    btc_df = load_historical(BTC_SYMBOL, INTERVAL, "2022-01-01", "2026-04-04")
    if btc_df is None or len(btc_df) < SMA_P * 3:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC: {len(btc_df)} 봉 ({btc_df.index[0].date()} ~ {btc_df.index[-1].date()})")

    # Full 3-window
    print(f"\n[Full 3-Window (2022~) — {FULL_SYMBOLS}]")
    full_results = []
    for sym in FULL_SYMBOLS:
        print(f"  → {sym} ...", end="", flush=True)
        r = screen(sym, W3_WINDOWS, btc_df)
        full_results.append(r)
        print()
        print_result(r)

    # Partial 2-window
    print(f"\n[Partial 2-Window (2024~) — {PARTIAL_SYMBOLS}]")
    partial_results = []
    for sym in PARTIAL_SYMBOLS:
        print(f"  → {sym} ...", end="", flush=True)
        r = screen(sym, W2_WINDOWS, btc_df)
        partial_results.append(r)
        print()
        print_result(r)

    # Summary
    all_results = full_results + partial_results
    qualified = [r for r in all_results if "error" not in r and r["passes"] >= 2]

    print("\n" + "=" * 70)
    print("최종 요약")
    print("=" * 70)
    for r in all_results:
        if "error" in r:
            continue
        sym = r["symbol"].replace("KRW-", "")
        icon = "🏆" if r["passes"] >= 2 else ("⚠️" if r["passes"] == 1 else "❌")
        print(f"  {icon} {sym}: {r['passes']}/{r['total']} 창 통과")

    print(f"\n합격 후보 ({SHARPE_MIN}+ Sharpe, 2/N 창 통과): {len(qualified)}개")
    for r in qualified:
        sym = r["symbol"].replace("KRW-", "")
        best_sh = max(
            (v["sharpe"] for v in r["windows"].values() if v["n"] >= MIN_TRADES),
            default=0.0,
        )
        best_wr = max(
            (v["wr"] for v in r["windows"].values() if v["n"] >= MIN_TRADES),
            default=0.0,
        )
        print(f"  ★ {sym}: 최고 Sharpe={best_sh:+.3f}, 최고 WR={best_wr:.1f}%")

    if qualified:
        print("\n→ daemon.toml stealth_3gate_wallet_1 추가 후보 발굴!")
    else:
        print("\n→ 합격 후보 없음")
        print("  분석: BULL 레짐에서 신규 심볼 stealth 엣지 부족")
        print("  다음 방향: momentum_sol BULL 전환 조건 문서화 또는 레짐별 성과 재분석")


if __name__ == "__main__":
    main()
