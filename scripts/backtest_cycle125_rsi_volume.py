"""
사이클 125: ETH RSI oversold + Volume Spike 복합 필터 백테스트
- 목적: 사이클 124 ETH RSI<25(W2 Sharpe=3.263) 미달 개선
         RSI<20 극단 과매도 + 볼륨 급증 동시 발생 시 반등 신뢰도 향상
- 가설: 패닉 셀링(볼륨 급증 + RSI 극단) 후 기술적 반등 확률 높음
- 전략: RSI(14) 극단 과매도(< threshold) + volume > MA_vol * spike_mult 동시 진입
- 심볼: KRW-ETH (사이클 124 최적 심볼)
- 타임프레임: 240m (4시간봉)
- WF: W1 OOS=2024, W2 OOS=2025-2026
- 판정 기준: 2/2창 Sharpe > 5.0 && trades >= 6
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005       # 0.05% 수수료 (편도)
SLIPPAGE = 0.001   # 0.10% 슬리피지 (편도)

WINDOWS = [
    {
        "name": "W1",
        "is_start": "2022-01-01", "is_end": "2023-12-31",
        "oos_start": "2024-01-01", "oos_end": "2024-12-31",
    },
    {
        "name": "W2",
        "is_start": "2023-01-01", "is_end": "2024-12-31",
        "oos_start": "2025-01-01", "oos_end": "2026-04-04",
    },
]

SYMBOL = "KRW-ETH"

# 그리드 파라미터
RSI_ENTRY_LIST    = [15, 18, 20]           # 극단 과매도 임계값
RSI_EXIT_LIST     = [40, 45, 50]           # RSI 회복 청산선
VOL_MA_PERIOD_LIST = [20, 30]              # 볼륨 MA 기간
VOL_SPIKE_LIST    = [1.5, 2.0, 2.5, 3.0]  # 볼륨 급증 배수
MAX_HOLD_LIST     = [12, 24, 36]           # 최대 보유 봉 수
TP_LIST           = [0.05, 0.08, 0.10]    # 익절 비율
SL_LIST           = [0.02, 0.03]          # 손절 비율

# 판정 기준 (사이클 125 목표: Sharpe > 5.0)
PASS_SHARPE = 5.0
PASS_TRADES = 6


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def volume_ma(volumes: np.ndarray, period: int) -> np.ndarray:
    """볼륨 이동평균"""
    vol_ma = np.full(len(volumes), np.nan)
    for i in range(period, len(volumes)):
        vol_ma[i] = volumes[i-period:i].mean()
    return vol_ma


def backtest(
    df: pd.DataFrame,
    rsi_entry: float,
    rsi_exit: float,
    vol_ma_period: int,
    vol_spike: float,
    tp: float,
    sl: float,
    max_hold: int,
    slippage: float = SLIPPAGE,
) -> dict:
    closes  = df["close"].values
    highs   = df["high"].values
    lows    = df["low"].values
    volumes = df["volume"].values if "volume" in df.columns else np.ones(len(closes))

    rsi_vals = rsi(closes)
    vol_ma_vals = volume_ma(volumes, vol_ma_period)
    n = len(closes)

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count  = 0

    start_idx = max(15, vol_ma_period + 1)
    for i in range(start_idx, n):
        if not in_pos:
            # 진입 조건: RSI 극단 과매도 크로스다운 + 볼륨 급증 동시 발생
            rsi_cross_down = (rsi_vals[i-1] >= rsi_entry) and (rsi_vals[i] < rsi_entry)
            vol_spiked = (
                not np.isnan(vol_ma_vals[i]) and
                volumes[i] >= vol_ma_vals[i] * vol_spike
            )
            if rsi_cross_down and vol_spiked:
                entry_price = closes[i] * (1 + slippage + FEE)
                in_pos = True
                hold_count = 0
        else:
            hold_count += 1

            # TP 확인
            if highs[i] >= entry_price * (1 + tp):
                exit_price = entry_price * (1 + tp) * (1 - slippage - FEE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append(pnl)
                in_pos = False
                continue

            # SL 확인
            if lows[i] <= entry_price * (1 - sl):
                exit_price = entry_price * (1 - sl) * (1 - slippage - FEE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append(pnl)
                in_pos = False
                continue

            # RSI 회복 청산
            if rsi_vals[i] > rsi_exit:
                exit_price = closes[i] * (1 - slippage - FEE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append(pnl)
                in_pos = False
                continue

            # max_hold 청산
            if hold_count >= max_hold:
                exit_price = closes[i] * (1 - slippage - FEE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append(pnl)
                in_pos = False
                continue

    if not trades or len(trades) < PASS_TRADES:
        return {"sharpe": float("nan"), "wr": float("nan"), "avg": float("nan"), "n": len(trades)}

    arr = np.array(trades)
    sharpe = arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6)  # 연환산 (240m = 하루 6봉)
    wr = (arr > 0).mean()
    avg = arr.mean()
    return {"sharpe": sharpe, "wr": wr, "avg": avg, "n": len(trades)}


def walk_forward(params: dict) -> list[dict]:
    results = []
    for w in WINDOWS:
        df_all = load_historical(SYMBOL, "240m", w["is_start"], w["oos_end"])
        if df_all is None or len(df_all) < 100:
            results.append({"window": w["name"], "sharpe": float("nan"), "n": 0})
            continue

        df_oos = df_all[
            (df_all.index >= w["oos_start"]) &
            (df_all.index <= w["oos_end"])
        ]
        if len(df_oos) < 30:
            results.append({"window": w["name"], "sharpe": float("nan"), "n": 0})
            continue

        res = backtest(df_oos, **params)
        results.append({"window": w["name"], **res})
    return results


def grid_search() -> list[dict]:
    all_results = []
    param_grid = list(product(
        RSI_ENTRY_LIST,
        RSI_EXIT_LIST,
        VOL_MA_PERIOD_LIST,
        VOL_SPIKE_LIST,
        MAX_HOLD_LIST,
        TP_LIST,
        SL_LIST,
    ))
    total = len(param_grid)
    print(f"\n{'='*70}")
    print(f"[{SYMBOL}] 그리드 탐색 {total} 조합")
    print(f"{'='*70}")

    for idx, (rsi_e, rsi_x, vol_ma_p, vol_sp, mh, tp, sl) in enumerate(param_grid):
        if idx % 100 == 0:
            print(f"  진행: {idx}/{total} ({idx/total*100:.1f}%)")

        params = {
            "rsi_entry": rsi_e,
            "rsi_exit": rsi_x,
            "vol_ma_period": vol_ma_p,
            "vol_spike": vol_sp,
            "max_hold": mh,
            "tp": tp,
            "sl": sl,
        }
        wf_res = walk_forward(params)

        sharpes = [r["sharpe"] for r in wf_res if not np.isnan(r["sharpe"])]
        passed = sum(
            1 for r in wf_res
            if not np.isnan(r["sharpe"])
            and r["sharpe"] >= PASS_SHARPE
            and r.get("n", 0) >= PASS_TRADES
        )
        avg_sharpe = np.mean(sharpes) if sharpes else float("nan")

        all_results.append({
            "rsi_entry": rsi_e,
            "rsi_exit": rsi_x,
            "vol_ma_p": vol_ma_p,
            "vol_spike": vol_sp,
            "max_hold": mh,
            "tp": f"{tp*100:.0f}%",
            "sl": f"{sl*100:.0f}%",
            "w1_sharpe": wf_res[0]["sharpe"] if wf_res else float("nan"),
            "w1_n": wf_res[0].get("n", 0) if wf_res else 0,
            "w2_sharpe": wf_res[1]["sharpe"] if len(wf_res) > 1 else float("nan"),
            "w2_n": wf_res[1].get("n", 0) if len(wf_res) > 1 else 0,
            "avg_sharpe": avg_sharpe,
            "passed": passed,
            "total_windows": len(WINDOWS),
        })

    return all_results


def main() -> None:
    print("=" * 70)
    print("사이클 125: ETH RSI Oversold + Volume Spike 복합 필터 백테스트")
    print(f"슬리피지: {SLIPPAGE*100:.2f}% (편도)")
    print(f"판정 기준: Sharpe > {PASS_SHARPE} && n >= {PASS_TRADES} (2/2창)")
    print(f"RSI 진입 임계: {RSI_ENTRY_LIST}")
    print(f"볼륨 스파이크 배수: {VOL_SPIKE_LIST}x")
    print("=" * 70)

    all_results = grid_search()
    df = pd.DataFrame(all_results)

    # 2/2창 통과
    passed_2_2 = df[df["passed"] == df["total_windows"]].sort_values("avg_sharpe", ascending=False)
    print(f"\n{'='*70}")
    print(f"2/2창 통과 조합 (Sharpe > {PASS_SHARPE}): {len(passed_2_2)}개")
    print(f"{'='*70}")
    if len(passed_2_2) > 0:
        print(passed_2_2[["rsi_entry","rsi_exit","vol_ma_p","vol_spike","max_hold","tp","sl",
                           "w1_sharpe","w1_n","w2_sharpe","w2_n","avg_sharpe"]].to_string(index=False))
    else:
        print("없음")

    # 1/2창 상위 15개 (참고용)
    passed_1_2 = df[df["passed"] == 1].sort_values("avg_sharpe", ascending=False).head(15)
    print(f"\n{'='*70}")
    print(f"1/2창 통과 상위 15개 (참고용 — W2 기준)")
    print(f"{'='*70}")
    if len(passed_1_2) > 0:
        print(passed_1_2[["rsi_entry","rsi_exit","vol_ma_p","vol_spike","max_hold","tp","sl",
                           "w1_sharpe","w1_n","w2_sharpe","w2_n","avg_sharpe"]].to_string(index=False))
    else:
        print("없음")

    # RSI 임계별 최고 성과 요약
    print(f"\n{'='*70}")
    print("RSI 임계별 최고 avg Sharpe 요약")
    print(f"{'='*70}")
    for rsi_thr in RSI_ENTRY_LIST:
        sub = df[df["rsi_entry"] == rsi_thr]
        valid = sub[
            (~sub["w1_sharpe"].isna()) &
            (~sub["w2_sharpe"].isna()) &
            (sub["w1_n"] >= PASS_TRADES) &
            (sub["w2_n"] >= PASS_TRADES)
        ]
        if len(valid) == 0:
            print(f"RSI<{rsi_thr}: 유효 결과 없음")
            continue
        best = valid.sort_values("avg_sharpe", ascending=False).iloc[0]
        print(f"RSI<{rsi_thr}: avg_sharpe={best['avg_sharpe']:.3f} "
              f"(W1={best['w1_sharpe']:.3f}/n={best['w1_n']}, "
              f"W2={best['w2_sharpe']:.3f}/n={best['w2_n']}) "
              f"vol_spike={best['vol_spike']}x vol_ma={best['vol_ma_p']} "
              f"hold={best['max_hold']} tp={best['tp']} sl={best['sl']}")

    # 볼륨 스파이크 임계별 요약
    print(f"\n{'='*70}")
    print("볼륨 스파이크 배수별 최고 avg Sharpe 요약")
    print(f"{'='*70}")
    for vs in VOL_SPIKE_LIST:
        sub = df[df["vol_spike"] == vs]
        valid = sub[
            (~sub["w1_sharpe"].isna()) &
            (~sub["w2_sharpe"].isna()) &
            (sub["w1_n"] >= PASS_TRADES) &
            (sub["w2_n"] >= PASS_TRADES)
        ]
        if len(valid) == 0:
            print(f"vol_spike={vs}x: 유효 결과 없음")
            continue
        best = valid.sort_values("avg_sharpe", ascending=False).iloc[0]
        print(f"vol_spike={vs}x: avg_sharpe={best['avg_sharpe']:.3f} "
              f"(W1={best['w1_sharpe']:.3f}/n={best['w1_n']}, "
              f"W2={best['w2_sharpe']:.3f}/n={best['w2_n']}) "
              f"RSI<{best['rsi_entry']}")


if __name__ == "__main__":
    main()
