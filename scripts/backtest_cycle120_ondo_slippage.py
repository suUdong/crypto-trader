"""
사이클 120: ONDO vpin 슬리피지 민감도 분석
- 목적: 사이클 119 확정 파라미터 (hold=18, TP=10%, SL=1.5%, BTC Gate1=Y)의
         실제 Upbit 슬리피지 환경에서 엣지 유지 여부 최종 검증
- 배경: ONDO vpin 2/2창 통과 (W1=+9.132, W2=+5.296, avg=+7.214)
         daemon 반영 전 슬리피지 내성 확인 필수
- 고정 파라미터: vh=0.55, vm=0.0005, hold=18, TP=10%, SL=1.5%, Gate1=Y
  (vh/vm은 Gate1이 지배 → 대표값 사용)
- 슬리피지 범위: 0.00% ~ 0.30% (편도, 진입/청산 각각 적용)
- WF 2창: W1 OOS=2025-01~2025-09, W2 OOS=2025-07~2026-04
- 판정 기준: OOS Sharpe > 5.0 && WR > 25% && trades >= 5 (2/2창)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL  = "KRW-ONDO"
BTC_SYM = "KRW-BTC"
FEE     = 0.0005   # 0.05% 편도 수수료
CTYPE   = "240m"

WINDOWS = [
    {
        "name": "W1",
        "oos_start": "2025-01-01", "oos_end": "2025-09-30",
    },
    {
        "name": "W2",
        "oos_start": "2025-07-01", "oos_end": "2026-04-04",
    },
]

# 사이클 119 확정 파라미터 (대표값 — vh/vm 무관이나 기준점 사용)
VH   = 0.55
VM   = 0.0005
HOLD = 18
TP   = 0.10
SL   = 0.015

# 고정 지표 파라미터
RSI_PERIOD     = 14
RSI_CEILING    = 65.0
RSI_FLOOR      = 20.0
BUCKET_COUNT   = 24
EMA_PERIOD     = 20
MOM_LOOKBACK   = 8
BTC_SMA_PERIOD = 20

# 슬리피지 구간 (편도 %)
SLIPPAGE_LIST = [0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003]

# 판정 기준
PASS_SHARPE = 5.0
PASS_WR     = 0.25
PASS_TRADES = 5


# ── 지표 계산 ─────────────────────────────────────────────────────────────────

def ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
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
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def compute_vpin(closes: np.ndarray, opens: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    vpin_proxy = np.abs(closes - opens) / (np.abs(closes - opens) + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def sma(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        result[i] = series[i - period + 1:i + 1].mean()
    return result


# ── 백테스트 (슬리피지 포함) ──────────────────────────────────────────────────

def backtest(
    df_sym: pd.DataFrame,
    df_btc: pd.DataFrame | None,
    slippage: float,
) -> dict:
    """슬리피지를 편도 비율로 적용.
    - 진입: buy = c[i+1] * (1 + FEE + slippage)
    - TP hit: TP - FEE - slippage
    - SL hit: -SL - FEE - slippage
    - hold_end: c[hold_end] / buy - 1 - FEE - slippage
    """
    c = df_sym["close"].values
    o = df_sym["open"].values
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr  = compute_vpin_momentum(c, MOM_LOOKBACK)

    # BTC Gate1 계산
    if df_btc is not None and len(df_btc) > 0:
        btc_c = df_btc["close"].values
        btc_sma_arr = sma(btc_c, BTC_SMA_PERIOD)
        btc_index   = pd.Series(btc_sma_arr, index=df_btc.index)
        btc_close_s = pd.Series(btc_c, index=df_btc.index)
        sym_ts      = df_sym.index
        gate1_arr   = np.zeros(n, dtype=bool)
        for idx_i, ts in enumerate(sym_ts):
            try:
                loc = btc_index.index.get_indexer([ts], method="pad")[0]
                if loc >= 0 and not np.isnan(btc_sma_arr[loc]):
                    gate1_arr[idx_i] = btc_close_s.iloc[loc] > btc_sma_arr[loc]
            except Exception:
                pass
    else:
        gate1_arr = np.ones(n, dtype=bool)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK, BTC_SMA_PERIOD) + 5
    i = warmup
    while i < n - 1:
        gate1_ok = bool(gate1_arr[i])
        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]

        if (gate1_ok
                and not np.isnan(vpin_val) and vpin_val > VH
                and not np.isnan(mom_val)  and mom_val > VM
                and not np.isnan(rsi_val)  and RSI_FLOOR < rsi_val < RSI_CEILING
                and not np.isnan(ema_val)  and c[i] > ema_val):

            buy = c[i + 1] * (1.0 + FEE + slippage)
            exited = False
            for j in range(i + 2, min(i + 1 + HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= TP:
                    returns.append(TP - FEE - slippage)
                    i = j
                    exited = True
                    break
                if ret <= -SL:
                    returns.append(-SL - FEE - slippage)
                    i = j
                    exited = True
                    break

            if not exited:
                hold_end = min(i + HOLD, n - 1)
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
    df_sym = load_historical(SYMBOL,  CTYPE, w["oos_start"], w["oos_end"])
    df_btc = load_historical(BTC_SYM, CTYPE, w["oos_start"], w["oos_end"])
    oos_r  = backtest(df_sym, df_btc, slippage)
    passed = (
        not np.isnan(oos_r["sharpe"])
        and oos_r["sharpe"] >= PASS_SHARPE
        and oos_r["wr"]     >= PASS_WR
        and oos_r["trades"] >= PASS_TRADES
    )
    return {"name": w["name"], "oos": oos_r, "passed": passed}


def main() -> None:
    print("=" * 72)
    print("사이클 120: ONDO vpin 슬리피지 민감도 분석")
    print(f"고정 파라미터: vh={VH} vm={VM} hold={HOLD} TP={TP*100:.0f}% "
          f"SL={SL*100:.1f}% BTC Gate1=Y")
    print(f"슬리피지 범위: {[f'{s*100:.2f}%' for s in SLIPPAGE_LIST]}")
    print(f"판정 기준: OOS Sharpe > {PASS_SHARPE} && WR > {PASS_WR:.0%} "
          f"&& trades >= {PASS_TRADES}")
    print(f"배경: W1 OOS +9.132, W2 OOS +5.296 → daemon 반영 전 최종 검증")
    print("=" * 72)

    print(f"\n{'Slip%':>6} | {'W1 OOS Sh':>10} {'WR':>5} {'T':>4} {'통과':>4} | "
          f"{'W2 OOS Sh':>10} {'WR':>5} {'T':>4} {'통과':>4} | {'2/2':>4}")
    print("-" * 75)

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
            sh_str = f"{sh:+.3f}" if not np.isnan(sh) else "  nan"
            cols.append(f"{sh_str:>10} {wr:>4.0%} {t:>4} {ok:>4}")

        all_pass = "✅" if pass_count == 2 else "❌"
        print(f"{slip_pct:>6} | {cols[0]} | {cols[1]} | {pass_count}/2 {all_pass}")
        summary_rows.append({
            "slip":      slip,
            "w1_sh":     row_results[0]["oos"]["sharpe"],
            "w2_sh":     row_results[1]["oos"]["sharpe"],
            "w1_wr":     row_results[0]["oos"]["wr"],
            "w2_wr":     row_results[1]["oos"]["wr"],
            "w1_t":      row_results[0]["oos"]["trades"],
            "w2_t":      row_results[1]["oos"]["trades"],
            "w1_pass":   row_results[0]["passed"],
            "w2_pass":   row_results[1]["passed"],
            "pass_count": pass_count,
        })

    # ── 분석 ──────────────────────────────────────────────────────────────────
    print()
    base = summary_rows[0]
    base_avg = np.nanmean([base["w1_sh"], base["w2_sh"]])
    print(f"★ 기준(슬리피지 0%): W1={base['w1_sh']:+.3f}, W2={base['w2_sh']:+.3f}, "
          f"avg={base_avg:+.3f}, 통과={base['pass_count']}/2")

    print()
    print("=== Sharpe 감쇠율 ===")
    for row in summary_rows[1:]:
        avg_sh = np.nanmean([row["w1_sh"], row["w2_sh"]])
        decay  = (base_avg - avg_sh) / abs(base_avg) * 100 if base_avg != 0 else 0
        ok_str = "✅ 2/2" if row["pass_count"] == 2 else "❌"
        print(f"  슬리피지 {row['slip']*100:.2f}%: W1={row['w1_sh']:+.3f} "
              f"W2={row['w2_sh']:+.3f} avg={avg_sh:+.3f} "
              f"(감쇠 {decay:+.1f}%) → {ok_str}")

    print()
    print("=== 슬리피지 임계점 분석 ===")
    first_fail = None
    for row in summary_rows:
        if row["pass_count"] < 2:
            first_fail = row["slip"]
            break
    if first_fail is not None:
        print(f"⚠️  2/2 미달 첫 슬리피지: {first_fail*100:.2f}%")
    else:
        print("✅ 모든 슬리피지 구간에서 2/2창 통과")

    print()
    print("=== 결론 ===")
    # 현실적 슬리피지: 0.10% (Upbit ONDO 유동성 감안)
    real_row = next((r for r in summary_rows if abs(r["slip"] - 0.001) < 0.0001), None)
    if real_row:
        real_avg = np.nanmean([real_row["w1_sh"], real_row["w2_sh"]])
        still_ok = real_row["pass_count"] == 2
        print(f"현실적 슬리피지 0.10%: W1={real_row['w1_sh']:+.3f} "
              f"W2={real_row['w2_sh']:+.3f} avg={real_avg:+.3f}, "
              f"통과 {real_row['pass_count']}/2 → "
              f"{'엣지 유지 ✅ daemon 반영 가능' if still_ok else '엣지 소멸 ⚠️ 재검토 필요'}")

    high_row = next((r for r in summary_rows if abs(r["slip"] - 0.002) < 0.0001), None)
    if high_row:
        high_avg = np.nanmean([high_row["w1_sh"], high_row["w2_sh"]])
        still_ok = high_row["pass_count"] == 2
        print(f"높은 슬리피지 0.20%: W1={high_row['w1_sh']:+.3f} "
              f"W2={high_row['w2_sh']:+.3f} avg={high_avg:+.3f}, "
              f"통과 {high_row['pass_count']}/2 → "
              f"{'엣지 유지 ✅' if still_ok else '엣지 소멸 ⚠️'}")

    print()
    # daemon 반영 여부 최종 판정
    real_row = next((r for r in summary_rows if abs(r["slip"] - 0.001) < 0.0001), None)
    if real_row and real_row["pass_count"] == 2:
        print("▶ daemon.toml 반영 권고: ONDO vpin 슬리피지 0.10% 이하에서 엣지 유지")
        print(f"  파라미터: vh={VH} vm={VM} hold={HOLD} TP={TP*100:.0f}% "
              f"SL={SL*100:.1f}% Gate1=BTC>SMA20")
    else:
        print("▶ daemon.toml 반영 보류: 슬리피지 민감도 과도 → 파라미터 재검토 필요")


if __name__ == "__main__":
    main()
