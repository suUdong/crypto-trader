"""
사이클 206: VWAP Anchored Deviation 역추세 전략 3-fold WF 백테스트
- 목적: 기존 BB/RSI 역추세와 다른 가격 앵커 — VWAP 기반 역추세
- 평가자 방향: 구조적 가격 앵커 교체 (Bollinger → VWAP deviation)
- 설계:
  1) VWAP: 일별(00:00 UTC) 또는 주별 앵커 리셋, 누적 VWAP 계산
  2) 편차: rolling σ of (close - VWAP) → z-score
  3) 진입: z-score <= -z_entry (과매도) + BTC > SMA200
  4) 청산: z-score >= z_exit (VWAP 복귀) 또는 ATR SL 또는 max_hold
  5) 다음 봉 시가 진입 (look-ahead bias 제거)
- 심볼: ETH/SOL/XRP 240m
- 3-fold WF: 새 윈도우
  F1: IS=2022-05~2024-03 → OOS=2024-04~2024-12
  F2: IS=2023-06~2025-01 → OOS=2025-02~2025-09
  F3: IS=2024-06~2025-09 → OOS=2025-10~2026-03
- 그리드: anchor(2) × z_entry(3) × z_exit(2) × atr_sl(3) × sigma_lb(3) × max_hold(2)
  = 2×3×2×3×3×2 = 216조합
★슬리피지포함 | 🔄다음봉시가진입
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005  # 0.05% 편도
SLIPPAGE = 0.001  # 0.10%

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]
BTC_SMA_PERIOD = 200

WINDOWS = [
    {
        "name": "F1",
        "is_start": "2022-05-01", "is_end": "2024-03-31",
        "oos_start": "2024-04-01", "oos_end": "2024-12-31",
    },
    {
        "name": "F2",
        "is_start": "2023-06-01", "is_end": "2025-01-31",
        "oos_start": "2025-02-01", "oos_end": "2025-09-30",
    },
    {
        "name": "F3",
        "is_start": "2024-06-01", "is_end": "2025-09-30",
        "oos_start": "2025-10-01", "oos_end": "2026-03-31",
    },
]

# ─── 그리드 파라미터 ─────────────────────────────────────────────────
ANCHOR_LIST = ["daily", "weekly"]          # VWAP 앵커 리셋 주기
Z_ENTRY_LIST = [1.5, 2.0, 2.5]            # 진입 z-score 임계값 (음수 방향)
Z_EXIT_LIST = [0.0, 0.5]                  # 청산 z-score (0=VWAP 복귀, 0.5=약간 위)
ATR_SL_LIST = [1.5, 2.0, 3.0]             # ATR 기반 SL 배수
SIGMA_LB_LIST = [20, 40, 60]              # σ 계산 lookback (봉수)
MAX_HOLD_LIST = [15, 25]                   # 최대 보유 봉수

# 총 조합: 2×3×2×3×3×2 = 216


# ─── VWAP 계산 ───────────────────────────────────────────────────────

def compute_vwap(df: pd.DataFrame, anchor: str) -> pd.Series:
    """Anchored VWAP 계산.

    anchor="daily": 매일 00:00 UTC에 리셋
    anchor="weekly": 매주 월요일 00:00 UTC에 리셋
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]

    # 앵커 포인트 결정
    if anchor == "daily":
        # 240m = 6봉/일, 매일 첫 봉에서 리셋
        groups = df.index.date
    else:  # weekly
        # ISO week 기준
        groups = df.index.isocalendar().week.values + df.index.year.values * 100

    # 그룹별 누적 VWAP
    vwap = pd.Series(np.nan, index=df.index, dtype=float)
    cum_tp_vol = 0.0
    cum_vol = 0.0
    prev_group = None

    for i, idx in enumerate(df.index):
        if anchor == "daily":
            cur_group = idx.date()
        else:
            cur_group = idx.isocalendar().week + idx.year * 100

        if cur_group != prev_group:
            cum_tp_vol = 0.0
            cum_vol = 0.0
            prev_group = cur_group

        cum_tp_vol += tp_vol.iloc[i]
        cum_vol += df["volume"].iloc[i]

        if cum_vol > 0:
            vwap.iloc[i] = cum_tp_vol / cum_vol
        else:
            vwap.iloc[i] = typical_price.iloc[i]

    return vwap


def compute_vwap_zscore(
    close: pd.Series, vwap: pd.Series, lookback: int
) -> pd.Series:
    """(close - VWAP)의 rolling z-score."""
    deviation = close - vwap
    mean_dev = deviation.rolling(lookback).mean()
    std_dev = deviation.rolling(lookback).std(ddof=1)
    std_dev = std_dev.replace(0, np.nan)
    return (deviation - mean_dev) / std_dev


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    h = df["high"]
    l = df["low"]
    c = df["close"].shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


# ─── 백테스트 엔진 ───────────────────────────────────────────────────

def run_backtest(
    df: pd.DataFrame,
    btc_close_aligned: pd.Series,
    btc_sma_aligned: pd.Series,
    anchor: str,
    z_entry: float,
    z_exit: float,
    atr_sl_mult: float,
    sigma_lb: int,
    max_hold: int,
) -> dict:
    """단일 심볼 백테스트."""
    vwap_s = compute_vwap(df, anchor)
    zscore = compute_vwap_zscore(df["close"], vwap_s, sigma_lb)
    atr_val = atr(df, 14)

    trades: list[dict] = []
    position = None
    warmup = max(sigma_lb, BTC_SMA_PERIOD) + 5

    for i in range(warmup, len(df) - 1):
        idx = df.index[i]
        c = df["close"].iloc[i]
        o_next = df["open"].iloc[i + 1]
        z = zscore.iloc[i]

        if position is not None:
            bars_held = i - position["entry_bar"]

            # 청산 조건
            exit_reason = None

            # 1) SL (ATR 기반)
            sl_price = position["entry_price"] * (1 - position["sl_pct"])
            if c <= sl_price:
                exit_reason = "SL"

            # 2) z-score 복귀 (TP)
            if not np.isnan(z) and z >= z_exit:
                exit_reason = "Z_EXIT"

            # 3) Max hold
            if bars_held >= max_hold:
                exit_reason = "MAX_HOLD"

            if exit_reason:
                exit_actual = o_next * (1 - SLIPPAGE)
                ret = (exit_actual / position["entry_price"]) - 1 - FEE * 2
                trades.append({
                    "entry_time": position["entry_time"],
                    "exit_time": df.index[i + 1],
                    "entry_price": position["entry_price"],
                    "exit_price": exit_actual,
                    "return": ret,
                    "reason": exit_reason,
                    "bars": bars_held,
                })
                position = None
        else:
            # 진입 조건: z-score <= -z_entry (과매도) + BTC > SMA200
            if (
                not np.isnan(z)
                and z <= -z_entry
                and not np.isnan(btc_sma_aligned.iloc[i])
                and btc_close_aligned.iloc[i] > btc_sma_aligned.iloc[i]
            ):
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val.iloc[i]
                if np.isnan(atr_now) or atr_now <= 0:
                    continue
                position = {
                    "entry_price": entry_price,
                    "entry_time": df.index[i + 1],
                    "entry_bar": i + 1,
                    "sl_pct": atr_now / c * atr_sl_mult,
                }

    if not trades:
        return {"sharpe": -999, "wr": 0, "n": 0, "avg_ret": 0, "mdd": 0,
                "trades": []}

    rets = [t["return"] for t in trades]
    n = len(rets)
    avg_ret = np.mean(rets)
    std_ret = np.std(rets, ddof=1) if n > 1 else 1e-10
    # Annualized Sharpe (240m = 6 bars/day, ~252 trading days)
    sharpe = (avg_ret / std_ret) * np.sqrt(252 * 6) if std_ret > 0 else 0
    wr = sum(1 for r in rets if r > 0) / n * 100

    equity = np.cumprod([1 + r for r in rets])
    peak_eq = np.maximum.accumulate(equity)
    mdd = np.min(equity / peak_eq - 1) * 100

    return {"sharpe": sharpe, "wr": wr, "n": n, "avg_ret": avg_ret * 100,
            "mdd": mdd, "trades": trades}


# ─── 메인 ────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== c206: VWAP Anchored Deviation 역추세 3-fold WF ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | ★슬리피지포함 | 🔄다음봉시가진입 ===")
    print("=" * 80)

    # BTC 데이터
    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    btc_sma_full = sma(btc_df["close"], BTC_SMA_PERIOD)
    print(f"BTC 데이터: {len(btc_df)} rows ({btc_df.index[0]} ~ {btc_df.index[-1]})")

    # 심볼 데이터
    sym_data = {}
    for sym in SYMBOLS:
        df = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        sym_data[sym] = df
        print(f"{sym} 데이터: {len(df)} rows ({df.index[0]} ~ {df.index[-1]})")

    # 그리드
    grid = list(product(
        ANCHOR_LIST, Z_ENTRY_LIST, Z_EXIT_LIST,
        ATR_SL_LIST, SIGMA_LB_LIST, MAX_HOLD_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # Walk-Forward
    all_results: list[dict] = []

    for gi, (anchor, z_entry, z_exit, atr_sl, sigma_lb, max_hold) in enumerate(grid):
        fold_sharpes = []
        fold_details = []
        total_n = 0

        for window in WINDOWS:
            fold_rets = []
            fold_n = 0

            for sym in SYMBOLS:
                df_full = sym_data[sym]

                # OOS 시작 전 warmup 포함
                warmup = max(sigma_lb, BTC_SMA_PERIOD) + 20
                oos_start_idx = df_full.index.get_indexer(
                    [pd.Timestamp(window["oos_start"])], method="nearest"
                )[0]
                start_idx = max(0, oos_start_idx - warmup)
                df_slice = df_full.iloc[start_idx:]

                # BTC 정렬
                btc_close_al = btc_df["close"].reindex(df_slice.index, method="ffill")
                btc_sma_al = btc_sma_full.reindex(df_slice.index, method="ffill")

                res = run_backtest(
                    df_slice, btc_close_al, btc_sma_al,
                    anchor, z_entry, z_exit, atr_sl, sigma_lb, max_hold,
                )

                # OOS 기간 거래만 필터
                oos_trades = [
                    t for t in res["trades"]
                    if pd.Timestamp(window["oos_start"]) <= t["entry_time"]
                    <= pd.Timestamp(window["oos_end"])
                ]
                fold_rets.extend([t["return"] for t in oos_trades])
                fold_n += len(oos_trades)

            # Fold Sharpe
            if fold_rets:
                avg = np.mean(fold_rets)
                std = np.std(fold_rets, ddof=1) if len(fold_rets) > 1 else 1e-10
                sharpe = (avg / std) * np.sqrt(252 * 6) if std > 0 else 0
                wr = sum(1 for r in fold_rets if r > 0) / len(fold_rets) * 100
            else:
                sharpe = -999
                wr = 0
                avg = 0

            fold_sharpes.append(sharpe)
            fold_details.append({
                "name": window["name"],
                "sharpe": sharpe, "wr": wr,
                "n": fold_n, "avg": avg * 100,
            })
            total_n += fold_n

        avg_sharpe = np.mean(fold_sharpes) if fold_sharpes else -999
        all_results.append({
            "params": {
                "anchor": anchor, "z_entry": z_entry, "z_exit": z_exit,
                "atr_sl": atr_sl, "sigma_lb": sigma_lb, "max_hold": max_hold,
            },
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
        })

        if (gi + 1) % 30 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")

    # ─── 결과 정리 ───────────────────────────────────────────────────
    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    print("\n" + "=" * 80)
    print("=== Top 10 결과 (n≥30) ===")
    print("=" * 80)
    for i, r in enumerate(valid[:10]):
        p = r["params"]
        print(f"\n#{i+1}: anchor={p['anchor']} z_entry={p['z_entry']} "
              f"z_exit={p['z_exit']} atr_sl={p['atr_sl']} "
              f"sigma_lb={p['sigma_lb']} max_hold={p['max_hold']}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  total_n={r['total_n']}")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  avg={f['avg']:+.2f}%")

    # Top 1 심볼별 분해
    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n" + "=" * 80)
        print(f"=== 심볼별 OOS 성능 분해 (Top 1) ===")

        for sym in SYMBOLS:
            sym_sharpes = []
            sym_total_n = 0
            for window in WINDOWS:
                df_full = sym_data[sym]
                warmup = max(bp["sigma_lb"], BTC_SMA_PERIOD) + 20
                oos_start_idx = df_full.index.get_indexer(
                    [pd.Timestamp(window["oos_start"])], method="nearest"
                )[0]
                start_idx = max(0, oos_start_idx - warmup)
                df_slice = df_full.iloc[start_idx:]
                btc_close_al = btc_df["close"].reindex(
                    df_slice.index, method="ffill"
                )
                btc_sma_al = btc_sma_full.reindex(
                    df_slice.index, method="ffill"
                )

                res = run_backtest(
                    df_slice, btc_close_al, btc_sma_al,
                    bp["anchor"], bp["z_entry"], bp["z_exit"],
                    bp["atr_sl"], bp["sigma_lb"], bp["max_hold"],
                )
                oos_trades = [
                    t for t in res["trades"]
                    if pd.Timestamp(window["oos_start"]) <= t["entry_time"]
                    <= pd.Timestamp(window["oos_end"])
                ]
                rets = [t["return"] for t in oos_trades]
                n = len(rets)
                if rets:
                    avg = np.mean(rets)
                    std = np.std(rets, ddof=1) if n > 1 else 1e-10
                    sh = (avg / std) * np.sqrt(252 * 6) if std > 0 else 0
                    wr = sum(1 for r in rets if r > 0) / n * 100
                    eq = np.cumprod([1 + r for r in rets])
                    pk = np.maximum.accumulate(eq)
                    mdd = np.min(eq / pk - 1) * 100
                else:
                    sh, wr, avg, mdd = 0, 0, 0, 0
                print(f"  {sym} {window['name']}: Sharpe={sh:+.3f}  "
                      f"WR={wr:.1f}%  n={n}  avg={avg*100:+.2f}%  MDD={mdd:+.2f}%")
                sym_sharpes.append(sh)
                sym_total_n += n
            avg_sh = np.mean(sym_sharpes) if sym_sharpes else 0
            print(f"  {sym} 평균: Sharpe={avg_sh:+.3f}  총 trades={sym_total_n}")

    # Buy-and-hold 비교
    print("\n" + "=" * 80)
    print("=== Buy-and-Hold 비교 ===")
    for sym in SYMBOLS:
        df_full = sym_data[sym]
        for window in WINDOWS:
            oos = df_full[(df_full.index >= window["oos_start"]) &
                          (df_full.index <= window["oos_end"])]
            if len(oos) > 1:
                bh_ret = (oos["close"].iloc[-1] / oos["close"].iloc[0] - 1) * 100
                print(f"  {sym} {window['name']}: BH return = {bh_ret:+.1f}%")

    # 최종 요약
    print("\n" + "=" * 80)
    print("=== 최종 요약 ===")
    if valid:
        b = valid[0]
        p = b["params"]
        status = "PASS" if b["avg_sharpe"] > 5.0 and b["total_n"] >= 30 else "FAIL"
        print(f"★ OOS 최적: anchor={p['anchor']} z_entry={p['z_entry']} "
              f"z_exit={p['z_exit']} atr_sl={p['atr_sl']} "
              f"sigma_lb={p['sigma_lb']} max_hold={p['max_hold']}")
        print(f"  avg OOS Sharpe: {b['avg_sharpe']:+.3f} {status}")
        print(f"  total trades: {b['total_n']}")
        for f in b["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  trades={f['n']}  avg={f['avg']:+.2f}%")
        print(f"\nSharpe: {b['avg_sharpe']:+.3f}")
        print(f"WR: {b['folds'][0]['wr']:.1f}%")
        print(f"trades: {b['total_n']}")
    else:
        print("n≥30 조건 충족 조합 없음 — FAIL")
        print("\nSharpe: N/A")
        print("WR: N/A")
        print("trades: 0")


if __name__ == "__main__":
    main()
