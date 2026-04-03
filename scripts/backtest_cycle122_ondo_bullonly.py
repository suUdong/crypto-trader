"""
사이클 122: ONDO vpin BULL-only 조건부 배포 설계
- 목적: BULL 기간(W1)에만 엣지 있는 ONDO vpin을 실용적으로 배포하기 위해
         BTC 강세 지속 Gate2를 추가 — W2(BEAR/혼재) 신호 차단 + W1 엣지 보존
- 배경:
  사이클 119: W1 Sharpe +9.132, W2 +5.296 (슬리피지 0%)
  사이클 120: 슬리피지 0.05%에서 W2 즉시 탈락 → daemon 반영 보류
  핵심 발견: W1(BULL)은 슬리피지 0.20%까지도 5.0+ 유지, W2(BEAR/혼재) 구조적 약점
- 전략: BTC Gate1(SMA20) + Gate2(BTC 강세 지속) 복합 필터
  Gate2 후보:
  (a) BTC N봉 수익률 > threshold (BTC 단기 모멘텀 양수)
  (b) BTC SMA20 이격률 > threshold (BTC 상승 추세 강도)
  (c) BTC 연속 양봉 수 >= N
- 목표: W2 신호 차단 비율 최대화 + W1 신호 유지 비율 최대화
- 고정 파라미터: vh=0.55, vm=0.0005, hold=18, TP=10%, SL=1.5%, Gate1=Y
- 슬리피지: 0.00%, 0.05%, 0.10% (3종)
- WF: W1 OOS=2025-01~2025-09 (BULL), W2 OOS=2025-07~2026-04 (BEAR/혼재)
- 판정 기준: OOS Sharpe > 5.0 && WR > 25% && trades >= 5
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
    {"name": "W1", "oos_start": "2025-01-01", "oos_end": "2025-09-30"},
    {"name": "W2", "oos_start": "2025-07-01", "oos_end": "2026-04-04"},
]

# 사이클 119 확정 파라미터
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

# 슬리피지 테스트
SLIPPAGE_LIST = [0.0, 0.0005, 0.001]

# 판정 기준
PASS_SHARPE = 5.0
PASS_WR     = 0.25
PASS_TRADES = 5

# Gate2 설정: (이름, 파라미터 딕셔너리)
# type=btc_mom_N_th: BTC N봉 수익률 > threshold
# type=btc_sma_gap_th: BTC close/SMA20 - 1 > threshold
# type=btc_consec_N: BTC 연속 양봉 >= N
GATE2_CONFIGS = [
    {"name": "없음(기준)", "type": "none"},
    # BTC 단기 모멘텀 양수 조건
    {"name": "BTC_30봉수익률>-3%", "type": "btc_mom", "lookback": 30, "threshold": -0.03},
    {"name": "BTC_30봉수익률>-2%", "type": "btc_mom", "lookback": 30, "threshold": -0.02},
    {"name": "BTC_30봉수익률>0%",  "type": "btc_mom", "lookback": 30, "threshold": 0.0},
    {"name": "BTC_60봉수익률>-5%", "type": "btc_mom", "lookback": 60, "threshold": -0.05},
    {"name": "BTC_60봉수익률>-3%", "type": "btc_mom", "lookback": 60, "threshold": -0.03},
    {"name": "BTC_60봉수익률>0%",  "type": "btc_mom", "lookback": 60, "threshold": 0.0},
    # BTC SMA20 이격률 조건 (SMA20 위 N% 이상 = 강한 상승 추세)
    {"name": "BTC_SMA이격>-2%", "type": "btc_sma_gap", "threshold": -0.02},
    {"name": "BTC_SMA이격>0%",  "type": "btc_sma_gap", "threshold": 0.0},
    {"name": "BTC_SMA이격>+2%", "type": "btc_sma_gap", "threshold": 0.02},
    # BTC 연속 양봉 조건
    {"name": "BTC_연속양봉>=2", "type": "btc_consec", "n": 2},
    {"name": "BTC_연속양봉>=3", "type": "btc_consec", "n": 3},
]


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


def compute_vpin(closes: np.ndarray, opens: np.ndarray, bucket_count: int = 24) -> np.ndarray:
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


# ── BTC 보조 지표 계산 ───────────────────────────────────────────────────────

def compute_btc_extras(df_btc: pd.DataFrame) -> dict:
    """BTC Gate2 계산용 보조 지표 반환."""
    c = df_btc["close"].values
    o = df_btc["open"].values
    n = len(c)
    sma20 = sma(c, BTC_SMA_PERIOD)

    # 연속 양봉 수
    consec = np.zeros(n, dtype=int)
    for i in range(1, n):
        if c[i] > o[i]:
            consec[i] = consec[i - 1] + 1
        else:
            consec[i] = 0

    return {
        "close":  c,
        "sma20":  sma20,
        "consec": consec,
        "index":  df_btc.index,
        "n":      n,
    }


def get_btc_gate2(btc_extras: dict, ts: pd.Timestamp, gate2_cfg: dict) -> bool:
    """주어진 시점(ts)에서 Gate2 조건 평가."""
    if gate2_cfg["type"] == "none":
        return True

    idx = btc_extras["index"].get_indexer([ts], method="pad")[0]
    if idx < 0:
        return False

    c      = btc_extras["close"]
    sma20  = btc_extras["sma20"]
    consec = btc_extras["consec"]

    if gate2_cfg["type"] == "btc_mom":
        lb = gate2_cfg["lookback"]
        th = gate2_cfg["threshold"]
        if idx < lb:
            return False
        ret = c[idx] / c[idx - lb] - 1
        return bool(ret > th)

    if gate2_cfg["type"] == "btc_sma_gap":
        th = gate2_cfg["threshold"]
        if np.isnan(sma20[idx]) or sma20[idx] == 0:
            return False
        gap = c[idx] / sma20[idx] - 1
        return bool(gap > th)

    if gate2_cfg["type"] == "btc_consec":
        return bool(consec[idx] >= gate2_cfg["n"])

    return True


# ── 백테스트 ─────────────────────────────────────────────────────────────────

def backtest(
    df_sym: pd.DataFrame,
    df_btc: pd.DataFrame | None,
    slippage: float,
    gate2_cfg: dict,
) -> dict:
    c = df_sym["close"].values
    o = df_sym["open"].values
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr  = compute_vpin_momentum(c, MOM_LOOKBACK)

    # BTC Gate1 (SMA20)
    gate1_arr = np.zeros(n, dtype=bool)
    btc_extras: dict | None = None
    if df_btc is not None and len(df_btc) > 0:
        btc_c      = df_btc["close"].values
        btc_sma    = sma(btc_c, BTC_SMA_PERIOD)
        btc_sma_s  = pd.Series(btc_sma,  index=df_btc.index)
        btc_c_s    = pd.Series(btc_c,    index=df_btc.index)
        sym_ts     = df_sym.index
        for idx_i, ts in enumerate(sym_ts):
            loc = btc_sma_s.index.get_indexer([ts], method="pad")[0]
            if loc >= 0 and not np.isnan(btc_sma[loc]):
                gate1_arr[idx_i] = bool(btc_c_s.iloc[loc] > btc_sma_s.iloc[loc])
        btc_extras = compute_btc_extras(df_btc)
    else:
        gate1_arr = np.ones(n, dtype=bool)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK, BTC_SMA_PERIOD) + 5
    i = warmup
    while i < n - 1:
        gate1_ok = bool(gate1_arr[i])

        # Gate2 확인
        gate2_ok = True
        if btc_extras is not None:
            ts = df_sym.index[i]
            gate2_ok = get_btc_gate2(btc_extras, ts, gate2_cfg)

        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]

        if (gate1_ok and gate2_ok
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


def run_window(w: dict, slippage: float, gate2_cfg: dict) -> dict:
    df_sym = load_historical(SYMBOL,  CTYPE, w["oos_start"], w["oos_end"])
    df_btc = load_historical(BTC_SYM, CTYPE, w["oos_start"], w["oos_end"])
    oos_r  = backtest(df_sym, df_btc, slippage, gate2_cfg)
    passed = (
        not np.isnan(oos_r["sharpe"])
        and oos_r["sharpe"] >= PASS_SHARPE
        and oos_r["wr"]     >= PASS_WR
        and oos_r["trades"] >= PASS_TRADES
    )
    return {"name": w["name"], "oos": oos_r, "passed": passed}


def main() -> None:
    print("=" * 80)
    print("사이클 122: ONDO vpin BULL-only Gate2 탐색")
    print(f"고정 파라미터: vh={VH} vm={VM} hold={HOLD} TP={TP*100:.0f}% SL={SL*100:.1f}% Gate1=Y")
    print(f"Gate2 후보: {len(GATE2_CONFIGS)}개 (BTC 모멘텀 / SMA 이격 / 연속 양봉)")
    print(f"슬리피지: {[f'{s*100:.2f}%' for s in SLIPPAGE_LIST]}")
    print(f"판정 기준: Sharpe > {PASS_SHARPE} && WR > {PASS_WR:.0%} && trades >= {PASS_TRADES}")
    print("=" * 80)

    all_results: list[dict] = []

    for gate2_cfg in GATE2_CONFIGS:
        print(f"\n{'─'*70}")
        print(f"[Gate2: {gate2_cfg['name']}]")
        print(f"{'Slip%':>6} | {'W1 Sharpe':>10} {'WR':>5} {'T':>4} {'통과':>4} | "
              f"{'W2 Sharpe':>10} {'WR':>5} {'T':>4} {'통과':>4} | {'2/2':>5}")
        print("-" * 70)

        for slip in SLIPPAGE_LIST:
            row_results = []
            pass_count  = 0
            for w in WINDOWS:
                res = run_window(w, slip, gate2_cfg)
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

            all_results.append({
                "gate2":      gate2_cfg["name"],
                "slip":       slip,
                "w1_sh":      row_results[0]["oos"]["sharpe"],
                "w2_sh":      row_results[1]["oos"]["sharpe"],
                "w1_wr":      row_results[0]["oos"]["wr"],
                "w2_wr":      row_results[1]["oos"]["wr"],
                "w1_t":       row_results[0]["oos"]["trades"],
                "w2_t":       row_results[1]["oos"]["trades"],
                "w1_pass":    row_results[0]["passed"],
                "w2_pass":    row_results[1]["passed"],
                "pass_count": pass_count,
            })

    # ── 요약 분석 ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("=== 종합 분석 (슬리피지 0.05% 기준) ===")
    print()

    # 기준값 (Gate2 없음, 슬리피지 0%)
    base = next(r for r in all_results if r["gate2"] == "없음(기준)" and r["slip"] == 0.0)
    print(f"★ 기준(Gate2 없음, slip=0%): W1={base['w1_sh']:+.3f}(n={base['w1_t']}) "
          f"W2={base['w2_sh']:+.3f}(n={base['w2_t']}), 통과={base['pass_count']}/2")

    # slip=0.05% 기준 비교표
    slip_target = 0.0005
    print(f"\n{'Gate2 조건':>22} | {'W1 Sh':>8} {'T':>4} {'통':>3} | "
          f"{'W2 Sh':>8} {'T':>4} {'통':>3} | {'2/2':>5} | {'W2 신호 감소':>10}")
    print("-" * 78)

    base_slip = next(
        r for r in all_results if r["gate2"] == "없음(기준)" and abs(r["slip"] - slip_target) < 1e-6
    )
    base_w2_t = base_slip["w2_t"] if base_slip["w2_t"] > 0 else 1

    for g_cfg in GATE2_CONFIGS:
        row = next(
            (r for r in all_results
             if r["gate2"] == g_cfg["name"] and abs(r["slip"] - slip_target) < 1e-6),
            None,
        )
        if row is None:
            continue
        w1_sh = row["w1_sh"]
        w2_sh = row["w2_sh"]
        w1_sh_str = f"{w1_sh:+.3f}" if not np.isnan(w1_sh) else " nan "
        w2_sh_str = f"{w2_sh:+.3f}" if not np.isnan(w2_sh) else " nan "
        ok2 = "✅" if row["pass_count"] == 2 else "❌"
        reduce_pct = (1 - row["w2_t"] / base_w2_t) * 100 if base_w2_t > 0 else 0
        print(f"{row['gate2']:>22} | {w1_sh_str:>8} {row['w1_t']:>4} "
              f"{'✅' if row['w1_pass'] else '❌':>3} | "
              f"{w2_sh_str:>8} {row['w2_t']:>4} "
              f"{'✅' if row['w2_pass'] else '❌':>3} | "
              f"{row['pass_count']}/2 {ok2} | "
              f"-{reduce_pct:.0f}%")

    # 2/2 통과 조합 있는지 확인
    winners = [r for r in all_results if r["pass_count"] == 2]
    print()
    if winners:
        print(f"★ 2/2 통과 조합 {len(winners)}개 발견!")
        for w in winners[:5]:
            avg_sh = np.nanmean([w["w1_sh"], w["w2_sh"]])
            print(f"  Gate2={w['gate2']} slip={w['slip']*100:.2f}%: "
                  f"W1={w['w1_sh']:+.3f} W2={w['w2_sh']:+.3f} avg={avg_sh:+.3f}")
    else:
        print("⚠️  2/2 통과 조합 없음 — Gate2로 W2 살리기 불가")
        # 가장 높은 W2 Sharpe 조합 출력
        best_w2 = max(
            (r for r in all_results if not np.isnan(r["w2_sh"])),
            key=lambda r: r["w2_sh"],
        )
        avg_sh = np.nanmean([best_w2["w1_sh"], best_w2["w2_sh"]])
        print(f"  최고 W2: Gate2={best_w2['gate2']} slip={best_w2['slip']*100:.2f}% "
              f"W1={best_w2['w1_sh']:+.3f} W2={best_w2['w2_sh']:+.3f} avg={avg_sh:+.3f}")

    # W1 엣지 보존 + W2 신호 최대 차단 균형점
    print()
    print("=== W1 엣지 보존 vs W2 신호 차단 균형점 (slip=0.05%) ===")
    slip_rows = [r for r in all_results if abs(r["slip"] - 0.0005) < 1e-6]
    print(f"{'Gate2 조건':>22} | {'W1 Sh':>8} {'W1n':>4} | {'W2 Sh':>8} {'W2n':>4} | {'W2차단율':>8}")
    print("-" * 70)
    for row in slip_rows:
        w1_sh = row["w1_sh"]
        w2_sh = row["w2_sh"]
        w1_sh_s = f"{w1_sh:+.3f}" if not np.isnan(w1_sh) else " nan "
        w2_sh_s = f"{w2_sh:+.3f}" if not np.isnan(w2_sh) else " nan "
        reduce_pct = (1 - row["w2_t"] / base_w2_t) * 100 if base_w2_t > 0 else 0
        print(f"{row['gate2']:>22} | {w1_sh_s:>8} {row['w1_t']:>4} | "
              f"{w2_sh_s:>8} {row['w2_t']:>4} | {reduce_pct:>7.0f}%")

    print()
    print("=== 결론 ===")
    if winners:
        best = max(winners, key=lambda r: np.nanmean([r["w1_sh"], r["w2_sh"]]))
        avg_sh = np.nanmean([best["w1_sh"], best["w2_sh"]])
        print(f"▶ BULL-only Gate2 성공: {best['gate2']} (slip={best['slip']*100:.2f}%)")
        print(f"  W1={best['w1_sh']:+.3f} W2={best['w2_sh']:+.3f} avg={avg_sh:+.3f}")
        print(f"  → daemon.toml 조건부 배포 가능 검토")
    else:
        print("▶ Gate2 추가로도 W2 Sharpe 5.0 달성 불가")
        print("  → ONDO vpin은 BULL-only 특화 전략 확정 (W2 구조적 취약)")
        print("  → BULL 전환(pre_bull ≥ 0.90) 시점에 W1 엣지만 활용하는 conditional 배포 설계 필요")
        # W2 신호를 많이 차단하면서 W1을 가장 잘 보존하는 Gate2 추천
        best_tradeoff = max(
            (r for r in slip_rows if not np.isnan(r["w1_sh"]) and r["w1_t"] >= PASS_TRADES),
            key=lambda r: (0 if np.isnan(r["w2_sh"]) else r["w2_sh"]),
            default=None,
        )
        if best_tradeoff:
            reduce_pct = (1 - best_tradeoff["w2_t"] / base_w2_t) * 100
            print(f"  최선 Gate2 (W2 Sharpe 최대화): {best_tradeoff['gate2']} "
                  f"W1={best_tradeoff['w1_sh']:+.3f} W2={best_tradeoff['w2_sh']:+.3f} "
                  f"W2차단율={reduce_pct:.0f}%")


if __name__ == "__main__":
    main()
