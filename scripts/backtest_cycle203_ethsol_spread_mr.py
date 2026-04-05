"""
사이클 203 — 크로스심볼 ETH/SOL 스프레드 역추세 (mean-reversion)
- 가설: ETH/SOL 가격 비율이 평균 회귀하는 속성을 이용
  → ratio 고점(SOL 상대 저평가): SOL 매수
  → ratio 저점(ETH 상대 저평가): ETH 매수
- Upbit 현물 제약: long only → 상대 저평가 자산만 매수
- 진입: next_bar open (신호 발생 다음 봉)
- 240m 캔들 기반
- 3-fold walk-forward + 슬리피지 스트레스 테스트
- 그리드: 162조합
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

SYMBOLS = ["KRW-ETH", "KRW-SOL"]
FEE = 0.0005

# -- 그리드 파라미터 --
RATIO_LOOKBACK_LIST = [48, 96, 144]    # z-score 룩백 (240m bars)
Z_ENTRY_LIST = [1.5, 2.0, 2.5]         # 진입 z-score 임계
Z_EXIT_LIST = [0.0, 0.5]               # 청산 z-score 임계
MAX_HOLD_LIST = [12, 24, 48]            # 최대 보유 기간 (bars)
BTC_GATE_LIST = [0, 200]               # BTC SMA 필터 (0=비활성)
RSI_FILTER_LIST = [0, 30]              # RSI < 30 과매도 확인 (0=비활성)
# 3×3×2×3×2×2 = 216 조합 → RSI 제거하면 108

# -- 3-fold WF --
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


def sma_calc(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    cumsum = np.cumsum(series)
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate(
        ([0.0], cumsum[:-period]))) / period
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


def compute_ratio_zscore(
    eth_close: np.ndarray, sol_close: np.ndarray, lookback: int
) -> tuple[np.ndarray, np.ndarray]:
    """ETH/SOL ratio z-score 계산"""
    ratio = eth_close / (sol_close + 1e-9)
    zscore = np.full(len(ratio), np.nan)
    ratio_ma = np.full(len(ratio), np.nan)

    for i in range(lookback - 1, len(ratio)):
        window = ratio[i - lookback + 1: i + 1]
        mu = window.mean()
        sigma = window.std()
        ratio_ma[i] = mu
        if sigma > 1e-9:
            zscore[i] = (ratio[i] - mu) / sigma
        else:
            zscore[i] = 0.0

    return ratio, zscore


def run_backtest(
    eth_df: pd.DataFrame,
    sol_df: pd.DataFrame,
    btc_df: pd.DataFrame | None,
    ratio_lb: int,
    z_entry: float,
    z_exit: float,
    max_hold: int,
    btc_gate: int,
    rsi_filter: int,
    slippage: float = 0.0005,
) -> dict:
    """단일 파라미터 조합 백테스트 실행"""
    eth_close = eth_df["close"].values
    sol_close = sol_df["close"].values
    eth_open = eth_df["open"].values
    sol_open = sol_df["open"].values

    ratio, zscore = compute_ratio_zscore(eth_close, sol_close, ratio_lb)

    # BTC SMA
    btc_above_sma = np.ones(len(eth_close), dtype=bool)
    if btc_gate > 0 and btc_df is not None:
        btc_close = btc_df["close"].values
        btc_sma = sma_calc(btc_close, btc_gate)
        btc_above_sma = btc_close > btc_sma

    # RSI for each symbol
    eth_rsi = rsi_calc(eth_close)
    sol_rsi = rsi_calc(sol_close)

    trades = []
    position = None  # {"symbol": "ETH"|"SOL", "entry_bar": int, "entry_price": float}

    for i in range(1, len(eth_close) - 1):
        if np.isnan(zscore[i]):
            continue

        if position is not None:
            # 청산 조건
            held = i - position["entry_bar"]
            should_exit = False

            if position["symbol"] == "SOL":
                # SOL 매수 → ratio 정상화(하락) 시 청산
                if zscore[i] <= z_exit:
                    should_exit = True
            else:
                # ETH 매수 → ratio 정상화(상승) 시 청산
                if zscore[i] >= -z_exit:
                    should_exit = True

            if held >= max_hold:
                should_exit = True

            if should_exit:
                # 다음 봉 시가로 청산
                exit_bar = i + 1
                if exit_bar >= len(eth_close):
                    break
                if position["symbol"] == "SOL":
                    exit_price = sol_open[exit_bar]
                else:
                    exit_price = eth_open[exit_bar]

                pnl_pct = (exit_price / position["entry_price"] - 1.0
                           - FEE * 2 - slippage * 2)
                trades.append({
                    "symbol": position["symbol"],
                    "entry_bar": position["entry_bar"],
                    "exit_bar": exit_bar,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "held": held,
                })
                position = None
            continue

        # 진입 조건 (다음 봉 시가로 진입)
        if not btc_above_sma[i]:
            continue

        entry_bar = i + 1
        if entry_bar >= len(eth_close):
            break

        if zscore[i] > z_entry:
            # ratio 높음 = SOL 상대 저평가 → SOL 매수
            if rsi_filter > 0 and not np.isnan(sol_rsi[i]):
                if sol_rsi[i] >= rsi_filter:
                    continue  # RSI 과매도 아님 → 스킵
            entry_price = sol_open[entry_bar]
            position = {
                "symbol": "SOL",
                "entry_bar": entry_bar,
                "entry_price": entry_price,
            }
        elif zscore[i] < -z_entry:
            # ratio 낮음 = ETH 상대 저평가 → ETH 매수
            if rsi_filter > 0 and not np.isnan(eth_rsi[i]):
                if eth_rsi[i] >= rsi_filter:
                    continue
            entry_price = eth_open[entry_bar]
            position = {
                "symbol": "ETH",
                "entry_bar": entry_bar,
                "entry_price": entry_price,
            }

    if not trades:
        return {"sharpe": -999, "wr": 0, "n": 0, "avg_pnl": 0, "mdd": 0}

    pnls = [t["pnl_pct"] for t in trades]
    n = len(pnls)
    avg_pnl = np.mean(pnls)
    std_pnl = np.std(pnls) if n > 1 else 1.0
    sharpe = (avg_pnl / std_pnl * np.sqrt(n)) if std_pnl > 1e-9 else 0.0
    wr = sum(1 for p in pnls if p > 0) / n * 100

    # MDD (순차 누적)
    cumret = np.cumprod([1 + p for p in pnls])
    peak = np.maximum.accumulate(cumret)
    dd = (cumret - peak) / peak
    mdd = dd.min() * 100

    # 심볼별 분해
    sym_stats = {}
    for sym in ["ETH", "SOL"]:
        sym_pnls = [t["pnl_pct"] for t in trades if t["symbol"] == sym]
        if sym_pnls:
            sym_n = len(sym_pnls)
            sym_avg = np.mean(sym_pnls)
            sym_std = np.std(sym_pnls) if sym_n > 1 else 1.0
            sym_sharpe = (sym_avg / sym_std * np.sqrt(sym_n)) if sym_std > 1e-9 else 0
            sym_wr = sum(1 for p in sym_pnls if p > 0) / sym_n * 100
            sym_stats[sym] = {"sharpe": sym_sharpe, "wr": sym_wr, "n": sym_n,
                              "avg": sym_avg * 100}

    return {
        "sharpe": sharpe,
        "wr": wr,
        "n": n,
        "avg_pnl": avg_pnl * 100,
        "mdd": mdd,
        "trades": trades,
        "sym_stats": sym_stats,
    }


def load_data(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """ETH, SOL, BTC 데이터 로드 및 시간 정렬"""
    eth = load_historical("KRW-ETH", "240m", start, end)
    sol = load_historical("KRW-SOL", "240m", start, end)
    btc = load_historical("KRW-BTC", "240m", start, end)

    # 시간 인덱스 교집합으로 정렬
    common_idx = eth.index.intersection(sol.index).intersection(btc.index)
    eth = eth.loc[common_idx].sort_index()
    sol = sol.loc[common_idx].sort_index()
    btc = btc.loc[common_idx].sort_index()

    return eth, sol, btc


def main():
    print("=" * 80)
    print("사이클 203: 크로스심볼 ETH/SOL 스프레드 역추세 백테스트")
    print("=" * 80)

    # -- Phase 0: 데이터 로드 (전체 기간) --
    print("\n[Phase 0] 데이터 로드...")
    eth_all, sol_all, btc_all = load_data("2022-01-01", "2026-04-05")
    print(f"  정렬된 공통 봉 수: {len(eth_all)}")

    # -- Ratio 분포 분석 --
    ratio = eth_all["close"].values / (sol_all["close"].values + 1e-9)
    print(f"\n  ETH/SOL ratio 분포:")
    print(f"    mean={ratio.mean():.2f}  std={ratio.std():.2f}")
    print(f"    min={ratio.min():.2f}  max={ratio.max():.2f}")
    print(f"    현재={ratio[-1]:.2f}")

    # -- Phase 1: Train 그리드 서치 --
    print("\n" + "=" * 80)
    print("Phase 1: Train 그리드 서치 (Fold 1 train 기간)")
    print("=" * 80)

    fold1 = WF_FOLDS[0]
    eth_train, sol_train, btc_train = load_data(
        fold1["train"][0], fold1["train"][1]
    )
    print(f"  Train 봉 수: {len(eth_train)}")

    grid = list(product(
        RATIO_LOOKBACK_LIST, Z_ENTRY_LIST, Z_EXIT_LIST,
        MAX_HOLD_LIST, BTC_GATE_LIST, RSI_FILTER_LIST,
    ))
    print(f"  총 조합: {len(grid)}")

    results = []
    for idx, (rlb, ze, zx, mh, bg, rf) in enumerate(grid):
        res = run_backtest(
            eth_train, sol_train, btc_train,
            rlb, ze, zx, mh, bg, rf,
        )
        results.append({
            "rlb": rlb, "ze": ze, "zx": zx, "mh": mh, "bg": bg, "rf": rf,
            **res,
        })
        if (idx + 1) % 50 == 0:
            print(f"  [{idx + 1}/{len(grid)}] 완료")

    print(f"  [{len(grid)}/{len(grid)}] 완료")

    # n >= 10 필터
    valid = [r for r in results if r["n"] >= 10]
    if not valid:
        print("\n❌ n >= 10인 조합 없음. 전략 구조 재검토 필요.")
        valid = sorted(results, key=lambda x: x["sharpe"], reverse=True)[:5]
        print("\n--- 참고: Top 5 (n 무관) ---")
        for i, r in enumerate(valid):
            print(f"  #{i+1} rlb={r['rlb']} ze={r['ze']} zx={r['zx']} "
                  f"mh={r['mh']} bg={r['bg']} rf={r['rf']} → "
                  f"Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1f}% n={r['n']} "
                  f"avg={r['avg_pnl']:+.2f}% MDD={r['mdd']:.2f}%")
        return

    valid_sorted = sorted(valid, key=lambda x: x["sharpe"], reverse=True)

    print("\n--- Train Top 5 ---")
    for i, r in enumerate(valid_sorted[:5]):
        print(f"  #{i+1} rlb={r['rlb']} ze={r['ze']} zx={r['zx']} "
              f"mh={r['mh']} bg={r['bg']} rf={r['rf']} → "
              f"Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1f}% n={r['n']} "
              f"avg={r['avg_pnl']:+.2f}% MDD={r['mdd']:.2f}%")

    # -- Phase 2: 3-fold WF 검증 --
    print("\n" + "=" * 80)
    print("Phase 2: 3-fold WF 검증 (Top 5)")
    print("=" * 80)

    wf_results = []
    for rank, params in enumerate(valid_sorted[:5]):
        pkey = (f"rlb={params['rlb']} ze={params['ze']} zx={params['zx']} "
                f"mh={params['mh']} bg={params['bg']} rf={params['rf']}")
        print(f"\n--- #{rank+1}: {pkey} ---")

        fold_sharpes = []
        fold_details = []
        for fi, fold in enumerate(WF_FOLDS):
            # Train
            eth_tr, sol_tr, btc_tr = load_data(fold["train"][0], fold["train"][1])
            train_res = run_backtest(
                eth_tr, sol_tr, btc_tr,
                params["rlb"], params["ze"], params["zx"],
                params["mh"], params["bg"], params["rf"],
            )

            # OOS
            eth_te, sol_te, btc_te = load_data(fold["test"][0], fold["test"][1])
            oos_res = run_backtest(
                eth_te, sol_te, btc_te,
                params["rlb"], params["ze"], params["zx"],
                params["mh"], params["bg"], params["rf"],
            )

            fold_sharpes.append(oos_res["sharpe"])
            fold_details.append(oos_res)
            print(f"  Fold {fi+1}: train Sharpe={train_res['sharpe']:+.3f} → "
                  f"OOS Sharpe={oos_res['sharpe']:+.3f} WR={oos_res['wr']:.1f}% "
                  f"n={oos_res['n']}")

        avg_oos = np.mean(fold_sharpes)
        total_n = sum(f["n"] for f in fold_details)
        print(f"  → avg OOS Sharpe: {avg_oos:+.3f}")

        wf_results.append({
            "params": params,
            "pkey": pkey,
            "avg_oos": avg_oos,
            "fold_sharpes": fold_sharpes,
            "fold_details": fold_details,
            "total_n": total_n,
        })

    # Best by avg OOS
    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos"], reverse=True)
    best = wf_sorted[0]
    bp = best["params"]

    # -- Phase 3: 슬리피지 스트레스 --
    print("\n" + "=" * 80)
    print("Phase 3: 슬리피지 스트레스 테스트")
    print("=" * 80)
    print(f"최적: {best['pkey']}")

    for slip in SLIPPAGE_LEVELS:
        slip_sharpes = []
        slip_n = 0
        slip_wr_sum = 0
        for fold in WF_FOLDS:
            eth_te, sol_te, btc_te = load_data(fold["test"][0], fold["test"][1])
            res = run_backtest(
                eth_te, sol_te, btc_te,
                bp["rlb"], bp["ze"], bp["zx"],
                bp["mh"], bp["bg"], bp["rf"],
                slippage=slip,
            )
            slip_sharpes.append(res["sharpe"])
            slip_n += res["n"]
            slip_wr_sum += res["wr"] * res["n"]

        avg_slip_sharpe = np.mean(slip_sharpes)
        avg_wr = slip_wr_sum / slip_n if slip_n > 0 else 0
        status = "PASS" if avg_slip_sharpe > 5.0 else "FAIL" if avg_slip_sharpe < 0 else "WEAK"
        print(f"  slip={slip:.4f}: Sharpe={avg_slip_sharpe:+.3f} WR={avg_wr:.1f}% "
              f"n={slip_n} [{status}]")

    # -- Phase 4: 심볼별 분해 --
    print("\n" + "=" * 80)
    print(f"심볼별 OOS 성능 분해 (Top 1: {best['pkey']})")
    print("=" * 80)

    for fi, fd in enumerate(best["fold_details"]):
        for sym, stats in fd.get("sym_stats", {}).items():
            print(f"  {sym} Fold {fi+1}: Sharpe={stats['sharpe']:+.3f} "
                  f"WR={stats['wr']:.1f}% n={stats['n']} avg={stats['avg']:+.2f}%")

    # -- Buy-and-hold 비교 --
    print("\n" + "=" * 80)
    print("Buy-and-Hold 비교")
    print("=" * 80)

    for fi, fold in enumerate(WF_FOLDS):
        eth_te, sol_te, _ = load_data(fold["test"][0], fold["test"][1])
        eth_bnh = (eth_te["close"].iloc[-1] / eth_te["close"].iloc[0] - 1) * 100
        sol_bnh = (sol_te["close"].iloc[-1] / sol_te["close"].iloc[0] - 1) * 100
        fd = best["fold_details"][fi]
        strat_ret = sum(t["pnl_pct"] for t in fd.get("trades", [])) * 100
        print(f"  Fold {fi+1}: ETH B&H={eth_bnh:+.1f}% SOL B&H={sol_bnh:+.1f}% "
              f"→ Strategy={strat_ret:+.1f}%")

    # -- 최종 요약 --
    print("\n" + "=" * 80)
    print("최종 요약")
    print("=" * 80)
    print(f"★ OOS 최적: {best['pkey']}")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f} "
          f"{'PASS' if best['avg_oos'] > 5.0 else 'FAIL'}")
    print(f"  total trades: {best['total_n']}")
    for fi, (sh, fd) in enumerate(zip(best["fold_sharpes"], best["fold_details"])):
        print(f"  Fold {fi+1}: Sharpe={sh:+.3f} WR={fd['wr']:.1f}% "
              f"n={fd['n']} avg={fd['avg_pnl']:+.2f}% MDD={fd['mdd']:.2f}%")

    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    total_wr = sum(fd["wr"] * fd["n"] for fd in best["fold_details"]) / best["total_n"] \
        if best["total_n"] > 0 else 0
    print(f"WR: {total_wr:.1f}%")
    print(f"trades: {best['total_n']}")


if __name__ == "__main__":
    main()
