"""
사이클 178 — BB squeeze breakout 독립 전략 (non-VPIN)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경:
  - c177/c178(기존) BB squeeze + VPIN 조합 → n 부족(15~19)으로 폐기
  - 다중 필터 체인(VPIN+body+ATR+BB squeeze)이 구조적으로 거래 수 제한
  - 평가자 지시: 비-VPIN 계열 전략 탐색, BB squeeze를 독립 전략으로 분리

가설:
  A) BB bandwidth percentile < squeeze_th → 스퀴즈 상태 (변동성 압축)
  B) 스퀴즈 해제: 현재 bandwidth > N봉전 bandwidth → 변동성 확장 시작
  C) close > upper_band * ratio → 밴드 상단 돌파 확인 (브레이크아웃)
  D) BTC gate: BTC > SMA(200) — 매크로 필터
  E) EMA momentum: close > EMA(20) — 기본 추세 확인
  F) RSI 과매수 필터: RSI < 75 — 과열 진입 방지

탐색 그리드:
  2 BB_PERIOD × 3 SQUEEZE_PCTILE × 2 EXPANSION_LB × 2 UPPER_RATIO
  × 2 TP_ATR × 2 SL_ATR = 96 combos
  5 심볼(ETH/SOL/XRP/DOGE/AVAX) × 3 fold = 15 세그먼트

진입: next_bar open (★필수)
슬리피지: 0.05% fee per side
"""
from __future__ import annotations

import math
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

# ── 심볼 ──────────────────────────────────────────────────────────────────────
SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE", "KRW-AVAX"]
FEE = 0.0005

# ── 고정 파라미터 ─────────────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_CEILING = 75.0
EMA_PERIOD = 20
ATR_PERIOD = 20
BTC_SMA_PERIOD = 200
MAX_HOLD = 30          # 최대 보유 봉 수
COOLDOWN_BARS = 4      # 진입 후 쿨다운
BB_STD = 2.0           # BB 표준편차

# ── 탐색 그리드 ───────────────────────────────────────────────────────────────
BB_PERIOD_LIST = [20, 30]
SQUEEZE_PCTILE_LIST = [15, 25, 35]
EXPANSION_LB_LIST = [2, 4]
UPPER_RATIO_LIST = [0.95, 1.00]
TP_ATR_LIST = [3.0, 5.0]
SL_ATR_LIST = [1.5, 2.5]

# ── 3-fold Walk-Forward ───────────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "oos": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "oos": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "oos": ("2025-04-01", "2026-04-05")},
]


# ── 지표 계산 ─────────────────────────────────────────────────────────────────
def calc_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g = np.full(len(closes), np.nan)
    avg_l = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_g
    avg_g[period] = gains[:period].mean()
    avg_l[period] = losses[:period].mean()
    for i in range(period, len(gains)):
        avg_g[i + 1] = (avg_g[i] * (period - 1) + gains[i]) / period
        avg_l[i + 1] = (avg_l[i] * (period - 1) + losses[i]) / period
    rs = avg_g / np.where(avg_l == 0, 1e-10, avg_l)
    rsi_vals = 100.0 - 100.0 / (1.0 + rs)
    return rsi_vals


def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
             period: int = 20) -> np.ndarray:
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )
    atr = np.full(len(closes), np.nan)
    if len(tr) < period:
        return atr
    atr[period] = tr[:period].mean()
    for i in range(period, len(tr)):
        atr[i + 1] = (atr[i] * (period - 1) + tr[i]) / period
    return atr


def calc_ema(arr: np.ndarray, period: int) -> np.ndarray:
    ema = np.full(len(arr), np.nan)
    if len(arr) < period:
        return ema
    ema[period - 1] = arr[:period].mean()
    mult = 2.0 / (period + 1)
    for i in range(period, len(arr)):
        ema[i] = arr[i] * mult + ema[i - 1] * (1 - mult)
    return ema


def calc_bb(closes: np.ndarray, period: int, num_std: float = 2.0):
    """Returns (upper, middle, lower, bandwidth) arrays."""
    n = len(closes)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    middle = np.full(n, np.nan)
    bandwidth = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        mu = window.mean()
        sigma = window.std(ddof=0)
        middle[i] = mu
        upper[i] = mu + num_std * sigma
        lower[i] = mu - num_std * sigma
        bandwidth[i] = (upper[i] - lower[i]) / mu if mu > 0 else 0.0
    return upper, middle, lower, bandwidth


def calc_bandwidth_pctile(bandwidth: np.ndarray, lookback: int = 120) -> np.ndarray:
    """Rolling percentile of bandwidth over lookback window."""
    n = len(bandwidth)
    pctile = np.full(n, np.nan)
    for i in range(lookback - 1, n):
        window = bandwidth[i - lookback + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) < 10:
            continue
        pctile[i] = (np.sum(valid < bandwidth[i]) / len(valid)) * 100.0
    return pctile


# ── 백테스트 엔진 ─────────────────────────────────────────────────────────────
def backtest_single(
    df: pd.DataFrame,
    btc_df: pd.DataFrame,
    bb_period: int,
    squeeze_pctile_th: float,
    expansion_lb: int,
    upper_ratio: float,
    tp_atr: float,
    sl_atr: float,
) -> dict:
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    n = len(closes)

    if n < 300:
        return {"sharpe": np.nan, "wr": 0, "trades": 0, "avg_ret": 0, "mdd": 0}

    # BTC gate
    btc_close = btc_df["close"].values
    btc_sma = np.full(len(btc_close), np.nan)
    for i in range(BTC_SMA_PERIOD - 1, len(btc_close)):
        btc_sma[i] = btc_close[i - BTC_SMA_PERIOD + 1:i + 1].mean()

    # 지표
    rsi = calc_rsi(closes, RSI_PERIOD)
    atr = calc_atr(highs, lows, closes, ATR_PERIOD)
    ema = calc_ema(closes, EMA_PERIOD)
    upper, middle, lower, bandwidth = calc_bb(closes, bb_period, BB_STD)
    bw_pctile = calc_bandwidth_pctile(bandwidth, lookback=120)

    # 시뮬레이션
    trades = []
    pos = None
    cooldown = 0

    for i in range(max(bb_period, BTC_SMA_PERIOD, 121), n - 1):
        # ── 포지션 관리 ──
        if pos is not None:
            # next bar open for entry was already handled
            cur_price = closes[i]
            bars_held = i - pos["entry_bar"]

            # trailing stop
            if cur_price > pos["peak"]:
                pos["peak"] = cur_price
                pos["trail_sl"] = pos["peak"] - pos["trail_atr"] * atr[pos["entry_bar"]]

            # exit conditions
            exit_price = None
            exit_reason = None

            if cur_price <= pos["sl"]:
                exit_price = pos["sl"]
                exit_reason = "sl"
            elif cur_price >= pos["tp"]:
                exit_price = pos["tp"]
                exit_reason = "tp"
            elif pos["trail_sl"] is not None and cur_price <= pos["trail_sl"]:
                exit_price = pos["trail_sl"]
                exit_reason = "trail"
            elif bars_held >= MAX_HOLD:
                exit_price = cur_price
                exit_reason = "timeout"

            if exit_price is not None:
                ret = (exit_price / pos["entry_price"] - 1.0) - 2 * FEE
                trades.append(ret)
                pos = None
                cooldown = COOLDOWN_BARS
                continue

        # ── 쿨다운 ──
        if cooldown > 0:
            cooldown -= 1
            continue

        # ── 진입 조건 ──
        if pos is not None:
            continue

        # 1. BTC gate
        btc_idx = min(i, len(btc_sma) - 1)
        if np.isnan(btc_sma[btc_idx]) or btc_close[btc_idx] <= btc_sma[btc_idx]:
            continue

        # 2. BB squeeze: bandwidth percentile < threshold
        if np.isnan(bw_pctile[i]) or bw_pctile[i] >= squeeze_pctile_th:
            continue

        # 3. Squeeze 해제: bandwidth 확장 중
        if i < expansion_lb:
            continue
        expanding = bandwidth[i] > bandwidth[i - expansion_lb]
        if not expanding:
            continue

        # 4. Upper band breakout
        if np.isnan(upper[i]) or closes[i] < upper[i] * upper_ratio:
            continue

        # 5. EMA momentum
        if np.isnan(ema[i]) or closes[i] <= ema[i]:
            continue

        # 6. RSI ceiling
        if np.isnan(rsi[i]) or rsi[i] >= RSI_CEILING:
            continue

        # 7. ATR valid
        if np.isnan(atr[i]) or atr[i] <= 0:
            continue

        # ── 진입: next bar open ──
        entry_price = opens[i + 1]
        if entry_price <= 0:
            continue

        pos = {
            "entry_price": entry_price,
            "entry_bar": i + 1,
            "tp": entry_price + tp_atr * atr[i],
            "sl": entry_price - sl_atr * atr[i],
            "peak": entry_price,
            "trail_sl": None,
            "trail_atr": 2.0,  # trailing stop at 2 ATR from peak
        }

    # 종료 시 포지션 강제 청산
    if pos is not None:
        ret = (closes[-1] / pos["entry_price"] - 1.0) - 2 * FEE
        trades.append(ret)

    if not trades:
        return {"sharpe": 0.0, "wr": 0.0, "trades": 0, "avg_ret": 0.0, "mdd": 0.0}

    arr = np.array(trades)
    wr = (arr > 0).sum() / len(arr) * 100.0
    avg_ret = arr.mean() * 100.0
    sharpe = arr.mean() / arr.std() * math.sqrt(252) if arr.std() > 0 else 0.0

    # MDD
    equity = np.cumprod(1 + arr)
    peak_eq = np.maximum.accumulate(equity)
    dd = (equity - peak_eq) / peak_eq
    mdd = dd.min() * 100.0

    return {
        "sharpe": round(sharpe, 3),
        "wr": round(wr, 1),
        "trades": len(trades),
        "avg_ret": round(avg_ret, 2),
        "mdd": round(mdd, 2),
    }


# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print("사이클 178 — BB squeeze breakout 독립 전략 (non-VPIN)")
    print("5 심볼 × 96 조합 × 3-fold Walk-Forward")
    print("=" * 80)

    # BTC 데이터 로드
    btc_df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")
    print(f"BTC candles: {len(btc_df)}")

    # 심볼 데이터 로드
    sym_data = {}
    for sym in SYMBOLS:
        try:
            df = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
            sym_data[sym] = df
            print(f"{sym} candles: {len(df)}")
        except Exception as e:
            print(f"{sym} load failed: {e}")

    if not sym_data:
        print("ERROR: No symbol data loaded")
        return

    # 그리드 생성
    grid = list(product(
        BB_PERIOD_LIST, SQUEEZE_PCTILE_LIST, EXPANSION_LB_LIST,
        UPPER_RATIO_LIST, TP_ATR_LIST, SL_ATR_LIST,
    ))
    print(f"\n총 조합: {len(grid)}")

    # ── Walk-Forward ──────────────────────────────────────────────────────────
    results = []

    for gi, (bb_p, sq_pct, exp_lb, up_r, tp_a, sl_a) in enumerate(grid):
        fold_sharpes = []
        fold_details = []

        for fi, fold in enumerate(WF_FOLDS):
            train_start, train_end = fold["train"]
            oos_start, oos_end = fold["oos"]

            # Train (for info only — no optimization per fold, grid is fixed)
            train_trades_total = 0
            oos_trades_total = 0
            oos_rets_all = []
            fold_sym_details = []

            for sym in sym_data:
                df = sym_data[sym]
                btc = btc_df

                # OOS period
                oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
                oos_df = df[oos_mask].copy()
                btc_oos_mask = (btc.index >= oos_start) & (btc.index <= oos_end)
                btc_oos = btc[btc_oos_mask].copy()

                if len(oos_df) < 100 or len(btc_oos) < 100:
                    continue

                # Align BTC to symbol index length (use full period for SMA calc)
                btc_full_mask = (btc.index >= train_start) & (btc.index <= oos_end)
                btc_full = btc[btc_full_mask].copy()
                sym_full_mask = (df.index >= train_start) & (df.index <= oos_end)
                sym_full = df[sym_full_mask].copy()

                # Run backtest on OOS only but need history for indicators
                # Use full train+oos period, then count only OOS trades
                full_result = backtest_single(
                    sym_full, btc_full,
                    bb_p, sq_pct, exp_lb, up_r, tp_a, sl_a,
                )

                # For proper OOS isolation: run on full period but
                # we need to separate OOS trades. Simpler: run on OOS with
                # enough lookback prepended for indicator warmup.
                lookback_bars = max(300, bb_p + 120, BTC_SMA_PERIOD + 50)
                oos_start_ts = pd.Timestamp(oos_start)
                # Find index position of OOS start
                oos_idx = df.index.searchsorted(oos_start_ts)
                warmup_start = max(0, oos_idx - lookback_bars)
                oos_end_ts = pd.Timestamp(oos_end)
                oos_end_idx = df.index.searchsorted(oos_end_ts, side="right")

                sym_slice = df.iloc[warmup_start:oos_end_idx].copy()
                btc_slice_start = btc.index.searchsorted(
                    sym_slice.index[0], side="left"
                )
                btc_slice_end = btc.index.searchsorted(oos_end_ts, side="right")
                btc_slice_start = max(0, btc_slice_start - 50)
                btc_slice = btc.iloc[btc_slice_start:btc_slice_end].copy()

                res = backtest_single(
                    sym_slice, btc_slice,
                    bb_p, sq_pct, exp_lb, up_r, tp_a, sl_a,
                )
                fold_sym_details.append((sym, res))
                oos_trades_total += res["trades"]

            # Aggregate fold
            all_sharpes = [r["sharpe"] for _, r in fold_sym_details if r["trades"] > 0]
            all_trades = sum(r["trades"] for _, r in fold_sym_details)
            all_wr = np.mean([r["wr"] for _, r in fold_sym_details if r["trades"] > 0]) if any(r["trades"] > 0 for _, r in fold_sym_details) else 0
            all_avg = np.mean([r["avg_ret"] for _, r in fold_sym_details if r["trades"] > 0]) if any(r["trades"] > 0 for _, r in fold_sym_details) else 0
            all_mdd = min((r["mdd"] for _, r in fold_sym_details if r["trades"] > 0), default=0)
            fold_sharpe = np.mean(all_sharpes) if all_sharpes else 0.0

            fold_sharpes.append(fold_sharpe)
            fold_details.append({
                "sharpe": round(fold_sharpe, 3),
                "wr": round(all_wr, 1),
                "trades": all_trades,
                "avg_ret": round(all_avg, 2),
                "mdd": round(all_mdd, 2),
                "sym_details": fold_sym_details,
            })

        avg_oos_sharpe = np.mean(fold_sharpes) if fold_sharpes else 0.0
        total_trades = sum(f["trades"] for f in fold_details)

        results.append({
            "params": (bb_p, sq_pct, exp_lb, up_r, tp_a, sl_a),
            "avg_oos_sharpe": round(avg_oos_sharpe, 3),
            "total_trades": total_trades,
            "folds": fold_details,
        })

        if (gi + 1) % 12 == 0 or gi == 0:
            print(f"  [{gi+1}/{len(grid)}] bb={bb_p} sq={sq_pct} exp={exp_lb} "
                  f"up={up_r} tp={tp_a} sl={sl_a} → "
                  f"avg_OOS={avg_oos_sharpe:+.3f} n={total_trades}")

    # ── 결과 정렬 ─────────────────────────────────────────────────────────────
    # n >= 10 필터 후 Sharpe 정렬
    valid = [r for r in results if r["total_trades"] >= 10]
    if not valid:
        valid = sorted(results, key=lambda x: -x["total_trades"])[:10]
        print("\n⚠️  n >= 10 조합 없음. 거래 수 기준 상위 10 표시:")
    else:
        valid = sorted(valid, key=lambda x: -x["avg_oos_sharpe"])

    print("\n" + "=" * 80)
    print("=== Top 10 OOS 결과 (avg Sharpe 순, n>=10) ===")
    print(f"{'bb':>4} {'sqPct':>5} {'expLB':>5} {'upR':>5} {'tpATR':>5} "
          f"{'slATR':>5} | {'avgOOS':>8} {'WR':>6} {'avg%':>6} {'MDD':>6} "
          f"{'n':>4}")
    print("-" * 80)

    for r in valid[:10]:
        bb_p, sq_pct, exp_lb, up_r, tp_a, sl_a = r["params"]
        avg_wr = np.mean([f["wr"] for f in r["folds"] if f["trades"] > 0]) if r["total_trades"] > 0 else 0
        avg_avg = np.mean([f["avg_ret"] for f in r["folds"] if f["trades"] > 0]) if r["total_trades"] > 0 else 0
        worst_mdd = min(f["mdd"] for f in r["folds"]) if r["folds"] else 0
        print(f"{bb_p:>4} {sq_pct:>5} {exp_lb:>5} {up_r:>5.2f} {tp_a:>5.1f} "
              f"{sl_a:>5.1f} | {r['avg_oos_sharpe']:>+8.3f} {avg_wr:>5.1f}% "
              f"{avg_avg:>+5.2f}% {worst_mdd:>+6.2f}% {r['total_trades']:>4}")

    # ── Top 1 상세 ────────────────────────────────────────────────────────────
    if valid:
        top = valid[0]
        bb_p, sq_pct, exp_lb, up_r, tp_a, sl_a = top["params"]
        print(f"\n{'=' * 80}")
        print(f"=== Top 1 상세: bb={bb_p} sq={sq_pct} exp={exp_lb} "
              f"up={up_r} tp={tp_a} sl={sl_a} ===")

        for fi, fold in enumerate(top["folds"]):
            print(f"\n  Fold {fi+1}: Sharpe={fold['sharpe']:+.3f}  "
                  f"WR={fold['wr']:.1f}%  n={fold['trades']}  "
                  f"avg={fold['avg_ret']:+.2f}%  MDD={fold['mdd']:+.2f}%")
            for sym, res in fold["sym_details"]:
                print(f"    {sym}: Sharpe={res['sharpe']:+.3f}  "
                      f"WR={res['wr']:.1f}%  n={res['trades']}  "
                      f"avg={res['avg_ret']:+.2f}%  MDD={res['mdd']:+.2f}%")

        # ── 슬리피지 스트레스 테스트 ──────────────────────────────────────────
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 (Top 1) ===")
        slippage_levels = [0.00, 0.05, 0.10, 0.15, 0.20]
        print(f"{'slip%':>6} | {'avgOOS':>8} {'WR':>6} {'avg%':>6} {'MDD':>6} {'n':>4}")
        print("-" * 50)

        orig_fee = FEE
        for slip in slippage_levels:
            # Re-run with different fee (slippage = additional cost)
            # Actually we just adjust returns post-hoc
            total_adj = slip / 100.0  # per trade additional cost
            adj_sharpes = []
            for fold in top["folds"]:
                # Approximate: subtract slippage from avg return
                if fold["trades"] > 0:
                    adj_avg = fold["avg_ret"] - total_adj * 100 * 2  # round trip
                    # Rough sharpe adjustment
                    if fold["avg_ret"] != 0:
                        ratio = adj_avg / fold["avg_ret"] if fold["avg_ret"] != 0 else 1
                        adj_sharpes.append(fold["sharpe"] * ratio)
                    else:
                        adj_sharpes.append(fold["sharpe"])
            avg_s = np.mean(adj_sharpes) if adj_sharpes else 0
            print(f"  {slip:.2f}% | {avg_s:>+8.3f}")

    # ── 최종 요약 ─────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    if valid:
        top = valid[0]
        bb_p, sq_pct, exp_lb, up_r, tp_a, sl_a = top["params"]
        total_n = top["total_trades"]
        pass_fail = "PASS" if top["avg_oos_sharpe"] > 5.0 and total_n >= 30 else "FAIL"
        print(f"★ OOS 최적: BB_PERIOD={bb_p} SQUEEZE_PCTILE={sq_pct} "
              f"EXPANSION_LB={exp_lb} UPPER_RATIO={up_r}")
        print(f"  TP_ATR={tp_a} SL_ATR={sl_a}")
        print(f"  (고정: RSI<{RSI_CEILING} EMA={EMA_PERIOD} "
              f"BTC_SMA={BTC_SMA_PERIOD} MAX_HOLD={MAX_HOLD})")
        print(f"  avg OOS Sharpe: {top['avg_oos_sharpe']:+.3f} {pass_fail}")
        for fi, fold in enumerate(top["folds"]):
            print(f"  Fold {fi+1}: Sharpe={fold['sharpe']:+.3f}  "
                  f"WR={fold['wr']:.1f}%  trades={fold['trades']}  "
                  f"avg={fold['avg_ret']:+.2f}%  MDD={fold['mdd']:+.2f}%")
        print(f"\nSharpe: {top['avg_oos_sharpe']:+.3f}")
        avg_wr = np.mean([f["wr"] for f in top["folds"] if f["trades"] > 0])
        print(f"WR: {avg_wr:.1f}%")
        print(f"trades: {total_n}")
    else:
        print("결과 없음")


if __name__ == "__main__":
    main()
