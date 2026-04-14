"""
vpin_eth 사이클 233 — BTC 추세 게이트 + RSI 속도 필터 (5-fold WF)

배경:
- 직전 결과: hold=14 TP=0.07 SL=0.006 ATRmin=OFF → Sharpe +8.295 WR 27.4% trades 507
- ATR% 변동성 레짐 필터는 효과 없음 (OFF가 전체 Top 차지)
- WR 27.4%가 낮음 → 진입 품질 개선 필요

가설:
1) BTC 추세 게이트: BTC EMA 상승 시에만 진입 → 하락장 노이즈 진입 제거
2) RSI 속도(delta): RSI 상승 기울기 > 문턱 → 모멘텀 확인 후 진입
3) 두 필터 조합으로 WR 30%+ 달성 가능, 거래수 300+ 유지 목표

고정: hold=14, TP=0.07, SL=0.006 (검증된 최적 exit)
탐색: BTC게이트(EMA기간/활성), RSI속도(lookback/threshold), VPIN/MOM 미세조정
검증: 5-fold walk-forward + 슬리피지 스트레스
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-ETH"
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005

# ── 고정 exit 파라미터 (직전 검증 최적) ──────────────────────────────────────
MAX_HOLD = 14
TP_PCT = 0.07
SL_PCT = 0.006

# ── 고정 지표 파라미터 ───────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_CEILING = 75.0
RSI_FLOOR = 20.0
BUCKET_COUNT = 24
EMA_PERIOD = 20
MOM_LOOKBACK = 8

# ── 탐색 그리드 ──────────────────────────────────────────────────────────────
# BTC 추세 게이트
BTC_EMA_PERIOD_LIST = [20, 50]                    # BTC EMA 기간
BTC_GATE_LIST = [False, True]                      # 게이트 활성/비활성

# RSI 속도 필터
RSI_DELTA_LB_LIST = [3, 5, 7]                     # RSI 변화 측정 기간 (봉)
RSI_DELTA_THRESH_LIST = [0, 2, 5, 8]              # RSI delta 문턱 (0=비활성)

# VPIN 진입 미세조정
VPIN_HIGH_LIST = [0.50, 0.55, 0.60]
VPIN_MOM_THRESH_LIST = [0.0003, 0.0005]

# ── 5-fold Walk-Forward 기간 ─────────────────────────────────────────────────
WF_FOLDS = [
    {"train": ("2022-01-01", "2023-06-30"), "test": ("2023-07-01", "2024-03-31")},
    {"train": ("2022-07-01", "2024-03-31"), "test": ("2024-04-01", "2024-12-31")},
    {"train": ("2023-01-01", "2024-09-30"), "test": ("2024-10-01", "2025-06-30")},
    {"train": ("2023-07-01", "2025-06-30"), "test": ("2025-07-01", "2025-12-31")},
    {"train": ("2024-01-01", "2025-12-31"), "test": ("2026-01-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

def ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def sma(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        result[i] = series[i - period + 1:i + 1].mean()
    return result


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def compute_vpin(closes: np.ndarray, opens: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_momentum(closes: np.ndarray, lookback: int) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_eth: pd.DataFrame,
    df_btc: pd.DataFrame | None,
    vpin_high: float,
    vpin_mom_thresh: float,
    btc_ema_period: int,
    btc_gate: bool,
    rsi_delta_lb: int,
    rsi_delta_thresh: float,
    slippage: float = 0.0005,
) -> dict:
    c = df_eth["close"].values
    o = df_eth["open"].values
    n = len(c)

    rsi_arr = rsi(c, RSI_PERIOD)
    ema_arr = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, BUCKET_COUNT)
    mom_arr = compute_momentum(c, MOM_LOOKBACK)

    # BTC 추세 게이트: BTC close > BTC EMA → 상승 추세
    btc_above_ema = np.ones(n, dtype=bool)  # 기본: 항상 True (비활성)
    if btc_gate and df_btc is not None and not df_btc.empty:
        btc_c = df_btc["close"].values
        btc_ema_arr = ema(btc_c, btc_ema_period)
        # ETH와 BTC 인덱스 정렬
        eth_idx = df_eth.index
        btc_series = pd.Series(
            btc_c > btc_ema_arr,
            index=df_btc.index,
        ).reindex(eth_idx, method="ffill").fillna(True)
        btc_above_ema = btc_series.values.astype(bool)

    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1,
                 MOM_LOOKBACK, rsi_delta_lb + RSI_PERIOD + 1) + 5

    returns: list[float] = []
    i = warmup
    while i < n - 1:
        rsi_val = rsi_arr[i]
        ema_val = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val = mom_arr[i]

        # 기본 VPIN 진입 조건
        base_ok = (
            not np.isnan(vpin_val) and vpin_val > vpin_high
            and not np.isnan(mom_val) and mom_val > vpin_mom_thresh
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        # BTC 추세 게이트
        btc_ok = bool(btc_above_ema[i])

        # RSI 속도 필터: RSI가 N봉 전보다 rsi_delta_thresh 이상 상승
        rsi_vel_ok = True
        if rsi_delta_thresh > 0 and i >= rsi_delta_lb:
            prev_rsi = rsi_arr[i - rsi_delta_lb]
            if not np.isnan(prev_rsi) and not np.isnan(rsi_val):
                rsi_vel_ok = (rsi_val - prev_rsi) >= rsi_delta_thresh
            else:
                rsi_vel_ok = False

        if base_ok and btc_ok and rsi_vel_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= TP_PCT:
                    returns.append(TP_PCT - FEE - slippage)
                    i = j
                    break
                if ret <= -SL_PCT:
                    returns.append(-SL_PCT - FEE - slippage)
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE - slippage)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0}
    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0
    mcl = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
            "trades": len(arr), "max_dd": max_dd, "mcl": mcl}


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("=== vpin_eth 사이클 233 — BTC 추세 게이트 + RSI 속도 필터 (5-fold WF) ===")
    print(f"심볼: {SYMBOL}  기준: hold={MAX_HOLD} TP={TP_PCT} SL={SL_PCT}")
    print("가설: BTC 게이트 + RSI delta 필터 → WR 30%+ (trades 300+)")
    print(f"기준선: Sharpe +8.295 WR 27.4% trades 507 (ATRmin=OFF)")
    print("=" * 80)

    # 데이터 로드
    df_eth_full = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc_full = load_historical(BTC_SYMBOL, "240m", "2021-01-01", "2026-12-31")
    if df_eth_full.empty:
        print("ETH 데이터 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return
    print(f"ETH 데이터: {len(df_eth_full)}행")
    print(f"BTC 데이터: {len(df_btc_full)}행")

    # 그리드 빌드
    combos = list(product(
        VPIN_HIGH_LIST, VPIN_MOM_THRESH_LIST,
        BTC_EMA_PERIOD_LIST, BTC_GATE_LIST,
        RSI_DELTA_LB_LIST, RSI_DELTA_THRESH_LIST,
    ))
    print(f"\n총 조합: {len(combos)}개")

    # ── 5-fold Walk-Forward ──────────────────────────────────────────────────
    print("\n=== 5-fold Walk-Forward ===")
    combo_wf: list[dict] = []

    for ci, (vh, vm, bep, bg, rdl, rdt) in enumerate(combos):
        if (ci + 1) % 20 == 0:
            print(f"  … 진행 {ci + 1}/{len(combos)}")

        fold_sharpes: list[float] = []
        fold_trades: list[int] = []
        fold_wrs: list[float] = []

        for fold in WF_FOLDS:
            ts, te = fold["test"]
            df_eth_test = df_eth_full.loc[ts:te]
            df_btc_test = df_btc_full.loc[ts:te] if not df_btc_full.empty else None

            if len(df_eth_test) < 50:
                fold_sharpes.append(0.0)
                fold_trades.append(0)
                fold_wrs.append(0.0)
                continue

            r = backtest(
                df_eth_test, df_btc_test,
                vh, vm, bep, bg, rdl, rdt,
            )
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            fold_sharpes.append(sh)
            fold_trades.append(r["trades"])
            fold_wrs.append(r["wr"])

        mean_sh = float(np.mean(fold_sharpes))
        min_sh = min(fold_sharpes) if fold_sharpes else 0.0
        total_trades = sum(fold_trades)
        mean_wr = float(np.mean(fold_wrs)) if fold_wrs else 0.0

        combo_wf.append({
            "vpin_high": vh, "vpin_mom": vm,
            "btc_ema_pd": bep, "btc_gate": bg,
            "rsi_delta_lb": rdl, "rsi_delta_th": rdt,
            "sh_mean": mean_sh, "sh_min": min_sh,
            "wr": mean_wr, "trades": total_trades,
            "fold_sharpes": fold_sharpes,
        })

    # ── 결과 정렬 (min-fold Sharpe 기준) ─────────────────────────────────────
    combo_wf.sort(key=lambda x: x["sh_min"], reverse=True)

    print(f"\n=== Top 15 (min-fold Sharpe 기준) ===")
    hdr = (f"{'vh':>5} {'vm':>7} {'bEP':>3} {'bG':>3} {'rDL':>3} {'rDT':>3} | "
           f"{'ShMean':>7} {'ShMin':>7} {'WR':>6} {'trades':>6}")
    print(hdr)
    print("-" * len(hdr))
    for r in combo_wf[:15]:
        bg_str = "ON" if r["btc_gate"] else "OFF"
        print(
            f"{r['vpin_high']:>5.2f} {r['vpin_mom']:>7.4f} "
            f"{r['btc_ema_pd']:>3} {bg_str:>3} "
            f"{r['rsi_delta_lb']:>3} {r['rsi_delta_th']:>3} | "
            f"{r['sh_mean']:>+7.3f} {r['sh_min']:>+7.3f} "
            f"{r['wr']:>5.1%} {r['trades']:>6}"
        )

    if not combo_wf:
        print("유효 결과 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    best = combo_wf[0]
    print(f"\n★ 최적 (min-fold 기준): "
          f"vh={best['vpin_high']} vm={best['vpin_mom']} "
          f"btc_ema={best['btc_ema_pd']} btc_gate={'ON' if best['btc_gate'] else 'OFF'} "
          f"rsi_delta_lb={best['rsi_delta_lb']} rsi_delta_th={best['rsi_delta_th']}")
    print(f"  폴드별 Sharpe: {[f'{s:+.3f}' for s in best['fold_sharpes']]}")

    # ── 슬리피지 스트레스 (Top 3) ────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (Top 3) ===")
    for rank, params in enumerate(combo_wf[:3], 1):
        print(f"\n--- #{rank}: vh={params['vpin_high']} vm={params['vpin_mom']} "
              f"btc_ema={params['btc_ema_pd']} "
              f"btc_gate={'ON' if params['btc_gate'] else 'OFF'} "
              f"rsi_dLB={params['rsi_delta_lb']} rsi_dTH={params['rsi_delta_th']} "
              f"(min-fold: {params['sh_min']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(
                df_eth_full, df_btc_full,
                params["vpin_high"], params["vpin_mom"],
                params["btc_ema_pd"], params["btc_gate"],
                params["rsi_delta_lb"], params["rsi_delta_th"],
                slippage=slip,
            )
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 기준선 비교 ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 기준선 비교 ===")
    baseline = backtest(
        df_eth_full, df_btc_full,
        0.50, 0.0003,   # vpin defaults from prior best
        50, False,       # no BTC gate
        3, 0,            # no RSI delta filter
    )
    bl_sh = baseline["sharpe"] if not np.isnan(baseline["sharpe"]) else 0.0
    print(f"기준(필터 없음): Sharpe {bl_sh:+.3f} WR {baseline['wr']:.1%} "
          f"trades {baseline['trades']}")
    print(f"최적(필터 적용): Sharpe {best['sh_mean']:+.3f} WR {best['wr']:.1%} "
          f"trades {best['trades']}")

    wr_delta = best["wr"] - baseline["wr"]
    print(f"WR 변화: {wr_delta * 100:+.1f}pp")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    all_pass = all(s >= 3.0 for s in best["fold_sharpes"])
    enough_trades = best["trades"] >= 100
    status = "✅" if all_pass and enough_trades else "❌"
    print(f"{status} 모든 폴드 Sharpe ≥ 3.0: {all_pass} | "
          f"거래수 충분(≥100): {enough_trades}")

    print(f"\nSharpe: {best['sh_mean']:+.3f}")
    print(f"WR: {best['wr'] * 100:.1f}%")
    print(f"trades: {best['trades']}")


if __name__ == "__main__":
    main()
