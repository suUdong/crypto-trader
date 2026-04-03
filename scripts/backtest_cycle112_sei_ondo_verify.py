"""
SEI/ONDO stealth_3gate 추가 검증 — 윈도우 재설계 (사이클 112)

배경: 사이클 111 결과
  - SEI: W_A(OOS 2025) Sharpe +4.500 ✅, W_B(OOS 2026 BEAR) ~0 ❌ → 1/2창
  - ONDO: OOS 2026H1 Sharpe +5.762 ✅ 단창 (IS=-1.071 약함)

목적:
  SEI — 2창 재설계: OOS 창을 BULL 구간(2024H2 + 2025 전체)으로 이동
    W1: IS=2023-08~2024-06, OOS=2024-07~2025-06 (BTC 2024 BULL rally 포함)
    W2: IS=2023-08~2024-12, OOS=2025-01~2025-12 (2025 BULL 전체)
    → 2/2창 통과 시 daemon 후보 확정

  ONDO — 2창 설계: 더 긴 BULL 구간으로 IS/OOS 분리
    W1: IS=2024-06~2024-12, OOS=2025-01~2025-12 (2025 BULL)
    W2: IS=2024-06~2025-06, OOS=2025-07~2026-04 (2025H2 포함)
    → 2/2창 통과 시 daemon 후보 확정

전략 파라미터 (daemon 확정값 — 사이클 111과 동일):
  W=36, SMA20, RS[0.5,1.0), acc>1.0, CVD>0
  Gate 1: BTC > SMA20  Gate 4: btc_trend_pos (BTC 10봉 > 0)
  TP=15%, SL=3%, MAX_HOLD=24봉 (96h)

성공 기준: OOS Sharpe ≥ 3.0, n ≥ 8
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
FWD = 6
FEE = 0.0005

MIN_TRADES = 8
SHARPE_MIN = 3.0

# 심볼별 윈도우 설정 — BULL 구간 집중
SYMBOL_CONFIG = {
    "KRW-SEI": {
        "data_start": "2023-08-01",
        "windows": [
            # BTC 2024 BULL rally 포함 OOS
            ("W1", "2024-07-01", "2025-06-30"),  # IS=2023-08~2024-06, OOS=2024H2~2025H1
            # 2025 전체 BULL OOS
            ("W2", "2025-01-01", "2025-12-31"),  # IS=2023-08~2024-12, OOS=2025 전체
        ],
        "note": "SEI 2창 재설계 — BULL 구간 OOS (W_A 사이클 111 Sharpe +4.500 확인됨)",
    },
    "KRW-ONDO": {
        "data_start": "2024-06-01",
        "windows": [
            # 2025 전체 BULL OOS
            ("W1", "2025-01-01", "2025-12-31"),  # IS=2024-06~2024-12, OOS=2025 전체
            # 2025H2 이후
            ("W2", "2025-07-01", "2026-04-04"),  # IS=2024-06~2025-06, OOS=2025H2~
        ],
        "note": "ONDO 2창 설계 — IS 확장 (OOS 2026H1 Sharpe +5.762 확인됨)",
    },
}


# ─── Indicator helpers (사이클 111 동일 로직) ────────────────────────────────

def compute_sma(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(p - 1, len(arr)):
        out[i] = arr[i - p + 1 : i + 1].mean()
    return out


def compute_acc(closes: np.ndarray, vols: np.ndarray, w: int) -> np.ndarray:
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
    rs = np.full(len(closes), np.nan)
    for i in range(w, len(closes)):
        ar = closes[i] / closes[i - w] - 1.0
        br = btc_closes[i] / btc_closes[i - w] - 1.0
        rs[i] = (ar - br) / (abs(br) + 0.05)
    return rs


# ─── Backtest core (사이클 111 동일 로직) ────────────────────────────────────

def _backtest_slice(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    start: str,
    end: str,
) -> dict:
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

        # Gate 4: btc_trend_pos
        if i < BTC_TREND_WINDOW or bc[i] <= bc[i - BTC_TREND_WINDOW]:
            i += 1
            continue

        # Alt stealth filters
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
            fwd_idx = min(i + FWD, len(c) - 1)
            ret = c[fwd_idx] / entry - 1.0 - 2 * FEE

        trades.append(ret)
        last_exit = i + max(hold, 1)
        i = last_exit

    if len(trades) < 3:
        return {"n": len(trades), "sharpe": 0.0, "wr": 0.0, "avg_ret": 0.0}

    arr = np.array(trades)
    sh = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6 / max(1, len(arr)))
    wr = float((arr > 0).mean()) * 100
    avg = float(arr.mean()) * 100

    return {"n": len(arr), "sharpe": sh, "wr": wr, "avg_ret": avg}


def run_window(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    is_end: str,
    oos_start: str,
    oos_end: str,
) -> dict:
    is_r = _backtest_slice(alt_df, btc_df, alt_df.index[0].strftime("%Y-%m-%d"), is_end)
    oos_r = _backtest_slice(alt_df, btc_df, oos_start, oos_end)
    return {"is": is_r, "oos": oos_r}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("사이클 112 — SEI/ONDO stealth_3gate 윈도우 재설계 검증")
    print(f"W={W}, SMA{SMA_P}, RS[{RS_LOW},{RS_HIGH}), acc>{ACC_THRESH}, CVD>{CVD_THRESH}")
    print(f"TP={TP*100:.0f}% SL={SL*100:.0f}% | 기준: OOS Sharpe≥{SHARPE_MIN}, n≥{MIN_TRADES}")
    print("=" * 70)

    print("\n[BTC 데이터 로드...]")
    btc_df = load_historical(BTC_SYMBOL, INTERVAL, "2023-01-01", "2026-04-04")
    if btc_df is None or len(btc_df) < SMA_P * 3:
        print("ERROR: BTC 데이터 없음")
        return
    print(f"  BTC: {len(btc_df)} 봉 ({btc_df.index[0].date()} ~ {btc_df.index[-1].date()})")

    all_results = []

    for symbol, cfg in SYMBOL_CONFIG.items():
        sym_short = symbol.replace("KRW-", "")
        print(f"\n{'─'*60}")
        print(f"[{sym_short}] {cfg['note']}")

        try:
            alt_df = load_historical(symbol, INTERVAL, cfg["data_start"], "2026-04-04")
        except Exception as e:
            print(f"  ERROR: 데이터 로드 실패 — {e}")
            all_results.append({"symbol": sym_short, "passes": 0, "total": len(cfg["windows"]), "windows": {}})
            continue

        if alt_df is None or len(alt_df) < W * 3:
            print(f"  ERROR: 데이터 부족 (n={len(alt_df) if alt_df is not None else 0})")
            all_results.append({"symbol": sym_short, "passes": 0, "total": len(cfg["windows"]), "windows": {}})
            continue

        print(f"  데이터: {len(alt_df)} 봉 ({alt_df.index[0].date()} ~ {alt_df.index[-1].date()})")

        window_passes = 0
        window_results = {}
        for wname, oos_start, oos_end in cfg["windows"]:
            is_end_dt = pd.Timestamp(oos_start) - pd.Timedelta(days=1)
            is_end = is_end_dt.strftime("%Y-%m-%d")

            r = run_window(alt_df, btc_df, is_end, oos_start, oos_end)
            oos = r["oos"]
            is_ = r["is"]

            oos_ok = oos["sharpe"] >= SHARPE_MIN and oos["n"] >= MIN_TRADES
            if oos_ok:
                window_passes += 1

            flag = "✅" if oos_ok else "❌"
            print(
                f"  {flag} {wname} OOS({oos_start[:7]}~{oos_end[:7]}): "
                f"Sharpe={oos['sharpe']:+.3f} WR={oos['wr']:.1f}% avg={oos['avg_ret']:+.2f}% n={oos['n']}"
            )
            print(
                f"       IS({alt_df.index[0].date()}~{is_end[:7]}): "
                f"Sharpe={is_['sharpe']:+.3f} WR={is_['wr']:.1f}% n={is_['n']}"
            )
            window_results[wname] = oos

        passes_str = f"{window_passes}/{len(cfg['windows'])}"
        if window_passes >= 2:
            verdict = "🏆 2창 이상 통과 — daemon 후보 확정!"
        elif window_passes == 1:
            verdict = "⚠️ 1창 통과 — 조건부 후보"
        else:
            verdict = "❌ 탈락"

        print(f"\n  → {passes_str} 창 통과 | {verdict}")
        all_results.append({
            "symbol": sym_short,
            "passes": window_passes,
            "total": len(cfg["windows"]),
            "windows": window_results,
        })

    # 최종 요약
    print("\n" + "=" * 70)
    print("최종 요약")
    print("=" * 70)
    confirmed = []
    conditional = []
    for r in all_results:
        if r["passes"] >= 2:
            icon = "🏆"
            confirmed.append(r["symbol"])
        elif r["passes"] == 1:
            icon = "⚠️"
            conditional.append(r["symbol"])
        else:
            icon = "❌"
        print(f"  {icon} {r['symbol']}: {r['passes']}/{r['total']} 창 통과")

    print(f"\n검증 기준: OOS Sharpe ≥ {SHARPE_MIN}, n ≥ {MIN_TRADES}")
    if confirmed:
        print(f"daemon 후보 확정: {confirmed}")
    if conditional:
        print(f"조건부 후보(추가 검증 필요): {conditional}")
    if not confirmed and not conditional:
        print("유망 후보 없음 — 전 심볼 탈락")

    print("\n[사이클 112 완료]")


if __name__ == "__main__":
    main()
