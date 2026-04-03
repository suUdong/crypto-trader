"""
사이클 119: ONDO vpin 전략 탐색
- 목적: ONDO stealth_3gate W1 실패(Sharpe -1.487) 극복 → vpin 프레임워크로 2창 통과 가능성 탐색
- 배경:
    사이클 112: ONDO stealth_3gate
        W1 OOS(2025-01~2025-12): Sharpe -1.487, WR=25%, n=24 → 실패
        W2 OOS(2025-07~2026-04): Sharpe +5.762, WR=60%, n=10 → 통과 (1/2창)
    가설: vpin(volume imbalance 기반)은 stealth(RS 기반)와 독립적 메커니즘
          → 2025H1에도 엣지 보유 가능성 탐색
- 데이터: KRW-ONDO 240m, 2024-06~2026-03 (21개월)
- WF 창:
    W1: IS=2024-06~2024-12, OOS=2025-01~2025-09 (BULL 기간, 9개월 OOS)
    W2: IS=2024-06~2025-06, OOS=2025-07~2026-04 (혼재, 10개월 OOS)
- 판정 기준: OOS Sharpe > 5.0 && WR > 25% && trades >= 5 (2/2창)
- 그리드: vh × vm × hold × TP × SL × Gate1 = 3×3×2×4×3×2 = 432조합
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL  = "KRW-ONDO"
BTC_SYM = "KRW-BTC"
FEE     = 0.0005   # 0.05% 편도
CTYPE   = "240m"

# Walk-forward windows (ONDO 데이터: 2024-06 시작)
WINDOWS = [
    {
        "name": "W1",
        "is_start":  "2024-06-01", "is_end":  "2024-12-31",
        "oos_start": "2025-01-01", "oos_end": "2025-09-30",
    },
    {
        "name": "W2",
        "is_start":  "2024-06-01", "is_end":  "2025-06-30",
        "oos_start": "2025-07-01", "oos_end": "2026-04-04",
    },
]

# 기준선: vpin_eth daemon 파라미터 그대로 ONDO에 적용
BASELINE = dict(vh=0.55, vm=0.0005, hold=18, tp=0.06, sl=0.008)

# 그리드 탐색
# ONDO는 신규 상장 알트 → SUI와 동일 범위 (변동성 높음)
GRID = {
    "vh":   [0.50, 0.55, 0.60],
    "vm":   [0.0003, 0.0005, 0.0010],
    "hold": [12, 18],
    "tp":   [0.06, 0.08, 0.10, 0.12],
    "sl":   [0.008, 0.015, 0.025],
}

GATE1_OPTIONS = [False, True]

# 고정 지표 파라미터
RSI_PERIOD     = 14
RSI_CEILING    = 65.0
RSI_FLOOR      = 20.0
BUCKET_COUNT   = 24
EMA_PERIOD     = 20
MOM_LOOKBACK   = 8
BTC_SMA_PERIOD = 20

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


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_sym: pd.DataFrame,
    df_btc: pd.DataFrame | None,
    vh: float, vm: float, hold: int, tp: float, sl: float,
    use_gate1: bool,
) -> dict:
    c = df_sym["close"].values
    o = df_sym["open"].values
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr  = compute_vpin_momentum(c, MOM_LOOKBACK)

    if use_gate1 and df_btc is not None and len(df_btc) > 0:
        btc_c = df_btc["close"].values
        btc_sma_arr = sma(btc_c, BTC_SMA_PERIOD)
        btc_index = pd.Series(btc_sma_arr, index=df_btc.index)
        btc_close_s = pd.Series(btc_c, index=df_btc.index)
        sym_ts = df_sym.index
        gate1_arr = np.zeros(n, dtype=bool)
        for idx_i, ts in enumerate(sym_ts):
            try:
                loc = btc_index.index.get_indexer([ts], method="pad")[0]
                if loc >= 0:
                    gate1_arr[idx_i] = (
                        btc_close_s.iloc[loc] > btc_sma_arr[loc]
                        if not np.isnan(btc_sma_arr[loc]) else False
                    )
            except Exception:
                pass
    else:
        gate1_arr = np.ones(n, dtype=bool)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK, BTC_SMA_PERIOD) + 5
    i = warmup
    while i < n - 1:
        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]
        gate1_ok = bool(gate1_arr[i]) if use_gate1 else True

        if (gate1_ok
                and not np.isnan(vpin_val) and vpin_val > vh
                and not np.isnan(mom_val)  and mom_val > vm
                and not np.isnan(rsi_val)  and RSI_FLOOR < rsi_val < RSI_CEILING
                and not np.isnan(ema_val)  and c[i] > ema_val):

            buy = c[i + 1] * (1.0 + FEE)
            exited = False
            for j in range(i + 2, min(i + 1 + hold, n)):
                ret = c[j] / buy - 1
                if ret >= tp:
                    returns.append(tp - FEE)
                    i = j
                    exited = True
                    break
                if ret <= -sl:
                    returns.append(-sl - FEE)
                    i = j
                    exited = True
                    break

            if not exited:
                hold_end = min(i + hold, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE)
                i = hold_end
        else:
            i += 1

    if len(returns) < PASS_TRADES:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def run_window(w: dict, use_gate1: bool, params: dict) -> dict:
    df_sym_is  = load_historical(SYMBOL,  CTYPE, w["is_start"],  w["is_end"])
    df_sym_oos = load_historical(SYMBOL,  CTYPE, w["oos_start"], w["oos_end"])

    if use_gate1:
        df_btc_is  = load_historical(BTC_SYM, CTYPE, w["is_start"],  w["is_end"])
        df_btc_oos = load_historical(BTC_SYM, CTYPE, w["oos_start"], w["oos_end"])
    else:
        df_btc_is  = None
        df_btc_oos = None

    is_r  = backtest(df_sym_is,  df_btc_is,  **params, use_gate1=use_gate1)
    oos_r = backtest(df_sym_oos, df_btc_oos, **params, use_gate1=use_gate1)

    passed = (
        not np.isnan(oos_r["sharpe"])
        and oos_r["sharpe"] >= PASS_SHARPE
        and oos_r["wr"]     >= PASS_WR
        and oos_r["trades"] >= PASS_TRADES
    )
    return {"name": w["name"], "is": is_r, "oos": oos_r, "passed": passed}


def run_combo(use_gate1: bool, params: dict) -> dict:
    results    = [run_window(w, use_gate1, params) for w in WINDOWS]
    pass_count = sum(r["passed"] for r in results)
    avg_sharpe = float(np.nanmean([r["oos"]["sharpe"] for r in results]))
    return {
        "gate1": use_gate1,
        "params": params,
        "results": results,
        "pass_count": pass_count,
        "avg_sharpe": avg_sharpe,
    }


def main() -> None:
    print("=" * 75)
    print("사이클 119: ONDO vpin 전략 탐색")
    print(f"심볼: {SYMBOL} / 타임프레임: {CTYPE}")
    print(f"판정 기준: OOS Sharpe > {PASS_SHARPE}, WR > {PASS_WR:.0%}, trades >= {PASS_TRADES}")
    print("WF 창: W1 OOS=2025-01~2025-09(BULL), W2 OOS=2025-07~2026-04(혼재)")
    print("배경: stealth_3gate W1 Sharpe -1.487 → vpin 독립 메커니즘으로 극복 탐색")
    print("=" * 75)

    # ── 1단계: 기준선 테스트 ───────────────────────────────────────────────────
    print("\n▶ 1단계: 기준선 테스트 (vpin_eth daemon 파라미터 ONDO 적용)")
    print(f"  파라미터: vh={BASELINE['vh']} vm={BASELINE['vm']} hold={BASELINE['hold']} "
          f"TP={BASELINE['tp']*100:.0f}% SL={BASELINE['sl']*100:.1f}%")

    for use_gate1 in [False, True]:
        gate_label = "BTC Gate1 포함" if use_gate1 else "BTC Gate1 없음"
        print(f"\n  [{gate_label}]")
        print(f"  {'창':>4} | {'IS Sh':>8} {'IS n':>5} | {'OOS Sh':>8} {'WR':>5} {'n':>4} | 통과")
        print(f"  {'-'*55}")
        pass_total = 0
        for w in WINDOWS:
            r = run_window(w, use_gate1, BASELINE)
            is_sh  = r["is"]["sharpe"]
            oos_sh = r["oos"]["sharpe"]
            wr     = r["oos"]["wr"]
            t      = r["oos"]["trades"]
            ok     = "✅" if r["passed"] else "❌"
            is_str  = f"{is_sh:+.3f}" if not np.isnan(is_sh) else "  nan"
            oos_str = f"{oos_sh:+.3f}" if not np.isnan(oos_sh) else "  nan"
            print(f"  {r['name']:>4} | {is_str:>8} {r['is']['trades']:>5} | "
                  f"{oos_str:>8} {wr:>4.0%} {t:>4} | {ok}")
            if r["passed"]:
                pass_total += 1
        print(f"  → {pass_total}/2창 통과")

    # ── 2단계: 그리드 탐색 ────────────────────────────────────────────────────
    keys   = list(GRID.keys())
    combos = list(itertools.product(*GRID.values()))
    total  = len(combos) * len(GATE1_OPTIONS)
    print(f"\n▶ 2단계: 그리드 탐색 ({len(combos)}조합 × {len(GATE1_OPTIONS)}Gate = {total}총)")
    print(f"  {'#':>4} {'G1':>3} {'vh':>5} {'vm':>7} {'hld':>4} {'TP':>5} {'SL':>5} | "
          f"{'W1 OOS':>8} {'WR':>5} | {'W2 OOS':>8} {'WR':>5} | {'avg':>7} | 통과")
    print("  " + "-" * 95)

    all_results = []
    n_done = 0
    for use_gate1 in GATE1_OPTIONS:
        for values in combos:
            params = dict(zip(keys, values))
            combo  = run_combo(use_gate1, params)
            all_results.append(combo)
            n_done += 1

            r1 = combo["results"][0]["oos"]
            r2 = combo["results"][1]["oos"]
            sh1 = f"{r1['sharpe']:+.3f}" if not np.isnan(r1["sharpe"]) else "  nan"
            sh2 = f"{r2['sharpe']:+.3f}" if not np.isnan(r2["sharpe"]) else "  nan"
            avg = f"{combo['avg_sharpe']:+.3f}"
            g   = "Y" if use_gate1 else "N"
            ok  = f"{combo['pass_count']}/2"
            flag = " ★" if combo["pass_count"] == 2 else (" ◆" if combo["pass_count"] == 1 else "")

            print(
                f"  {n_done:>4} {g:>3} "
                f"{params['vh']:>5.2f} {params['vm']:>7.4f} {params['hold']:>4} "
                f"{params['tp']*100:>4.0f}% {params['sl']*100:>4.1f}% | "
                f"{sh1:>8} {r1['wr']:>4.0%} | "
                f"{sh2:>8} {r2['wr']:>4.0%} | "
                f"{avg:>7} | {ok}{flag}"
            )

    # ── 결과 요약 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 75)
    print("▶ 결과 요약")

    two_pass = [r for r in all_results if r["pass_count"] == 2]
    one_pass = [r for r in all_results if r["pass_count"] == 1]

    print(f"\n2/2창 통과: {len(two_pass)}개")
    if two_pass:
        two_pass.sort(key=lambda x: x["avg_sharpe"], reverse=True)
        print("  상위 10개 (avg Sharpe 기준):")
        for combo in two_pass[:10]:
            p = combo["params"]
            r1 = combo["results"][0]["oos"]
            r2 = combo["results"][1]["oos"]
            g  = "Gate1" if combo["gate1"] else "NoGate"
            print(
                f"    {g} vh={p['vh']:.2f} vm={p['vm']:.4f} hold={p['hold']} "
                f"TP={p['tp']*100:.0f}% SL={p['sl']*100:.1f}% | "
                f"W1={r1['sharpe']:+.3f}({r1['wr']:.0%} n={r1['trades']}) "
                f"W2={r2['sharpe']:+.3f}({r2['wr']:.0%} n={r2['trades']}) "
                f"avg={combo['avg_sharpe']:+.3f} ★"
            )
    else:
        print("  없음 — ONDO vpin 2/2창 기준 미충족")

    print(f"\n1/2창 통과: {len(one_pass)}개")
    if one_pass:
        one_pass.sort(key=lambda x: x["avg_sharpe"], reverse=True)
        print("  상위 5개 (avg Sharpe 기준):")
        for combo in one_pass[:5]:
            p = combo["params"]
            r1 = combo["results"][0]["oos"]
            r2 = combo["results"][1]["oos"]
            g  = "Gate1" if combo["gate1"] else "NoGate"
            print(
                f"    {g} vh={p['vh']:.2f} vm={p['vm']:.4f} hold={p['hold']} "
                f"TP={p['tp']*100:.0f}% SL={p['sl']*100:.1f}% | "
                f"W1={r1['sharpe']:+.3f}({r1['wr']:.0%} n={r1['trades']}) "
                f"W2={r2['sharpe']:+.3f}({r2['wr']:.0%} n={r2['trades']}) "
                f"avg={combo['avg_sharpe']:+.3f}"
            )

    # Gate1 효과 분석
    print("\n▶ BTC Gate1 효과 분석")
    for use_gate1 in GATE1_OPTIONS:
        sub = [r for r in all_results if r["gate1"] == use_gate1]
        avg_all = float(np.nanmean([r["avg_sharpe"] for r in sub]))
        passed  = sum(r["pass_count"] == 2 for r in sub)
        g_label = "Gate1 포함" if use_gate1 else "Gate1 없음"
        print(f"  {g_label}: 평균 avg Sharpe {avg_all:+.3f}, 2/2창 통과 {passed}/{len(sub)}")

    # 최고 조합
    best = max(all_results, key=lambda x: x["avg_sharpe"])
    p = best["params"]
    print(f"\n▶ 최고 avg Sharpe 조합:")
    g = "Gate1 포함" if best["gate1"] else "Gate1 없음"
    print(f"  {g} vh={p['vh']:.2f} vm={p['vm']:.4f} hold={p['hold']} "
          f"TP={p['tp']*100:.0f}% SL={p['sl']*100:.1f}%")
    for res in best["results"]:
        oos = res["oos"]
        sh_str = f"{oos['sharpe']:+.3f}" if not np.isnan(oos["sharpe"]) else "nan"
        print(f"  {res['name']}: OOS Sharpe={sh_str}, WR={oos['wr']:.0%}, n={oos['trades']}, "
              f"{'통과 ✅' if res['passed'] else '탈락 ❌'}")
    print(f"  avg Sharpe={best['avg_sharpe']:+.3f}, {best['pass_count']}/2창")

    print("\n▶ 결론")
    if two_pass:
        best2 = two_pass[0]
        p2 = best2["params"]
        g2 = "BTC Gate1 포함" if best2["gate1"] else "BTC Gate1 없음"
        print(f"  ✅ ONDO vpin 전략 유효! 2/2창 통과 {len(two_pass)}개")
        print(f"  최적: {g2} vh={p2['vh']:.2f} vm={p2['vm']:.4f} hold={p2['hold']} "
              f"TP={p2['tp']*100:.0f}% SL={p2['sl']*100:.1f}% (avg={best2['avg_sharpe']:+.3f})")
        print("  → daemon 반영 검토 가능 (Sharpe > 5.0 기준 충족)")
    elif one_pass:
        best1 = one_pass[0]
        print(f"  ◆ ONDO vpin 1/2창 통과 — 추가 검증 필요")
        print(f"  최고 avg Sharpe: {best1['avg_sharpe']:+.3f}")
    else:
        print("  ❌ ONDO vpin 기준 미달 — 다른 전략/심볼 탐색 필요")
        print(f"  최고 avg Sharpe: {best['avg_sharpe']:+.3f}")


if __name__ == "__main__":
    main()
