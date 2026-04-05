"""
사이클 200 — Binance 실제 펀딩레이트 기반 역추세(contrarian) 전략 백테스트

목적: 평가자 방향 "펀딩레이트 기반 신규 메커니즘" 실행
- Binance perpetual 펀딩레이트(8h) 실제 히스토리 사용 (proxy 아님)
- 음수 극단 펀딩 = 과매도 → 현물 매수, 양수 극단 = 과매수 → 청산 대기
- Upbit 현물 전략이므로 LONG-ONLY (short 없음)
- BTC regime gate (BTC > SMA200) + RSI 필터 결합

그리드: NEG_THRESH × DEEP_NEG × RSI_OVERSOLD × MAX_HOLD × COOLDOWN = 108조합
심볼: ETH/SOL 240m | 🔄다음봉시가진입 | ★슬리피지포함
3-fold expanding WF
"""
from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOLS = ["KRW-ETH", "KRW-SOL"]
FUNDING_FILES = {
    "KRW-ETH": "data/funding_rate_ETHUSDT.json",
    "KRW-SOL": "data/funding_rate_SOLUSDT.json",
}
FEE = 0.0005  # Upbit 수수료

# BTC regime gate
BTC_SMA_PERIOD = 200

# 그리드 파라미터
GRID = {
    "NEG_THRESH": [-0.0001, -0.0002, -0.0003],       # 음수 펀딩 진입 임계값
    "DEEP_NEG": [-0.0003, -0.0005, -0.0008],          # 극단 음수 (강한 매수)
    "RSI_OVERSOLD": [30.0, 35.0, 40.0],               # RSI 과매도
    "MAX_HOLD": [12, 24, 48],                          # 최대 보유 봉수 (240m 기준)
}
# 고정 파라미터
COOLDOWN = 4        # 쿨다운 봉수
RSI_PERIOD = 14
MOM_LOOKBACK = 10
TP_PCT = 0.04       # 4% TP
SL_PCT = 0.02       # 2% SL
TRAIL_PCT = 0.015   # 1.5% trailing stop

# 3-fold expanding WF
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-02-28"), "test": ("2024-03-01", "2024-11-30")},
    {"train": ("2022-01-01", "2024-11-30"), "test": ("2024-12-01", "2025-08-31")},
    {"train": ("2022-01-01", "2025-05-31"), "test": ("2025-06-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


def sma_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    cumsum = np.cumsum(series)
    result[period - 1:] = (
        cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))
    ) / period
    return result


def rsi_calc(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def load_funding_rates(filepath: str) -> list[tuple[datetime, float]]:
    """Load Binance funding rate history and return sorted (time, rate) pairs."""
    with open(filepath) as f:
        records = json.load(f)
    result = []
    for rec in records:
        ft = datetime.fromtimestamp(int(rec["fundingTime"]) / 1000, tz=UTC)
        rate = float(rec["fundingRate"])
        result.append((ft, rate))
    return sorted(result, key=lambda x: x[0])


def align_funding_to_candles(
    candle_times: list[datetime], funding_data: list[tuple[datetime, float]]
) -> np.ndarray:
    """For each candle, find the most recent funding rate."""
    rates = np.full(len(candle_times), np.nan)
    fi = 0
    for ci, ct in enumerate(candle_times):
        while fi < len(funding_data) - 1 and funding_data[fi + 1][0] <= ct:
            fi += 1
        if fi < len(funding_data) and funding_data[fi][0] <= ct:
            rates[ci] = funding_data[fi][1]
    return rates


def run_backtest(
    df: pd.DataFrame,
    funding_rates: np.ndarray,
    btc_sma: np.ndarray | None,
    btc_closes: np.ndarray | None,
    neg_thresh: float,
    deep_neg: float,
    rsi_oversold: float,
    max_hold: int,
    slippage: float = 0.0,
) -> dict:
    """Run funding rate contrarian strategy on a single symbol's data."""
    closes = df["close"].values
    opens = df["open"].values
    rsi_arr = rsi_calc(closes, RSI_PERIOD)
    mom = np.full(len(closes), np.nan)
    for i in range(MOM_LOOKBACK, len(closes)):
        mom[i] = (closes[i] - closes[i - MOM_LOOKBACK]) / closes[i - MOM_LOOKBACK]

    trades: list[dict] = []
    in_position = False
    entry_price = 0.0
    entry_bar = 0
    peak_price = 0.0
    last_exit_bar = -COOLDOWN - 1

    for i in range(1, len(closes)):
        if np.isnan(rsi_arr[i]) or np.isnan(funding_rates[i]):
            continue

        if in_position:
            # Exit logic
            current_price = closes[i]
            peak_price = max(peak_price, current_price)
            holding_bars = i - entry_bar
            pnl_pct = (current_price - entry_price) / entry_price

            exit_reason = None

            # TP
            if pnl_pct >= TP_PCT:
                exit_reason = "tp"
            # SL
            elif pnl_pct <= -SL_PCT:
                exit_reason = "sl"
            # Trailing stop
            elif peak_price > entry_price * (1 + TRAIL_PCT):
                drawdown = (peak_price - current_price) / peak_price
                if drawdown >= TRAIL_PCT:
                    exit_reason = "trail"
            # Max hold
            elif holding_bars >= max_hold:
                exit_reason = "max_hold"
            # Funding flipped extreme positive → exit
            elif funding_rates[i] > 0.0003:
                exit_reason = "funding_flip"

            if exit_reason:
                # Exit at next bar open
                if i + 1 < len(closes):
                    exit_price = opens[i + 1] * (1 - slippage)
                else:
                    exit_price = current_price * (1 - slippage)
                ret = (exit_price - entry_price) / entry_price - 2 * FEE
                trades.append({
                    "entry_bar": entry_bar,
                    "exit_bar": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return": ret,
                    "reason": exit_reason,
                    "holding_bars": holding_bars,
                })
                in_position = False
                last_exit_bar = i
                continue
        else:
            # Entry logic — signal at bar i, enter at bar i+1 open
            if i - last_exit_bar < COOLDOWN:
                continue
            if i + 1 >= len(closes):
                continue

            # BTC regime gate
            if btc_sma is not None and btc_closes is not None:
                if np.isnan(btc_sma[i]) or btc_closes[i] < btc_sma[i]:
                    continue

            fr = funding_rates[i]
            rsi_val = rsi_arr[i]

            # Entry conditions: negative funding + RSI oversold area
            buy_signal = False
            if fr <= deep_neg and rsi_val <= rsi_oversold + 5:
                buy_signal = True  # Strong: deep negative funding
            elif fr <= neg_thresh and rsi_val <= rsi_oversold:
                buy_signal = True  # Moderate: negative funding + oversold

            if buy_signal:
                entry_price = opens[i + 1] * (1 + slippage)
                entry_bar = i + 1
                peak_price = entry_price
                in_position = True

    # Close any open position at last bar
    if in_position and len(closes) > 0:
        exit_price = closes[-1] * (1 - slippage)
        ret = (exit_price - entry_price) / entry_price - 2 * FEE
        trades.append({
            "entry_bar": entry_bar,
            "exit_bar": len(closes) - 1,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return": ret,
            "reason": "end",
            "holding_bars": len(closes) - 1 - entry_bar,
        })

    bh_ret = (closes[-1] - closes[0]) / closes[0] * 100 if len(closes) > 1 else 0.0
    if not trades:
        return {"sharpe": 0.0, "wr": 0.0, "n": 0, "avg_ret": 0.0, "mdd": 0.0,
                "total_ret": 0.0, "bh_ret": round(bh_ret, 1)}

    returns = [t["return"] for t in trades]
    n = len(returns)
    avg_ret = np.mean(returns)
    std_ret = np.std(returns, ddof=1) if n > 1 else 1.0
    sharpe = (avg_ret / std_ret * math.sqrt(n)) if std_ret > 1e-9 else 0.0
    wr = sum(1 for r in returns if r > 0) / n * 100

    # MDD
    cum = np.cumprod([1 + r for r in returns])
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak
    mdd = dd.max() * 100

    # Buy-and-hold comparison (already computed above)

    return {
        "sharpe": round(sharpe, 3),
        "wr": round(wr, 1),
        "n": n,
        "avg_ret": round(avg_ret * 100, 2),
        "mdd": round(mdd, 2),
        "total_ret": round(np.prod([1 + r for r in returns]) * 100 - 100, 2),
        "bh_ret": round(bh_ret, 1),
    }


def main() -> None:
    print("=" * 80)
    print("c200: Binance 실제 펀딩레이트 역추세 전략 — ETH/SOL 240m")
    print("=" * 80)

    # Load BTC data for regime gate
    btc_raw = load_historical("KRW-BTC", "240m")
    btc_df = pd.DataFrame(btc_raw)
    btc_df.index = pd.to_datetime(btc_df.index, utc=True)
    btc_df = btc_df.reset_index().rename(columns={"datetime": "timestamp"})
    btc_closes_full = btc_df["close"].values
    btc_sma_full = sma_calc(btc_closes_full, BTC_SMA_PERIOD)
    btc_times = btc_df["timestamp"].tolist()

    # Build param grid
    from itertools import product
    param_combos = list(product(
        GRID["NEG_THRESH"], GRID["DEEP_NEG"],
        GRID["RSI_OVERSOLD"], GRID["MAX_HOLD"],
    ))
    # Filter: deep_neg must be <= neg_thresh
    param_combos = [
        (nt, dn, ro, mh) for nt, dn, ro, mh in param_combos if dn <= nt
    ]
    print(f"\n유효 파라미터 조합: {len(param_combos)}")

    # Results storage
    all_results: list[dict] = []

    for fold_idx, fold in enumerate(WF_FOLDS):
        print(f"\n{'='*60}")
        print(f"Fold {fold_idx+1}: train {fold['train']} → test {fold['test']}")
        print(f"{'='*60}")

        test_start = pd.Timestamp(fold["test"][0], tz="UTC")
        test_end = pd.Timestamp(fold["test"][1], tz="UTC")
        train_start = pd.Timestamp(fold["train"][0], tz="UTC")

        # Load and prepare data per symbol
        symbol_data: dict[str, dict] = {}
        for sym in SYMBOLS:
            raw = load_historical(sym, "240m")
            df = pd.DataFrame(raw)
            df.index = pd.to_datetime(df.index, utc=True)
            df = df.reset_index().rename(columns={"datetime": "timestamp"})

            # Load funding rates
            funding_path = FUNDING_FILES[sym]
            funding_data = load_funding_rates(funding_path)
            candle_times = df["timestamp"].tolist()
            funding_aligned = align_funding_to_candles(candle_times, funding_data)

            # Align BTC SMA to this symbol's candles
            btc_sma_aligned = np.full(len(df), np.nan)
            btc_closes_aligned = np.full(len(df), np.nan)
            bi = 0
            for ci, ct in enumerate(candle_times):
                while bi < len(btc_times) - 1 and btc_times[bi + 1] <= ct:
                    bi += 1
                if bi < len(btc_times) and btc_times[bi] <= ct:
                    btc_sma_aligned[ci] = btc_sma_full[bi]
                    btc_closes_aligned[ci] = btc_closes_full[bi]

            symbol_data[sym] = {
                "df": df,
                "funding": funding_aligned,
                "btc_sma": btc_sma_aligned,
                "btc_closes": btc_closes_aligned,
            }

        # Grid search on train, evaluate on test
        best_train_sharpe = -999
        best_params = None
        train_results: dict[tuple, float] = {}

        for nt, dn, ro, mh in param_combos:
            train_sharpes = []
            for sym in SYMBOLS:
                sd = symbol_data[sym]
                df = sd["df"]
                mask = (df["timestamp"] >= train_start) & (df["timestamp"] < test_start)
                train_df = df[mask].reset_index(drop=True)
                if len(train_df) < BTC_SMA_PERIOD:
                    continue
                train_idx = df.index[mask]
                train_funding = sd["funding"][train_idx[0]:train_idx[-1]+1]
                train_btc_sma = sd["btc_sma"][train_idx[0]:train_idx[-1]+1]
                train_btc_closes = sd["btc_closes"][train_idx[0]:train_idx[-1]+1]

                res = run_backtest(
                    train_df, train_funding, train_btc_sma, train_btc_closes,
                    nt, dn, ro, mh,
                )
                if res["n"] > 0:
                    train_sharpes.append(res["sharpe"])

            avg_sharpe = np.mean(train_sharpes) if train_sharpes else 0.0
            key = (nt, dn, ro, mh)
            train_results[key] = avg_sharpe
            if avg_sharpe > best_train_sharpe:
                best_train_sharpe = avg_sharpe
                best_params = key

        if best_params is None:
            print("  ⚠️ No valid params found in training")
            continue

        nt, dn, ro, mh = best_params
        print(f"\n  Train best: NT={nt} DN={dn} RSI_OS={ro} MH={mh}")
        print(f"  Train Sharpe: {best_train_sharpe:.3f}")

        # OOS evaluation
        print(f"\n  --- OOS evaluation ---")
        fold_results = {"fold": fold_idx + 1, "params": best_params}
        fold_sharpes = []
        fold_trades = 0

        for sym in SYMBOLS:
            sd = symbol_data[sym]
            df = sd["df"]
            mask = (df["timestamp"] >= test_start) & (df["timestamp"] <= test_end)
            test_df = df[mask].reset_index(drop=True)
            if len(test_df) < 20:
                print(f"  {sym}: insufficient test data")
                continue
            test_idx = df.index[mask]
            test_funding = sd["funding"][test_idx[0]:test_idx[-1]+1]
            test_btc_sma = sd["btc_sma"][test_idx[0]:test_idx[-1]+1]
            test_btc_closes = sd["btc_closes"][test_idx[0]:test_idx[-1]+1]

            res = run_backtest(
                test_df, test_funding, test_btc_sma, test_btc_closes,
                nt, dn, ro, mh,
            )
            print(f"  {sym}: Sharpe={res['sharpe']:+.3f} WR={res['wr']:.1f}% "
                  f"n={res['n']} avg={res['avg_ret']:+.2f}% MDD={res['mdd']:.2f}% "
                  f"BH={res['bh_ret']:+.1f}%")
            fold_sharpes.append(res["sharpe"])
            fold_trades += res["n"]
            fold_results[sym] = res

        fold_avg = np.mean(fold_sharpes) if fold_sharpes else 0.0
        fold_results["avg_sharpe"] = fold_avg
        fold_results["total_trades"] = fold_trades
        all_results.append(fold_results)
        print(f"  Fold {fold_idx+1} avg OOS Sharpe: {fold_avg:+.3f} trades={fold_trades}")

    # Overall summary
    print("\n" + "=" * 80)
    print("=== 전체 OOS 요약 ===")
    total_sharpe = np.mean([r["avg_sharpe"] for r in all_results]) if all_results else 0.0
    total_trades = sum(r["total_trades"] for r in all_results)

    for r in all_results:
        nt, dn, ro, mh = r["params"]
        print(f"  F{r['fold']}: NT={nt} DN={dn} RSI={ro} MH={mh} "
              f"→ Sharpe={r['avg_sharpe']:+.3f} trades={r['total_trades']}")

    print(f"\n  Overall avg OOS Sharpe: {total_sharpe:+.3f}")
    print(f"  Total OOS trades: {total_trades}")

    # Top-1 params across folds
    if all_results:
        best_fold = max(all_results, key=lambda r: r["avg_sharpe"])
        nt, dn, ro, mh = best_fold["params"]
        print(f"\n  ★ Best fold params: NT={nt} DN={dn} RSI_OS={ro} MH={mh}")

    # Slippage stress test on best params
    if all_results:
        best = max(all_results, key=lambda r: r["avg_sharpe"])
        nt, dn, ro, mh = best["params"]
        print(f"\n{'='*60}")
        print("=== 슬리피지 스트레스 테스트 (best fold params) ===")
        for slip in SLIPPAGE_LEVELS:
            slip_sharpes = []
            slip_trades = 0
            for sym in SYMBOLS:
                raw = load_historical(sym, "240m")
                df = pd.DataFrame(raw)
                df.index = pd.to_datetime(df.index, utc=True)
                df = df.reset_index().rename(columns={"datetime": "timestamp"})
                funding_data = load_funding_rates(FUNDING_FILES[sym])
                funding_aligned = align_funding_to_candles(
                    df["timestamp"].tolist(), funding_data
                )
                btc_sma_aligned = np.full(len(df), np.nan)
                btc_closes_aligned = np.full(len(df), np.nan)
                bi = 0
                for ci, ct in enumerate(df["timestamp"].tolist()):
                    while bi < len(btc_times) - 1 and btc_times[bi + 1] <= ct:
                        bi += 1
                    if bi < len(btc_times) and btc_times[bi] <= ct:
                        btc_sma_aligned[ci] = btc_sma_full[bi]
                        btc_closes_aligned[ci] = btc_closes_full[bi]

                fold = WF_FOLDS[-1]  # Last fold for stress test
                test_start = pd.Timestamp(fold["test"][0], tz="UTC")
                test_end = pd.Timestamp(fold["test"][1], tz="UTC")
                mask = (df["timestamp"] >= test_start) & (df["timestamp"] <= test_end)
                test_df = df[mask].reset_index(drop=True)
                if len(test_df) < 20:
                    continue
                test_idx = df.index[mask]
                res = run_backtest(
                    test_df,
                    funding_aligned[test_idx[0]:test_idx[-1]+1],
                    btc_sma_aligned[test_idx[0]:test_idx[-1]+1],
                    btc_closes_aligned[test_idx[0]:test_idx[-1]+1],
                    nt, dn, ro, mh, slippage=slip,
                )
                slip_sharpes.append(res["sharpe"])
                slip_trades += res["n"]

            avg_s = np.mean(slip_sharpes) if slip_sharpes else 0.0
            status = "PASS" if avg_s > 0 else "FAIL"
            print(f"  슬리피지 {slip*100:.2f}%: Sharpe={avg_s:+.3f} "
                  f"trades={slip_trades} [{status}]")

    # Symbol-level OOS breakdown for all folds
    print(f"\n{'='*80}")
    print("=== 심볼별 OOS 성능 분해 ===")
    for r in all_results:
        for sym in SYMBOLS:
            if sym in r:
                s = r[sym]
                print(f"  {sym} F{r['fold']}: Sharpe={s['sharpe']:+.3f} "
                      f"WR={s['wr']:.1f}% n={s['n']} avg={s['avg_ret']:+.2f}% "
                      f"MDD={s['mdd']:.2f}%")

    print(f"\nSharpe: {total_sharpe:+.3f}")
    print(f"trades: {total_trades}")


if __name__ == "__main__":
    main()
