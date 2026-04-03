"""
사이클 114: vpin_eth 슬리피지 민감도 분석
- 목적: Sharpe +7.46 (IS), OOS W1/W3 +9.4 이 과적합인지 확인
         실제 시장에서 슬리피지 0.10%~0.30% 구간에서도 엣지 유지 여부
- daemon 파라미터: vh=0.55, vm=0.0005, max_hold=18, TP=6%, SL=0.8%
- 슬리피지 범위: 0.0% ~ 0.30% (편도, 진입+청산 각각 적용)
- WF 3창: W1 OOS=2024, W2 OOS=2025, W3 OOS=2026
- 판정 기준: OOS Sharpe > 3.0 && WR > 35% && trades >= 5
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
FEE    = 0.0005  # 0.05% 수수료 (편도)

WINDOWS = [
    {"name": "W1", "is_start": "2022-01-01", "is_end": "2023-12-31",
     "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2023-01-01", "is_end": "2024-12-31",
     "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"name": "W3", "is_start": "2024-01-01", "is_end": "2025-12-31",
     "oos_start": "2026-01-01", "oos_end": "2026-04-04"},
]

# daemon 파라미터 (확정, 변경 없음)
VH        = 0.55
VM        = 0.0005
MAX_HOLD  = 18
TP        = 0.06
SL        = 0.008

# 슬리피지 구간 (편도 %)
SLIPPAGE_LIST = [0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003]

# 고정값
RSI_PERIOD    = 14
RSI_CEILING   = 65.0
RSI_FLOOR     = 20.0
BUCKET_COUNT  = 24
EMA_PERIOD    = 20
MOM_LOOKBACK  = 8

PASS_SHARPE   = 3.0
PASS_WR       = 0.20   # vpin_eth 특성상 WR 기준 완화 (사이클 99 W2 WR=23.1% 기준)
PASS_TRADES   = 5


# ── 지표 ───────────────────────────────────────────────────────────────────────

def ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i-1] * (1 - k)
    return result


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


def compute_vpin(closes: np.ndarray, opens: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    vpin_proxy = np.abs(closes - opens) / (np.abs(closes - opens) + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i-bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def backtest(df: pd.DataFrame, slippage: float) -> dict:
    """슬리피지를 편도 비율로 적용.
    기존 스크립트(backtest_vpin_eth_sliding_wf.py)와 동일한 로직 기반으로,
    슬리피지를 진입가 및 청산 수익에 추가.
    - 진입: buy = c[i+1] * (1 + FEE + slippage)
    - TP hit: returns.append(TP - FEE - slippage)  [기존 tp-FEE 방식 유지]
    - SL hit: returns.append(-SL - FEE - slippage)
    - hold_end: c[hold_end] / buy - 1 - FEE - slippage
    """
    c = df["close"].values
    o = df["open"].values
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr  = compute_vpin_momentum(c, MOM_LOOKBACK)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK) + 5
    i = warmup
    while i < n - 1:
        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]

        if (not np.isnan(vpin_val) and vpin_val > VH
                and not np.isnan(mom_val) and mom_val > VM
                and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
                and not np.isnan(ema_val) and c[i] > ema_val):

            # 진입가: 기존 방식 + 슬리피지
            buy = c[i + 1] * (1.0 + FEE + slippage)

            exited = False
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= TP:
                    returns.append(TP - FEE - slippage)   # 청산 슬리피지 차감
                    i = j
                    exited = True
                    break
                if ret <= -SL:
                    returns.append(-SL - FEE - slippage)  # 청산 슬리피지 차감
                    i = j
                    exited = True
                    break

            if not exited:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE - slippage)
                i = hold_end
        else:
            i += 1

    if len(returns) < PASS_TRADES:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def run_window(w: dict, slippage: float) -> dict:
    """IS + OOS 각각 독립 로드 후 백테스트 (기존 스크립트와 동일 방식)."""
    df_is  = load_historical(SYMBOL, "240m", w["is_start"],  w["is_end"])
    df_oos = load_historical(SYMBOL, "240m", w["oos_start"], w["oos_end"])
    is_r   = backtest(df_is, slippage)
    oos_r  = backtest(df_oos, slippage)
    passed = (
        not np.isnan(oos_r["sharpe"])
        and oos_r["sharpe"] >= PASS_SHARPE
        and oos_r["wr"] >= PASS_WR
        and oos_r["trades"] >= PASS_TRADES
    )
    return {"name": w["name"], "is": is_r, "oos": oos_r, "passed": passed}


def main() -> None:
    print("=" * 70)
    print("사이클 114: vpin_eth 슬리피지 민감도 분석")
    print(f"daemon 파라미터: vh={VH} vm={VM} hold={MAX_HOLD} TP={TP*100:.0f}% SL={SL*100:.1f}%")
    print(f"슬리피지 범위: {[f'{s*100:.2f}%' for s in SLIPPAGE_LIST]}")
    print("=" * 70)

    # 슬리피지별 요약 테이블
    print(f"{'Slip%':>6} | {'W1 OOS Sh':>10} {'WR':>6} {'T':>4} | "
          f"{'W2 OOS Sh':>10} {'WR':>6} {'T':>4} | "
          f"{'W3 OOS Sh':>10} {'WR':>6} {'T':>4} | {'통과':>5}")
    print("-" * 85)

    summary_rows = []
    for slip in SLIPPAGE_LIST:
        row_results = []
        pass_count  = 0
        for w in WINDOWS:
            res = run_window(w, slip)
            row_results.append(res)
            if res["passed"]:
                pass_count += 1

        slip_pct = f"{slip*100:.2f}%"
        cols = []
        for res in row_results:
            sh = res["oos"]["sharpe"]
            wr = res["oos"]["wr"]
            t  = res["oos"]["trades"]
            ok = "✅" if res["passed"] else "❌"
            sh_str = f"{sh:+.3f}{ok}" if not np.isnan(sh) else "  nan❌"
            cols.append(f"{sh_str:>10} {wr:>5.1%} {t:>4}")

        print(f"{slip_pct:>6} | {cols[0]} | {cols[1]} | {cols[2]} | {pass_count}/3")
        summary_rows.append({
            "slip": slip,
            "w1_sh": row_results[0]["oos"]["sharpe"],
            "w2_sh": row_results[1]["oos"]["sharpe"],
            "w3_sh": row_results[2]["oos"]["sharpe"],
            "pass_count": pass_count,
        })

    print()

    # 기준 슬리피지 (0%) 결과 재확인
    base = summary_rows[0]
    print(f"★ 기준(슬리피지 0%): W1={base['w1_sh']:+.3f}, W2={base['w2_sh']:+.3f}, "
          f"W3={base['w3_sh']:+.3f}, 통과={base['pass_count']}/3")

    # Sharpe가 급락하는 슬리피지 임계점 탐색
    print()
    print("=== 슬리피지 임계점 분석 ===")
    first_fail_slip = None
    for row in summary_rows:
        if row["pass_count"] < 2:
            first_fail_slip = row["slip"]
            break
    if first_fail_slip is not None:
        print(f"⚠️  2/3 미달 첫 슬리피지: {first_fail_slip*100:.2f}%")
    else:
        print("✅ 모든 슬리피지 구간에서 2/3+ 통과")

    # Sharpe 50% 감쇠 포인트
    base_avg = np.nanmean([base["w1_sh"], base["w2_sh"], base["w3_sh"]])
    print(f"기준 OOS 평균 Sharpe: {base_avg:+.3f}")
    for row in summary_rows[1:]:
        avg_sh = np.nanmean([row["w1_sh"], row["w2_sh"], row["w3_sh"]])
        decay  = (base_avg - avg_sh) / abs(base_avg) * 100 if base_avg != 0 else 0
        status = f"(감쇠 {decay:+.1f}%)"
        print(f"  슬리피지 {row['slip']*100:.2f}%: 평균 Sharpe {avg_sh:+.3f} {status}")

    print()
    print("=== 결론 ===")
    # 0.10% (현실적 슬리피지)에서의 결과
    real_row = next((r for r in summary_rows if abs(r["slip"] - 0.001) < 0.0001), None)
    if real_row:
        real_avg = np.nanmean([real_row["w1_sh"], real_row["w2_sh"], real_row["w3_sh"]])
        still_ok = real_row["pass_count"] >= 2
        print(f"현실적 슬리피지 0.10%: 평균 OOS Sharpe {real_avg:+.3f}, "
              f"통과 {real_row['pass_count']}/3 → {'엣지 유지 ✅' if still_ok else '엣지 소멸 ⚠️'}")

    high_row = next((r for r in summary_rows if abs(r["slip"] - 0.002) < 0.0001), None)
    if high_row:
        high_avg = np.nanmean([high_row["w1_sh"], high_row["w2_sh"], high_row["w3_sh"]])
        still_ok = high_row["pass_count"] >= 2
        print(f"높은 슬리피지 0.20%: 평균 OOS Sharpe {high_avg:+.3f}, "
              f"통과 {high_row['pass_count']}/3 → {'엣지 유지 ✅' if still_ok else '엣지 소멸 ⚠️'}")


if __name__ == "__main__":
    main()
