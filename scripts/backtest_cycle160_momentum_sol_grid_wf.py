"""
momentum_sol 그리드 Top-5 Walk-Forward 검증 — 사이클 160
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: momentum_sol 4h 그리드(540조합) 풀스팬 Sharpe +14.367 도출
      (lookback=20 adx=25 vol=2.0 TP=0.12 SL=0.04, WR=46.8%, trades=79)
      풀스팬 성과는 오버피팅 위험 — 3-fold walk-forward OOS 검증 필요.

목적:
  1) 풀스팬 Top-5 조합을 3-fold OOS 로 재검증
  2) daemon.toml(lb=20 adx=20 vol=1.5 TP=0.08 SL=0.03) 과의 비교
  3) 각 폴드에서 trades/WR/Sharpe/MDD 안전 기준 체크

폴드:
  Fold1 test: 2024-01-01 ~ 2024-12-31
  Fold2 test: 2025-01-01 ~ 2025-12-31
  Fold3 test: 2026-01-01 ~ 2026-12-31

기대: 평균 OOS Sharpe ≥ +3.0 AND 모든 폴드 trades ≥ 10 → 후보 채택.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-SOL"
FEE = 0.0005
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
ENTRY_THRESHOLD = 0.005
MAX_HOLD = 48

# 풀스팬 그리드 Top-5 + 현 daemon 설정
CANDIDATES = [
    # (label, lookback, adx, vol_mult, tp, sl)
    ("grid_top1",    20, 25.0, 2.0, 0.12, 0.04),
    ("grid_top2",    28, 20.0, 2.0, 0.12, 0.02),
    ("grid_top3",    12, 25.0, 2.0, 0.12, 0.04),
    ("grid_top4",    24, 20.0, 2.0, 0.12, 0.02),
    ("grid_top5",    20, 20.0, 2.0, 0.12, 0.02),
    ("daemon_live",  20, 20.0, 1.5, 0.08, 0.03),
]

WF_FOLDS = [
    {"name": "Fold1_2024", "range": ("2024-01-01", "2024-12-31")},
    {"name": "Fold2_2025", "range": ("2025-01-01", "2025-12-31")},
    {"name": "Fold3_2026", "range": ("2026-01-01", "2026-12-31")},
]


# ── 지표 ─────────────────────────────────────────────────────────────────────

def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    out = np.full(len(closes), np.nan)
    if len(gains) < period:
        return out
    ag = gains[:period].mean()
    al = losses[:period].mean()
    out[period] = 100.0 - 100.0 / (1.0 + (ag / (al + 1e-9)))
    for i in range(period + 1, len(closes)):
        ag = (ag * (period - 1) + gains[i - 1]) / period
        al = (al * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 - 100.0 / (1.0 + (ag / (al + 1e-9)))
    return out


def adx_indicator(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    dm_p = np.where(
        (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
        np.maximum(highs[1:] - highs[:-1], 0.0), 0.0,
    )
    dm_m = np.where(
        (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
        np.maximum(lows[:-1] - lows[1:], 0.0), 0.0,
    )
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period - 1] = tr[:period].sum()
    dip_s[period - 1] = dm_p[:period].sum()
    dim_s[period - 1] = dm_m[:period].sum()
    for i in range(period, n - 1):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        dip_s[i] = dip_s[i - 1] - dip_s[i - 1] / period + dm_p[i]
        dim_s[i] = dim_s[i - 1] - dim_s[i - 1] / period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dip_s / (atr_s + 1e-9)
        di_m = 100 * dim_s / (atr_s + 1e-9)
        dx = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2 * period - 2] = dx[period - 1:2 * period - 1].mean()
    for i in range(2 * period - 1, n - 1):
        adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


# ── 백테스트 ─────────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    lookback: int,
    adx_thresh: float,
    vol_mult: float,
    tp: float,
    sl: float,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(c)

    if n < lookback + 60:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "max_consec_loss": 0}

    mom = np.full(n, np.nan)
    mom[lookback:] = c[lookback:] / c[:n - lookback] - 1.0
    rsi_arr = rsi(c, RSI_PERIOD)
    adx_arr = adx_indicator(h, lo, c, 14)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > vol_mult * vol_ma

    returns: list[float] = []
    warmup = max(lookback + RSI_PERIOD + 28, 40)

    i = warmup
    while i < n - 1:
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr[i]) and adx_arr[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = o[i + 1] * (1 + FEE)
            ret = None
            exit_bar = i + 1
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                r = c[j] / buy - 1
                if r >= tp:
                    ret = tp - FEE
                    exit_bar = j
                    break
                if r <= -sl:
                    ret = -sl - FEE
                    exit_bar = j
                    break
            if ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                ret = c[hold_end] / buy - 1 - FEE
                exit_bar = hold_end
            returns.append(ret)
            i = exit_bar
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": len(returns), "max_dd": 0.0, "max_consec_loss": 0}

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    max_dd = float((cum - peak).min())
    max_consec = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd, "max_consec_loss": max_consec,
    }


def main() -> None:
    print("=" * 78)
    print("momentum_sol 그리드 Top-5 Walk-Forward 검증 (사이클 160)")
    print("=" * 78)
    print(f"심볼: {SYMBOL}  타임프레임: 240m\n")

    # Phase 1: 폴드별 결과
    print("=== Phase 1: 폴드별 OOS 성과 ===")
    print(f"{'label':>12} {'fold':>12} {'Sharpe':>8} {'WR':>6} "
          f"{'MDD%':>8} {'cLoss':>6} {'trades':>7}")
    print("-" * 78)

    fold_data = {}
    for fold in WF_FOLDS:
        df = load_historical(SYMBOL, "240m", fold["range"][0], fold["range"][1])
        fold_data[fold["name"]] = df

    agg: dict[str, list[dict]] = {c[0]: [] for c in CANDIDATES}
    for cand in CANDIDATES:
        label, lb, adx_t, vm, tp, sl = cand
        for fold in WF_FOLDS:
            df = fold_data[fold["name"]]
            if df.empty:
                continue
            r = backtest(df, lb, adx_t, vm, tp, sl)
            agg[label].append(r)
            sh = f"{r['sharpe']:+.3f}" if not np.isnan(r["sharpe"]) else "    nan"
            print(
                f"{label:>12} {fold['name']:>12} {sh:>8} {r['wr']:>5.1%} "
                f"{r['max_dd'] * 100:>+7.2f}% {r['max_consec_loss']:>6} "
                f"{r['trades']:>7}"
            )
        print()

    # Phase 2: 후보별 평균
    print("=== Phase 2: 후보별 평균 OOS ===")
    print(f"{'label':>12} {'avgSharpe':>10} {'avgWR':>7} "
          f"{'totTrades':>10} {'minFoldTr':>10} {'status':>8}")
    print("-" * 78)
    summary = []
    for cand in CANDIDATES:
        label, lb, adx_t, vm, tp, sl = cand
        rs = [r for r in agg[label] if not np.isnan(r["sharpe"])]
        if not rs:
            print(f"{label:>12}  (데이터 부족)")
            continue
        avg_sh = float(np.mean([r["sharpe"] for r in rs]))
        avg_wr = float(np.mean([r["wr"] for r in rs]))
        tot_tr = sum(r["trades"] for r in rs)
        min_tr = min(r["trades"] for r in rs)
        status = "PASS" if (avg_sh >= 3.0 and min_tr >= 10) else "FAIL"
        summary.append((label, avg_sh, avg_wr, tot_tr, min_tr, status, cand))
        print(
            f"{label:>12} {avg_sh:>+10.3f} {avg_wr:>6.1%} "
            f"{tot_tr:>10} {min_tr:>10} {status:>8}"
        )

    # Phase 3: 승자
    passes = [s for s in summary if s[5] == "PASS"]
    passes.sort(key=lambda s: s[1], reverse=True)
    print("\n=== Phase 3: 승자 ===")
    if passes:
        w = passes[0]
        _, _, lb, adx_t, vm, tp, sl = w[6]
        print(f"  ★ {w[0]}: lb={lb} adx={adx_t} vol={vm} TP={tp} SL={sl}")
        print(f"    평균 OOS Sharpe={w[1]:+.3f}  WR={w[2]:.1%}  "
              f"총 trades={w[3]}  최소 폴드 trades={w[4]}")
        final_sh, final_wr, final_tr = w[1], w[2] * 100, w[3]
    else:
        print("  (PASS 후보 없음 — 풀스팬 최적이 OOS 에서 유지되지 않음)")
        if summary:
            summary.sort(key=lambda s: s[1], reverse=True)
            b = summary[0]
            final_sh, final_wr, final_tr = b[1], b[2] * 100, b[3]
        else:
            final_sh, final_wr, final_tr = 0.0, 0.0, 0

    print(f"\nSharpe: {final_sh:+.3f}")
    print(f"WR: {final_wr:.1f}%")
    print(f"trades: {final_tr}")


if __name__ == "__main__":
    main()
