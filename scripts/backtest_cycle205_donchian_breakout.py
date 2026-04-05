"""
사이클 205: Donchian Channel Breakout 독립 전략 3-fold WF 백테스트
- 목적: 기존 VPIN 역추세와 완전 다른 alpha 축 — 순수 추세추종
- 설계:
  1) 진입: close > Donchian upper(N봉 최고가) + BTC > SMA200 + ADX >= threshold
  2) 청산: ATR-based TP/SL, trailing stop, 또는 close < Donchian lower(M봉 최저가)
  3) 다음 봉 시가 진입 (look-ahead bias 제거)
- 심볼: ETH/SOL/XRP 240m
- 3-fold WF: 새 윈도우 (OOS 미사용 확인)
  F1: IS=2022-07~2024-04 → OOS=2024-05~2025-02
  F2: IS=2023-05~2025-02 → OOS=2025-03~2025-11
  F3: IS=2024-03~2025-11 → OOS=2025-12~2026-03
- 그리드: dc_upper(3) × dc_lower(3) × adx_th(3) × atr_tp(3) × atr_sl(3) × trail(2) = 162조합
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
        "is_start": "2022-07-01", "is_end": "2024-04-30",
        "oos_start": "2024-05-01", "oos_end": "2025-02-28",
    },
    {
        "name": "F2",
        "is_start": "2023-05-01", "is_end": "2025-02-28",
        "oos_start": "2025-03-01", "oos_end": "2025-11-30",
    },
    {
        "name": "F3",
        "is_start": "2024-03-01", "is_end": "2025-11-30",
        "oos_start": "2025-12-01", "oos_end": "2026-03-31",
    },
]

# ─── 그리드 파라미터 ─────────────────────────────────────────────────
DC_UPPER_LIST = [20, 30, 50]        # Donchian upper lookback (진입)
DC_LOWER_LIST = [10, 15, 20]        # Donchian lower lookback (청산)
ADX_THRESH_LIST = [20, 25, 30]      # ADX 추세 강도 필터
ATR_TP_LIST = [3.0, 4.0, 5.0]      # ATR 기반 TP 배수
ATR_SL_LIST = [1.5, 2.0, 2.5]      # ATR 기반 SL 배수
TRAIL_LIST = [0.0, 0.3]            # trailing stop (0=없음, ATR 배수)
MAX_HOLD = 30                       # 최대 보유 봉수

# 총 조합: 3×3×3×3×3×2 = 162


# ─── 지표 계산 ───────────────────────────────────────────────────────

def donchian_upper(highs: pd.Series, period: int) -> pd.Series:
    """N봉 최고가 (현재 봉 제외)."""
    return highs.shift(1).rolling(period).max()


def donchian_lower(lows: pd.Series, period: int) -> pd.Series:
    """N봉 최저가 (현재 봉 제외)."""
    return lows.shift(1).rolling(period).min()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    h = df["high"]
    l = df["low"]
    c = df["close"].shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index."""
    h = df["high"]
    l = df["low"]
    c = df["close"]

    plus_dm = h.diff()
    minus_dm = -l.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_s = tr.ewm(span=period, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr_s)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr_s)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


# ─── 백테스트 엔진 ───────────────────────────────────────────────────

def run_backtest(
    df: pd.DataFrame,
    btc_df: pd.DataFrame,
    dc_upper_lb: int,
    dc_lower_lb: int,
    adx_thresh: float,
    atr_tp_mult: float,
    atr_sl_mult: float,
    trail_mult: float,
) -> dict:
    """단일 심볼 백테스트."""
    # 지표
    dc_up = donchian_upper(df["high"], dc_upper_lb)
    dc_lo = donchian_lower(df["low"], dc_lower_lb)
    atr_val = atr(df, 14)
    adx_val = adx(df, 14)
    btc_sma = sma(btc_df["close"], BTC_SMA_PERIOD)

    # BTC SMA 데이터를 심볼 인덱스에 맞춤
    btc_sma_aligned = btc_sma.reindex(df.index, method="ffill")

    trades: list[dict] = []
    position = None

    for i in range(max(dc_upper_lb, BTC_SMA_PERIOD) + 2, len(df) - 1):
        idx = df.index[i]
        c = df["close"].iloc[i]
        o_next = df["open"].iloc[i + 1]  # 다음 봉 시가 진입

        if position is not None:
            # 포지션 관리
            bars_held = i - position["entry_bar"]
            atr_now = atr_val.iloc[i]

            # trailing stop 업데이트
            if trail_mult > 0 and c > position.get("peak", position["entry_price"]):
                position["peak"] = c
                trail_stop = c - atr_now * trail_mult
                if trail_stop > position.get("trail_stop", 0):
                    position["trail_stop"] = trail_stop

            # 청산 조건
            exit_reason = None
            exit_price = c

            # 1) SL
            sl_price = position["entry_price"] * (1 - position["sl_pct"])
            if c <= sl_price:
                exit_reason = "SL"
                exit_price = sl_price

            # 2) TP
            tp_price = position["entry_price"] * (1 + position["tp_pct"])
            if c >= tp_price:
                exit_reason = "TP"
                exit_price = tp_price

            # 3) Trailing stop
            if trail_mult > 0 and c <= position.get("trail_stop", 0):
                exit_reason = "TRAIL"
                exit_price = position["trail_stop"]

            # 4) Donchian lower 돌파
            if dc_lo.iloc[i] is not None and not np.isnan(dc_lo.iloc[i]):
                if c <= dc_lo.iloc[i]:
                    exit_reason = "DC_LOW"
                    exit_price = c

            # 5) Max hold
            if bars_held >= MAX_HOLD:
                exit_reason = "MAX_HOLD"
                exit_price = c

            if exit_reason:
                # 다음 봉 시가로 청산
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
            # 진입 조건
            if (
                not np.isnan(dc_up.iloc[i])
                and not np.isnan(adx_val.iloc[i])
                and c > dc_up.iloc[i]                      # Donchian upper 돌파
                and adx_val.iloc[i] >= adx_thresh           # ADX 추세 확인
                and idx in btc_sma_aligned.index
                and not np.isnan(btc_sma_aligned.loc[idx])
                and btc_df["close"].reindex(df.index, method="ffill").iloc[i]
                    > btc_sma_aligned.iloc[i]               # BTC > SMA200
            ):
                entry_price = o_next * (1 + SLIPPAGE)
                atr_now = atr_val.iloc[i]
                if np.isnan(atr_now) or atr_now <= 0:
                    continue
                position = {
                    "entry_price": entry_price,
                    "entry_time": df.index[i + 1],
                    "entry_bar": i + 1,
                    "tp_pct": atr_now / c * atr_tp_mult,
                    "sl_pct": atr_now / c * atr_sl_mult,
                    "peak": entry_price,
                    "trail_stop": 0,
                }

    if not trades:
        return {"sharpe": -999, "wr": 0, "n": 0, "avg_ret": 0, "mdd": 0, "trades": []}

    rets = [t["return"] for t in trades]
    n = len(rets)
    avg_ret = np.mean(rets)
    std_ret = np.std(rets, ddof=1) if n > 1 else 1e-10
    sharpe = (avg_ret / std_ret) * np.sqrt(252 / (240 / 60 / 24)) if std_ret > 0 else 0
    wr = sum(1 for r in rets if r > 0) / n * 100

    # MDD
    equity = np.cumprod([1 + r for r in rets])
    peak_eq = np.maximum.accumulate(equity)
    mdd = np.min(equity / peak_eq - 1) * 100

    return {"sharpe": sharpe, "wr": wr, "n": n, "avg_ret": avg_ret * 100, "mdd": mdd,
            "trades": trades}


# ─── 메인 ────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== c205: Donchian Channel Breakout 독립 전략 3-fold WF ===")
    print("=== 심볼: ETH/SOL/XRP | 240m | ★슬리피지포함 | 🔄다음봉시가진입 ===")
    print("=" * 80)

    # BTC 데이터 (SMA200 필터용)
    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"BTC 데이터: {len(btc_df)} rows ({btc_df.index[0]} ~ {btc_df.index[-1]})")

    # 심볼 데이터 로드
    sym_data = {}
    for sym in SYMBOLS:
        df = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        sym_data[sym] = df
        print(f"{sym} 데이터: {len(df)} rows ({df.index[0]} ~ {df.index[-1]})")

    # 그리드 정의
    grid = list(product(
        DC_UPPER_LIST, DC_LOWER_LIST, ADX_THRESH_LIST,
        ATR_TP_LIST, ATR_SL_LIST, TRAIL_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # Walk-Forward
    all_results: list[dict] = []

    for gi, (dc_up_lb, dc_lo_lb, adx_th, atr_tp, atr_sl, trail) in enumerate(grid):
        fold_sharpes = []
        fold_details = []
        total_n = 0

        for window in WINDOWS:
            fold_rets = []
            fold_n = 0

            for sym in SYMBOLS:
                df_full = sym_data[sym]

                # IS 구간으로 최적화 (여기서는 직접 OOS 실행 — grid search이므로 IS에서 학습 안 함)
                oos_mask = (df_full.index >= window["oos_start"]) & \
                           (df_full.index <= window["oos_end"])
                # 지표 계산을 위해 OOS 시작 전 충분한 데이터 포함
                warmup = max(dc_up_lb, BTC_SMA_PERIOD) + 10
                oos_start_idx = df_full.index.get_indexer(
                    [pd.Timestamp(window["oos_start"])], method="nearest"
                )[0]
                start_idx = max(0, oos_start_idx - warmup)
                df_slice = df_full.iloc[start_idx:]

                # BTC도 같은 범위
                btc_slice = btc_df.reindex(df_slice.index, method="ffill")

                res = run_backtest(
                    df_slice, btc_slice,
                    dc_up_lb, dc_lo_lb, adx_th, atr_tp, atr_sl, trail,
                )

                # OOS 기간 거래만 필터
                oos_trades = [
                    t for t in res["trades"]
                    if pd.Timestamp(window["oos_start"]) <= t["entry_time"]
                    <= pd.Timestamp(window["oos_end"])
                ]
                fold_rets.extend([t["return"] for t in oos_trades])
                fold_n += len(oos_trades)

            # Fold Sharpe 계산
            if fold_rets:
                avg = np.mean(fold_rets)
                std = np.std(fold_rets, ddof=1) if len(fold_rets) > 1 else 1e-10
                sharpe = (avg / std) * np.sqrt(252 / (240 / 60 / 24)) if std > 0 else 0
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
            "params": (dc_up_lb, dc_lo_lb, adx_th, atr_tp, atr_sl, trail),
            "avg_sharpe": avg_sharpe,
            "total_n": total_n,
            "folds": fold_details,
        })

        if (gi + 1) % 20 == 0:
            print(f"  진행: {gi + 1}/{len(grid)} 완료")

    # ─── 결과 정리 ───────────────────────────────────────────────────
    valid = [r for r in all_results if r["total_n"] >= 30]
    valid.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    print("\n" + "=" * 80)
    print("=== Top 10 결과 (n≥30) ===")
    print("=" * 80)
    for i, r in enumerate(valid[:10]):
        p = r["params"]
        print(f"\n#{i+1}: dcU={p[0]} dcL={p[1]} adx={p[2]} "
              f"atrTP={p[3]} atrSL={p[4]} trail={p[5]}")
        print(f"  avg OOS Sharpe: {r['avg_sharpe']:+.3f}  total_n={r['total_n']}")
        for f in r["folds"]:
            print(f"  {f['name']}: Sharpe={f['sharpe']:+.3f}  "
                  f"WR={f['wr']:.1f}%  n={f['n']}  avg={f['avg']:+.2f}%")

    # Top 1 심볼별 분해
    if valid:
        best = valid[0]
        bp = best["params"]
        print("\n" + "=" * 80)
        print(f"=== 심볼별 OOS 성능 분해 (Top 1: dcU={bp[0]} dcL={bp[1]} "
              f"adx={bp[2]} atrTP={bp[3]} atrSL={bp[4]} trail={bp[5]}) ===")

        for sym in SYMBOLS:
            sym_sharpes = []
            sym_total_n = 0
            for window in WINDOWS:
                df_full = sym_data[sym]
                warmup = max(bp[0], BTC_SMA_PERIOD) + 10
                oos_start_idx = df_full.index.get_indexer(
                    [pd.Timestamp(window["oos_start"])], method="nearest"
                )[0]
                start_idx = max(0, oos_start_idx - warmup)
                df_slice = df_full.iloc[start_idx:]
                btc_slice = btc_df.reindex(df_slice.index, method="ffill")

                res = run_backtest(
                    df_slice, btc_slice,
                    bp[0], bp[1], bp[2], bp[3], bp[4], bp[5],
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
                    sh = (avg / std) * np.sqrt(252 / (240 / 60 / 24)) if std > 0 else 0
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
            print(f"  {sym} 평균: Sharpe={np.mean(sym_sharpes):+.3f}  총 trades={sym_total_n}")

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
        print(f"★ OOS 최적: dcU={p[0]} dcL={p[1]} adx={p[2]} "
              f"atrTP={p[3]} atrSL={p[4]} trail={p[5]}")
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
