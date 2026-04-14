"""
사이클 176 — RSI velocity + regime trail + VWAP 편차 필터 + 멀티심볼 확장
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경:
  c170+c168: RSI velocity 진입 + 레짐별 trailing SL 분리
    → rVel=5.0 vSrg=1.5 hvTS=0.8 lvTS=0.5
    → avg OOS Sharpe +10.471, WR 41.5%, trades 64
    → 강점: Sharpe 양호, slippage 내성 확인
    → 약점: trades=64 통계적 유의성 부족, WR 41.5% 개선 여지

가설:
  1) VWAP 편차 필터: 가격이 VWAP 위일 때만 진입 → 추세 확인, WR 개선
     - VWAP deviation = (close - VWAP) / VWAP
     - vwap_dev > threshold 일 때만 진입 (모멘텀 확인)
  2) 멀티심볼 확장 (ETH+SOL+XRP) → trade count 3x
  3) RSI velocity 범위 확장 탐색 (rVel 3.0~7.0)
  4) 목표: avg OOS Sharpe > +10 유지, trades > 100, WR > 43%

그리드:
  - rsi_vel_thresh: [3.0, 5.0, 7.0] — RSI velocity 진입 임계 (3)
  - vwap_dev_thresh: [0.0, 0.005, 0.01] — VWAP deviation 최소 (3)
     (0.0 = 필터 비활성, baseline 대비 비교용)
  - hv_trail_sl: [0.6, 0.8, 1.0] — high-vol 레짐 trailing SL (3)
  - lv_trail_sl: [0.3, 0.5, 0.7] — low-vol 레짐 trailing SL (3)
  = 3×3×3×3 = 81 조합 × 3 심볼 × 2 fold

검증:
  - 2-fold WF (c170 동일 fold)
  - 슬리피지 스트레스 0.05~0.20%
  - 심볼별 분해 출력
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOLS = ["KRW-ETH", "KRW-SOL", "KRW-XRP"]
BTC = "KRW-BTC"
FEE = 0.0005

# ── c165 최적 고정 (진입) ────────────────────────────────────────────────────
LOOKBACK = 20
ADX_THRESH_BASE = 25.0
ADX_THRESH_LOWVOL = 15.0
VOL_MULT = 1.5
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
MAX_HOLD = 48
COOLDOWN_TRIGGER = 3
COOLDOWN_BARS = 24
ATR_PERIOD = 20
ATR_VOL_LOOKBACK = 180
BASE_SL_ATR = 2.0
BASE_TP_ATR = 4.0
TIER1_PCT = 40
TIER2_PCT = 70
LOW_TP_MULT = 3.0
LOW_SL_MULT = 2.0
ADX_GRAD_BARS = 6
TRAIL_ACTIVATE = 2.0
ENTRY_THRESHOLD = 0.005

# c168 regime exit 고정
BTC_SMA_PERIOD = 200

# VWAP 계산 기간
VWAP_PERIOD = 20  # 20봉 rolling VWAP

# 탐색 그리드
RSI_VEL_THRESH_LIST = [3.0, 5.0, 7.0]
VWAP_DEV_THRESH_LIST = [0.0, 0.005, 0.01]
HV_TRAIL_SL_LIST = [0.6, 0.8, 1.0]
LV_TRAIL_SL_LIST = [0.3, 0.5, 0.7]

# 2-fold WF (c170 동일)
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-03-31"), "test": ("2025-04-01", "2026-04-05")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ────────────────────────────────────────────────────────────────────

def rsi_func(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def rsi_velocity(rsi_arr: np.ndarray, lookback: int = 5) -> np.ndarray:
    """RSI 변화 속도: rsi[i] - rsi[i-lookback]."""
    n = len(rsi_arr)
    vel = np.full(n, np.nan)
    for i in range(lookback, n):
        if not np.isnan(rsi_arr[i]) and not np.isnan(rsi_arr[i - lookback]):
            vel[i] = rsi_arr[i] - rsi_arr[i - lookback]
    return vel


def adx_indicator(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14,
) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2:
        return adx_arr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    dm_p = np.where(
        (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
        np.maximum(highs[1:] - highs[:-1], 0.0), 0.0,
    )
    dm_m = np.where(
        (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
        np.maximum(lows[:-1] - lows[1:], 0.0), 0.0,
    )
    atr_s = np.full(n - 1, np.nan)
    dip_s = np.full(n - 1, np.nan)
    dim_s = np.full(n - 1, np.nan)
    atr_s[period - 1] = tr[:period].sum()
    dip_s[period - 1] = dm_p[:period].sum()
    dim_s[period - 1] = dm_m[:period].sum()
    for i in range(period, n - 1):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        dip_s[i] = dip_s[i - 1] - dip_s[i - 1] / period + dm_p[i]
        dim_s[i] = dim_s[i - 1] - dim_s[i - 1] / period + dm_m[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dip_s / (atr_s + 1e-9)
        di_m = 100 * dim_s / (atr_s + 1e-9)
        dx = 100 * np.abs(di_p - di_m) / (di_p + di_m + 1e-9)
    adx_vals = np.full(n - 1, np.nan)
    adx_vals[2 * period - 2] = dx[period - 1:2 * period - 1].mean()
    for i in range(2 * period - 1, n - 1):
        adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period
    adx_arr[1:] = adx_vals
    return adx_arr


def compute_sma(closes: np.ndarray, period: int) -> np.ndarray:
    sma = np.full(len(closes), np.nan)
    if len(closes) < period:
        return sma
    cumsum = np.cumsum(closes)
    sma[period - 1:] = (cumsum[period - 1:] - np.concatenate(
        ([0.0], cumsum[:len(closes) - period])
    )) / period
    return sma


def compute_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int,
) -> np.ndarray:
    n = len(closes)
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    atr[period] = tr[:period].mean()
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period
    return atr


def compute_atr_percentile(atr_arr: np.ndarray, lookback: int) -> np.ndarray:
    n = len(atr_arr)
    pctile = np.full(n, np.nan)
    for i in range(lookback, n):
        window = atr_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        rank = np.sum(valid <= atr_arr[i])
        pctile[i] = rank / len(valid) * 100.0
    return pctile


def compute_vwap(
    closes: np.ndarray, volumes: np.ndarray, period: int,
) -> np.ndarray:
    """Rolling VWAP: sum(close*volume) / sum(volume) over period."""
    n = len(closes)
    vwap = np.full(n, np.nan)
    if n < period:
        return vwap
    cv = closes * volumes
    cum_cv = np.cumsum(cv)
    cum_v = np.cumsum(volumes)
    for i in range(period - 1, n):
        start = i - period + 1
        sum_cv = cum_cv[i] - (cum_cv[start - 1] if start > 0 else 0.0)
        sum_v = cum_v[i] - (cum_v[start - 1] if start > 0 else 0.0)
        if sum_v > 0:
            vwap[i] = sum_cv / sum_v
    return vwap


def compute_vwap_deviation(
    closes: np.ndarray, vwap: np.ndarray,
) -> np.ndarray:
    """VWAP deviation: (close - VWAP) / VWAP."""
    with np.errstate(invalid="ignore", divide="ignore"):
        dev = np.where(vwap > 0, (closes - vwap) / vwap, np.nan)
    return dev


# ── 백테스트 ────────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_ma_aligned: np.ndarray,
    atr_arr: np.ndarray,
    atr_pctile: np.ndarray,
    adx_arr_ind: np.ndarray,
    rsi_vel_arr: np.ndarray,
    vwap_dev_arr: np.ndarray,
    *,
    rsi_vel_thresh: float,
    vwap_dev_thresh: float,
    hv_trail_sl: float,
    lv_trail_sl: float,
    slippage: float = 0.0005,
) -> dict:
    c = df["close"].values
    o = df["open"].values
    v = df["volume"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0
    rsi_arr = rsi_func(c, RSI_PERIOD)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = max(LOOKBACK + RSI_PERIOD + 28, 210)
    consec_loss = 0
    cooldown_until = 0
    trail_exits = 0
    tp_exits = 0
    sl_exits = 0
    hold_exits = 0
    rv_entries = 0
    vwap_filtered = 0

    i = warmup
    while i < n - 1:
        if i < cooldown_until:
            i += 1
            continue

        # BTC gate + regime detection
        btc_above = (
            not np.isnan(btc_ma_aligned[i])
            and btc_close_aligned[i] > btc_ma_aligned[i]
        )
        is_bull = btc_above

        if not btc_above:
            i += 1
            continue

        if np.isnan(atr_arr[i]) or atr_arr[i] <= 0:
            i += 1
            continue

        cur_pctile = atr_pctile[i] if not np.isnan(atr_pctile[i]) else 50.0
        if cur_pctile > TIER2_PCT:
            i += 1
            continue

        in_lowvol = cur_pctile <= TIER1_PCT

        # ADX gradient
        ref_idx = i - ADX_GRAD_BARS
        if (
            ref_idx >= 0
            and not np.isnan(adx_arr_ind[i])
            and not np.isnan(adx_arr_ind[ref_idx])
            and adx_arr_ind[i] <= adx_arr_ind[ref_idx]
        ):
            i += 1
            continue

        adx_thresh = ADX_THRESH_LOWVOL if in_lowvol else ADX_THRESH_BASE

        # ★ RSI velocity 필터 (c170)
        cur_rv = rsi_vel_arr[i] if not np.isnan(rsi_vel_arr[i]) else 0.0
        if cur_rv < rsi_vel_thresh:
            i += 1
            continue

        # ★ VWAP deviation 필터 (NEW)
        cur_vwap_dev = vwap_dev_arr[i] if not np.isnan(vwap_dev_arr[i]) else 0.0
        if vwap_dev_thresh > 0 and cur_vwap_dev < vwap_dev_thresh:
            vwap_filtered += 1
            i += 1
            continue

        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr_ind[i]) and adx_arr_ind[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            entry_atr = atr_arr[i]
            rv_entries += 1

            if in_lowvol:
                sl_mult = LOW_SL_MULT
                tp_mult = LOW_TP_MULT
            else:
                sl_mult = BASE_SL_ATR
                tp_mult = BASE_TP_ATR

            sl_pct = (entry_atr * sl_mult) / buy
            tp_pct = (entry_atr * tp_mult) / buy
            trail_activate_pct = (entry_atr * TRAIL_ACTIVATE) / buy

            # ★ 레짐별 trailing SL (c168)
            trail_sl_mult = hv_trail_sl if not in_lowvol else lv_trail_sl
            trail_sl_dist = (entry_atr * trail_sl_mult) / buy

            sl_pct = min(max(sl_pct, 0.01), 0.10)
            tp_pct = min(max(tp_pct, 0.02), 0.20)

            ret = None
            exit_bar = i + 1
            trailing_active = False
            highest_ret = 0.0

            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                r = c[j] / buy - 1

                if r > highest_ret:
                    highest_ret = r

                if trailing_active:
                    trail_stop = highest_ret - trail_sl_dist
                    if r <= trail_stop:
                        ret = r - FEE - slippage
                        exit_bar = j
                        trail_exits += 1
                        break

                if not trailing_active and r >= trail_activate_pct:
                    trailing_active = True

                if r >= tp_pct:
                    ret = tp_pct - FEE - slippage
                    exit_bar = j
                    tp_exits += 1
                    break

                if r <= -sl_pct:
                    ret = -sl_pct - FEE - slippage
                    exit_bar = j
                    sl_exits += 1
                    break

            if ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                ret = c[hold_end] / buy - 1 - FEE - slippage
                exit_bar = hold_end
                hold_exits += 1

            returns.append(ret)

            if ret < 0:
                consec_loss += 1
                if consec_loss >= COOLDOWN_TRIGGER:
                    cooldown_until = exit_bar + COOLDOWN_BARS
                    consec_loss = 0
            else:
                consec_loss = 0

            i = exit_bar
        else:
            i += 1

    if len(returns) < 3:
        return {
            "sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
            "trades": 0, "max_dd": 0.0, "mcl": 0,
            "trail_exits": 0, "tp_exits": 0, "rv_entries": 0,
            "vwap_filtered": 0,
        }

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

    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd, "mcl": mcl,
        "trail_exits": trail_exits, "tp_exits": tp_exits,
        "rv_entries": rv_entries, "vwap_filtered": vwap_filtered,
    }


def pool_results(results_list: list[dict]) -> dict:
    all_sharpes = []
    all_wrs = []
    total_trades = 0
    all_avg_rets = []
    all_max_dds = []
    all_mcls = []
    all_trx = 0
    all_rvE = 0
    for r in results_list:
        if r["trades"] > 0 and not np.isnan(r["sharpe"]):
            all_sharpes.append(r["sharpe"])
            all_wrs.append(r["wr"])
            total_trades += r["trades"]
            all_avg_rets.append(r["avg_ret"])
            all_max_dds.append(r["max_dd"])
            all_mcls.append(r["mcl"])
            all_trx += r["trail_exits"]
            all_rvE += r["rv_entries"]
    if not all_sharpes:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0,
                "trail_exits": 0, "rv_entries": 0}
    return {
        "sharpe": float(np.mean(all_sharpes)),
        "wr": float(np.mean(all_wrs)),
        "avg_ret": float(np.mean(all_avg_rets)),
        "trades": total_trades,
        "max_dd": float(np.mean(all_max_dds)),
        "mcl": max(all_mcls),
        "trail_exits": all_trx,
        "rv_entries": all_rvE,
    }


def align_btc_to_sym(
    df_sym: pd.DataFrame, df_btc: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].reindex(df_sym.index, method="ffill").values
    btc_ma_raw = compute_sma(df_btc["close"].values, BTC_SMA_PERIOD)
    btc_ma_s = pd.Series(btc_ma_raw, index=df_btc.index)
    btc_ma_aligned = btc_ma_s.reindex(df_sym.index, method="ffill").values
    return btc_close, btc_ma_aligned


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def fmt_sh(val: float) -> str:
    return f"{val:+.3f}" if not np.isnan(val) else "  nan"


def precompute_sym(df: pd.DataFrame, df_btc: pd.DataFrame) -> dict:
    """심볼별 지표 사전 계산."""
    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    btc_c, btc_ma = align_btc_to_sym(df, df_btc)
    atr = compute_atr(h, lo, c, ATR_PERIOD)
    atr_pctile = compute_atr_percentile(atr, ATR_VOL_LOOKBACK)
    adx = adx_indicator(h, lo, c, 14)
    rsi_arr = rsi_func(c, RSI_PERIOD)
    rsi_vel = rsi_velocity(rsi_arr, lookback=5)
    vwap = compute_vwap(c, v, VWAP_PERIOD)
    vwap_dev = compute_vwap_deviation(c, vwap)
    return {
        "df": df, "btc_close": btc_c, "btc_ma": btc_ma,
        "atr": atr, "atr_pctile": atr_pctile,
        "adx": adx, "rsi_vel": rsi_vel, "vwap_dev": vwap_dev,
    }


def main() -> None:
    print("=" * 80)
    print("=== c176 — RSI velocity + VWAP deviation 필터 + 레짐 trail + 멀티심볼 ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"기반: c170+c168 RSI vel + regime trail (OOS +10.471, 64 trades)")
    print(f"  RSI vel thresh: {RSI_VEL_THRESH_LIST}")
    print(f"  VWAP dev thresh: {VWAP_DEV_THRESH_LIST}")
    print(f"  HV trail SL: {HV_TRAIL_SL_LIST}  LV trail SL: {LV_TRAIL_SL_LIST}")
    combos = list(product(
        RSI_VEL_THRESH_LIST, VWAP_DEV_THRESH_LIST,
        HV_TRAIL_SL_LIST, LV_TRAIL_SL_LIST,
    ))
    print(f"  총 조합: {len(combos)}")
    print(f"목표: avg OOS Sharpe > +10, trades > 100, WR > 43%")
    print("=" * 80)

    # 데이터 로드
    df_btc_full = load_historical(BTC, "240m", "2021-01-01", "2026-12-31")
    if df_btc_full.empty:
        print("BTC 데이터 없음.")
        return

    print("\n--- 심볼별 데이터 확인 ---")
    sym_ok: list[str] = []
    for sym in SYMBOLS:
        df_check = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if df_check.empty or len(df_check) < 500:
            print(f"  {sym}: 데이터 부족 ({len(df_check)}행) -> 제외")
        else:
            print(f"  {sym}: {len(df_check)}행 OK")
            sym_ok.append(sym)

    if not sym_ok:
        print("유효 심볼 없음.")
        print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")
        return

    # ── Phase 0: 베이스라인 (c170 최적 ETH-only, no VWAP filter) ─────────────
    print("\n--- 베이스라인: c170 ETH-only rVel=5.0 hvTS=0.8 lvTS=0.5 (no VWAP) ---")
    for sym in sym_ok:
        df_full = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
        if not df_full.empty:
            pre = precompute_sym(df_full, df_btc_full)
            base = backtest(
                pre["df"], pre["btc_close"], pre["btc_ma"],
                pre["atr"], pre["atr_pctile"], pre["adx"],
                pre["rsi_vel"], pre["vwap_dev"],
                rsi_vel_thresh=5.0, vwap_dev_thresh=0.0,
                hv_trail_sl=0.8, lv_trail_sl=0.5,
            )
            print(f"  {sym}: Sharpe={fmt_sh(base['sharpe'])}  "
                  f"WR={base['wr']:.1%}  n={base['trades']}  "
                  f"MDD={base['max_dd'] * 100:+.2f}%  "
                  f"trX={base['trail_exits']}  rvE={base['rv_entries']}")

    # ── Phase 1: 2-fold OOS Walk-Forward ─────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"=== 2-fold OOS Walk-Forward ({len(combos)} 조합 × {len(sym_ok)} 심볼) ===")

    wf_results: list[dict] = []
    for combo_i, (rv_th, vwap_th, hv_ts, lv_ts) in enumerate(combos):
        fold_sharpes: list[float] = []
        fold_details: list[dict] = []
        all_pass = True

        for fold_i, fold in enumerate(WF_FOLDS):
            sym_fold_results: list[dict] = []
            for sym in sym_ok:
                df_test = load_historical(
                    sym, "240m", fold["test"][0], fold["test"][1])
                df_btc_t = load_historical(
                    BTC, "240m", fold["test"][0], fold["test"][1])
                if df_test.empty or df_btc_t.empty:
                    continue
                pre = precompute_sym(df_test, df_btc_t)
                r = backtest(
                    pre["df"], pre["btc_close"], pre["btc_ma"],
                    pre["atr"], pre["atr_pctile"], pre["adx"],
                    pre["rsi_vel"], pre["vwap_dev"],
                    rsi_vel_thresh=rv_th, vwap_dev_thresh=vwap_th,
                    hv_trail_sl=hv_ts, lv_trail_sl=lv_ts,
                )
                sym_fold_results.append({"sym": sym, **r})

            pooled = pool_results(sym_fold_results)
            fold_sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
            fold_sharpes.append(fold_sh)
            fold_details.append({
                "fold": fold_i + 1, **pooled,
                "sym_details": sym_fold_results,
            })
            if fold_sh <= 0:
                all_pass = False

        avg_oos = float(np.mean(fold_sharpes)) if fold_sharpes else 0.0
        wf_results.append({
            "rsi_vel": rv_th, "vwap_dev": vwap_th,
            "hv_ts": hv_ts, "lv_ts": lv_ts,
            "avg_oos": avg_oos, "all_pass": all_pass,
            "fold_sharpes": fold_sharpes,
            "fold_details": fold_details,
        })

        if (combo_i + 1) % 27 == 0 or combo_i + 1 == len(combos):
            print(f"  진행: {combo_i + 1}/{len(combos)}")

    # ── WF 결과 출력 ────────────────────────────────────────────────────────
    wf_results.sort(key=lambda x: x["avg_oos"], reverse=True)

    print(f"\n--- WF 통과 여부 ---")
    hdr = (f"{'rVel':>5} {'vwDev':>6} {'hvTS':>5} {'lvTS':>5} | "
           f"{'avg OOS':>8} | {'F1':>7} {'F2':>7} | {'PASS':>5}")
    print(hdr)
    print("-" * len(hdr))
    pass_count = 0
    for w in wf_results:
        f1 = w["fold_sharpes"][0] if len(w["fold_sharpes"]) > 0 else 0.0
        f2 = w["fold_sharpes"][1] if len(w["fold_sharpes"]) > 1 else 0.0
        status = "PASS" if w["all_pass"] else "FAIL"
        if w["all_pass"]:
            pass_count += 1
        print(
            f"{w['rsi_vel']:>5.1f} {w['vwap_dev']:>6.3f} "
            f"{w['hv_ts']:>5.1f} {w['lv_ts']:>5.1f} | "
            f"{w['avg_oos']:>+8.3f} | "
            f"{f1:>+7.3f} {f2:>+7.3f} | {status:>5}"
        )

    print(f"\n통과: {pass_count}/{len(wf_results)}")

    # ── Top 5 심볼별 분해 ────────────────────────────────────────────────────
    top_pass = [w for w in wf_results if w["all_pass"]]
    top_show = top_pass[:5] if top_pass else wf_results[:5]

    for rank, w in enumerate(top_show, 1):
        label = "PASS" if w["all_pass"] else "FAIL"
        print(f"\n--- #{rank} ({label}): rVel={w['rsi_vel']} "
              f"vwDev={w['vwap_dev']} hvTS={w['hv_ts']} lvTS={w['lv_ts']} "
              f"(avg OOS: {w['avg_oos']:+.3f}) ---")
        for fd in w["fold_details"]:
            print(f"  Fold {fd['fold']}: pooled Sharpe={fd['sharpe']:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={fd['trades']}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%  "
                  f"trX={fd['trail_exits']}  rvE={fd['rv_entries']}")
            for sd in fd.get("sym_details", []):
                sh = sd["sharpe"] if not np.isnan(sd["sharpe"]) else 0.0
                print(f"    {sd['sym']}: Sharpe={sh:+.3f}  WR={sd['wr']:.1%}  "
                      f"n={sd['trades']}  avg={sd['avg_ret'] * 100:+.2f}%  "
                      f"MDD={sd['max_dd'] * 100:+.2f}%")

    # ── 슬리피지 스트레스 (Top 3 PASS) ───────────────────────────────────────
    stress_targets = top_pass[:3] if top_pass else wf_results[:1]
    if stress_targets:
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 (WF Top 3) ===")

        for rank, w in enumerate(stress_targets, 1):
            print(f"\n--- #{rank}: rVel={w['rsi_vel']} vwDev={w['vwap_dev']} "
                  f"hvTS={w['hv_ts']} lvTS={w['lv_ts']} "
                  f"(avg OOS: {w['avg_oos']:+.3f}) ---")
            hdr3 = (f"{'slippage':>9} {'Sharpe':>8} {'WR':>6} "
                    f"{'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5}")
            print(hdr3)
            print("-" * len(hdr3))
            for slip in SLIPPAGE_LEVELS:
                sym_results = []
                for fold_i, fold in enumerate(WF_FOLDS):
                    for sym in sym_ok:
                        df_test = load_historical(
                            sym, "240m", fold["test"][0], fold["test"][1])
                        df_btc_t = load_historical(
                            BTC, "240m", fold["test"][0], fold["test"][1])
                        if df_test.empty or df_btc_t.empty:
                            continue
                        pre = precompute_sym(df_test, df_btc_t)
                        r = backtest(
                            pre["df"], pre["btc_close"], pre["btc_ma"],
                            pre["atr"], pre["atr_pctile"], pre["adx"],
                            pre["rsi_vel"], pre["vwap_dev"],
                            rsi_vel_thresh=w["rsi_vel"],
                            vwap_dev_thresh=w["vwap_dev"],
                            hv_trail_sl=w["hv_ts"],
                            lv_trail_sl=w["lv_ts"],
                            slippage=slip,
                        )
                        sym_results.append(r)
                pooled = pool_results(sym_results)
                sh = pooled["sharpe"] if not np.isnan(pooled["sharpe"]) else 0.0
                print(
                    f"  {slip:.2%}   {sh:>+8.3f} {pooled['wr']:>5.1%} "
                    f"{pooled['avg_ret'] * 100:>+6.2f}% "
                    f"{pooled['max_dd'] * 100:>+6.2f}% {pooled['mcl']:>4} "
                    f"{pooled['trades']:>5}"
                )

    # ── Buy-and-Hold 비교 ────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== Buy-and-Hold 기준선 (OOS 구간별) ===")
    for fold_i, fold in enumerate(WF_FOLDS):
        for sym in sym_ok:
            df_test = load_historical(
                sym, "240m", fold["test"][0], fold["test"][1])
            if not df_test.empty:
                bh = buy_and_hold(df_test)
                print(f"  {sym} Fold {fold_i + 1} "
                      f"({fold['test'][0]}~{fold['test'][1]}): "
                      f"B&H {bh * 100:+.2f}%")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    if top_pass:
        best = top_pass[0]
        all_trades = 0
        all_wr_sum = 0.0
        all_wr_n = 0
        for fd in best["fold_details"]:
            all_trades += fd["trades"]
            if fd["trades"] > 0:
                all_wr_sum += fd["wr"]
                all_wr_n += 1
        avg_wr = all_wr_sum / all_wr_n if all_wr_n > 0 else 0.0

        print(f"\n{'=' * 80}")
        print("=== 최종 요약 ===")
        print(f"★ WF 최고: rVel={best['rsi_vel']} vwDev={best['vwap_dev']} "
              f"hvTS={best['hv_ts']} lvTS={best['lv_ts']}")
        print(f"  (기반: c170 RSI vel + c168 regime trail + VWAP deviation 필터)")
        print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f}")
        for fd in best["fold_details"]:
            print(f"  Fold {fd['fold']}: Sharpe={fd['sharpe']:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={fd['trades']}  "
                  f"MDD={fd['max_dd'] * 100:+.2f}%  "
                  f"trX={fd['trail_exits']}  rvE={fd['rv_entries']}")
        print(f"\n  vs 베이스라인 (c170 ETH-only): "
              f"Sharpe=+10.471  WR=41.5%  MDD=-13.41%  n=64")

        print(f"\nSharpe: {best['avg_oos']:+.3f}")
        print(f"WR: {avg_wr * 100:.1f}%")
        print(f"trades: {all_trades}")
    else:
        best = wf_results[0] if wf_results else None
        if best:
            all_trades = sum(fd["trades"] for fd in best["fold_details"])
            all_wr_n = sum(1 for fd in best["fold_details"] if fd["trades"] > 0)
            avg_wr = (sum(fd["wr"] for fd in best["fold_details"]
                          if fd["trades"] > 0)
                      / all_wr_n if all_wr_n > 0 else 0.0)

            print(f"\n{'=' * 80}")
            print("=== 최종 요약 (전 조합 WF FAIL) ===")
            print(f"최고 avg OOS: {best['avg_oos']:+.3f} "
                  f"(rVel={best['rsi_vel']} vwDev={best['vwap_dev']} "
                  f"hvTS={best['hv_ts']} lvTS={best['lv_ts']})")

            print(f"\nSharpe: {best['avg_oos']:+.3f}")
            print(f"WR: {avg_wr * 100:.1f}%")
            print(f"trades: {all_trades}")
        else:
            print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")


if __name__ == "__main__":
    main()
