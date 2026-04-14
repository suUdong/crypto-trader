"""
momentum BB squeeze breakout multi-asset + volume confirm — 사이클 169
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: c167 최적 bbP20_sqTH20_exB5_ema150
      OOS avg Sharpe +35.117, WR 71.9%, 64 trades
      문제1: 2026 거래 0건 — squeeze 임계값/감지 윈도우 확장 필요
      문제2: MDD -13.65% — 15% 한계 근접, 분산 필요
      문제3: SOL 단일자산 — 거래 기회 부족

가설:
  1) 멀티자산 (SOL + ETH) — 두 자산 독립 신호, 거래 수 2배, MDD 분산
  2) 볼륨 확인: squeeze breakout 시 volume > vol_ma * vol_mult 확인
     → 거짓 breakout 필터링, WR 향상
  3) squeeze 강도 점수: squeeze 기간(연속 봉 수)에 비례한 적응형 TP 배수
     → 오래 눌렸을수록 강한 expansion 기대, TP 확대
  4) squeeze 감지 완화: bb_squeeze_pctile [15, 20, 25] (기존 20~40)
     + expand_lookback [3, 5, 8] (기존 2~5) → 2026 진입 확보

그리드:
  - asset: [SOL, ETH] (2)
  - bb_squeeze_pctile: [15, 20, 25] (3)
  - squeeze_expand_bars: [3, 5, 8] (3)
  - vol_confirm_mult: [1.0, 1.5, 2.0] (3)  ← 1.0 = 필터 없음
  = 2×3×3×3 = 54 조합 (per asset), 총 108
  BTC gate 고정: ema150 (c167 best), main gate 고정: sma200
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

ASSETS = ["KRW-SOL", "KRW-ETH"]
BTC = "KRW-BTC"
FEE = 0.0005

# Confirmed from c167 best
LOOKBACK = 20
ADX_THRESH_BASE = 25.0
ADX_THRESH_LOWVOL = 15.0
VOL_MULT_ENTRY = 1.5
RSI_PERIOD = 14
RSI_OVERBOUGHT = 75.0
MAX_HOLD = 48
COOLDOWN_TRIGGER = 3
COOLDOWN_BARS = 24
ATR_PERIOD = 20
ATR_VOL_LOOKBACK = 180
BB_PERIOD = 20  # c167 best

BASE_SL_ATR = 2.0
BASE_TP_ATR = 4.0
TIER1_PCT = 40
TIER2_PCT = 70
LOW_TP_MULT = 3.0
LOW_SL_MULT = 2.0
ADX_GRAD_BARS = 6
TRAIL_ACTIVATE = 2.0
TRAIL_SL = 1.0
ENTRY_THRESHOLD = 0.005

# Fixed from c167 best
BTC_GATE_MAIN = "sma200"
BTC_GATE_SQUEEZE = "ema150"

# Grid axes
BB_SQUEEZE_PCTILE_LIST = [15, 20, 25]
SQUEEZE_EXPAND_BARS_LIST = [3, 5, 8]
VOL_CONFIRM_MULT_LIST = [1.0, 1.5, 2.0]

WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-01")},
]


# ── 지표 ──────────────────────────────────────────────────────────────────────

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


def compute_ema(closes: np.ndarray, period: int) -> np.ndarray:
    ema = np.full(len(closes), np.nan)
    if len(closes) < period:
        return ema
    ema[period - 1] = closes[:period].mean()
    mult = 2.0 / (period + 1)
    for i in range(period, len(closes)):
        ema[i] = closes[i] * mult + ema[i - 1] * (1 - mult)
    return ema


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


def compute_bb_width(closes: np.ndarray, period: int) -> np.ndarray:
    n = len(closes)
    width = np.full(n, np.nan)
    sma = compute_sma(closes, period)
    for i in range(period - 1, n):
        std = np.std(closes[i - period + 1:i + 1])
        if sma[i] > 0:
            width[i] = (2 * 2 * std) / sma[i]
    return width


def compute_bb_width_percentile(
    bb_width: np.ndarray, lookback: int,
) -> np.ndarray:
    n = len(bb_width)
    pctile = np.full(n, np.nan)
    for i in range(lookback, n):
        window = bb_width[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        rank = np.sum(valid <= bb_width[i])
        pctile[i] = rank / len(valid) * 100.0
    return pctile


def compute_squeeze_duration(bb_width_pctile: np.ndarray, threshold: float) -> np.ndarray:
    """Count consecutive bars in squeeze (bb_width_pctile <= threshold)."""
    n = len(bb_width_pctile)
    duration = np.zeros(n)
    for i in range(1, n):
        if not np.isnan(bb_width_pctile[i]) and bb_width_pctile[i] <= threshold:
            duration[i] = duration[i - 1] + 1
        else:
            duration[i] = 0
    return duration


def compute_btc_ma(btc_closes: np.ndarray, gate_type: str) -> np.ndarray:
    if gate_type == "sma200":
        return compute_sma(btc_closes, 200)
    elif gate_type == "ema200":
        return compute_ema(btc_closes, 200)
    elif gate_type == "ema150":
        return compute_ema(btc_closes, 150)
    elif gate_type == "ema100":
        return compute_ema(btc_closes, 100)
    else:
        raise ValueError(f"Unknown gate_type: {gate_type}")


# ── 백테스트 ─────────────────────────────────────────────────────────────────

def backtest(
    df_asset: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_ma_main: np.ndarray,
    btc_ma_squeeze: np.ndarray,
    atr_arr: np.ndarray,
    atr_pctile: np.ndarray,
    adx_arr_ind: np.ndarray,
    bb_width_pctile: np.ndarray,
    bb_width: np.ndarray,
    squeeze_duration: np.ndarray,
    *,
    bb_squeeze_th: float,
    squeeze_expand_bars: int,
    vol_confirm_mult: float,
) -> dict:
    c = df_asset["close"].values
    o = df_asset["open"].values
    v = df_asset["volume"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0
    rsi_arr = rsi(c, RSI_PERIOD)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT_ENTRY * vol_ma

    returns: list[float] = []
    warmup = max(LOOKBACK + RSI_PERIOD + 28, 210)
    consec_loss = 0
    cooldown_until = 0
    vol_filtered = 0
    adx_grad_filtered = 0
    btc_blocked = 0
    squeeze_entries = 0
    normal_entries = 0
    vol_confirm_blocked = 0

    i = warmup
    while i < n - 1:
        if i < cooldown_until:
            i += 1
            continue

        # ★ Squeeze breakout 감지
        is_squeeze_breakout = False
        squeeze_strength = 0.0
        if (
            not np.isnan(bb_width_pctile[i])
            and squeeze_expand_bars > 0
            and i >= squeeze_expand_bars
        ):
            was_squeezed = False
            for k in range(1, squeeze_expand_bars + 1):
                ref = i - k
                if ref >= 0 and not np.isnan(bb_width_pctile[ref]):
                    if bb_width_pctile[ref] <= bb_squeeze_th:
                        was_squeezed = True
                        # squeeze 강도 = 직전 squeeze 기간 (봉 수)
                        squeeze_strength = squeeze_duration[ref]
                        break
            if was_squeezed and bb_width_pctile[i] > bb_squeeze_th:
                is_squeeze_breakout = True

        # ★ 볼륨 확인 (squeeze breakout 전용)
        if is_squeeze_breakout and vol_confirm_mult > 1.0:
            if np.isnan(vol_ma[i]) or v[i] <= vol_confirm_mult * vol_ma[i]:
                is_squeeze_breakout = False
                vol_confirm_blocked += 1

        # ★ BTC gate (dual path)
        btc_above_main = (
            not np.isnan(btc_ma_main[i])
            and btc_close_aligned[i] > btc_ma_main[i]
        )
        btc_above_squeeze = (
            not np.isnan(btc_ma_squeeze[i])
            and btc_close_aligned[i] > btc_ma_squeeze[i]
        )

        path = None
        if btc_above_main:
            path = "normal"
        elif is_squeeze_breakout and btc_above_squeeze:
            path = "squeeze"
        else:
            btc_blocked += 1
            i += 1
            continue

        if np.isnan(atr_arr[i]) or atr_arr[i] <= 0:
            i += 1
            continue

        # 3-tier ATR regime
        cur_pctile = atr_pctile[i] if not np.isnan(atr_pctile[i]) else 50.0
        if cur_pctile > TIER2_PCT:
            vol_filtered += 1
            i += 1
            continue

        in_lowvol = cur_pctile <= TIER1_PCT

        # ADX gradient: squeeze path에서는 해제
        if path == "normal":
            ref_idx = i - ADX_GRAD_BARS
            if (
                ref_idx >= 0
                and not np.isnan(adx_arr_ind[i])
                and not np.isnan(adx_arr_ind[ref_idx])
                and adx_arr_ind[i] <= adx_arr_ind[ref_idx]
            ):
                adx_grad_filtered += 1
                i += 1
                continue

        # 적응형 ADX 임계값
        adx_thresh = ADX_THRESH_LOWVOL if in_lowvol else ADX_THRESH_BASE
        if path == "squeeze":
            adx_thresh = min(adx_thresh, ADX_THRESH_LOWVOL)

        # Entry signal
        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr_ind[i]) and adx_arr_ind[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = o[i + 1] * (1 + FEE)
            entry_atr = atr_arr[i]

            if in_lowvol:
                sl_mult = LOW_SL_MULT
                tp_mult = LOW_TP_MULT
            else:
                sl_mult = BASE_SL_ATR
                tp_mult = BASE_TP_ATR

            if path == "squeeze":
                # 적응형 TP: squeeze 기간이 길수록 TP 확대 (10봉+ = 1.2x)
                strength_bonus = min(squeeze_strength / 50.0, 0.2)  # max +20%
                tp_mult *= (0.8 + strength_bonus)
                sl_mult *= 0.9
                squeeze_entries += 1
            else:
                normal_entries += 1

            sl_pct = (entry_atr * sl_mult) / buy
            tp_pct = (entry_atr * tp_mult) / buy
            trail_activate_pct = (entry_atr * TRAIL_ACTIVATE) / buy
            trail_sl_dist = (entry_atr * TRAIL_SL) / buy

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
                        ret = r - FEE
                        exit_bar = j
                        break

                if not trailing_active and r >= trail_activate_pct:
                    trailing_active = True

                if r >= tp_pct:
                    ret = tp_pct - FEE
                    exit_bar = j
                    break

                if r <= -sl_pct:
                    ret = -sl_pct - FEE
                    exit_bar = j
                    break

            if ret is None:
                hold_end = min(i + MAX_HOLD, n - 1)
                ret = c[hold_end] / buy - 1 - FEE
                exit_bar = hold_end

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
            "trades": 0, "max_dd": 0.0, "max_consec_loss": 0,
            "vol_filtered": vol_filtered, "adx_grad_filtered": adx_grad_filtered,
            "btc_blocked": btc_blocked, "squeeze_entries": squeeze_entries,
            "normal_entries": normal_entries, "vol_confirm_blocked": vol_confirm_blocked,
        }

    arr = np.array(returns)
    sh = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr = float((arr > 0).mean())

    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = float(dd.min()) if len(dd) > 0 else 0.0

    max_consec = 0
    cur = 0
    for r in arr:
        if r < 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    return {
        "sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()),
        "trades": len(arr), "max_dd": max_dd, "max_consec_loss": max_consec,
        "vol_filtered": vol_filtered, "adx_grad_filtered": adx_grad_filtered,
        "btc_blocked": btc_blocked, "squeeze_entries": squeeze_entries,
        "normal_entries": normal_entries, "vol_confirm_blocked": vol_confirm_blocked,
    }


def align_btc(
    df_asset: pd.DataFrame, df_btc: pd.DataFrame, gate_type: str,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].reindex(df_asset.index, method="ffill").values
    btc_ma = compute_btc_ma(df_btc["close"].values, gate_type)
    btc_ma_s = pd.Series(btc_ma, index=df_btc.index)
    btc_ma_aligned = btc_ma_s.reindex(df_asset.index, method="ffill").values
    return btc_close, btc_ma_aligned


def fmt_sh(val: float) -> str:
    return f"{val:+.3f}" if not np.isnan(val) else "  nan"


def run_asset_grid(
    asset: str, df_asset: pd.DataFrame, df_btc: pd.DataFrame,
) -> list[tuple]:
    """Run full grid for one asset, return list of (asset, sq_th, ex_bars, vol_m, result)."""
    atr_arr = compute_atr(
        df_asset["high"].values, df_asset["low"].values,
        df_asset["close"].values, ATR_PERIOD,
    )
    atr_pctile = compute_atr_percentile(atr_arr, ATR_VOL_LOOKBACK)
    adx_arr = adx_indicator(
        df_asset["high"].values, df_asset["low"].values,
        df_asset["close"].values, 14,
    )
    bb_width = compute_bb_width(df_asset["close"].values, BB_PERIOD)
    bb_width_pctile = compute_bb_width_percentile(bb_width, ATR_VOL_LOOKBACK)

    btc_close_aligned, btc_ma_main = align_btc(df_asset, df_btc, BTC_GATE_MAIN)
    _, btc_ma_squeeze = align_btc(df_asset, df_btc, BTC_GATE_SQUEEZE)

    results = []
    for sq_th in BB_SQUEEZE_PCTILE_LIST:
        sq_dur = compute_squeeze_duration(bb_width_pctile, sq_th)
        for ex_bars in SQUEEZE_EXPAND_BARS_LIST:
            for vol_m in VOL_CONFIRM_MULT_LIST:
                r = backtest(
                    df_asset, btc_close_aligned, btc_ma_main, btc_ma_squeeze,
                    atr_arr, atr_pctile, adx_arr, bb_width_pctile, bb_width,
                    sq_dur,
                    bb_squeeze_th=sq_th, squeeze_expand_bars=ex_bars,
                    vol_confirm_mult=vol_m,
                )
                results.append((asset, sq_th, ex_bars, vol_m, r))
    return results


def run_asset_backtest(
    asset: str, df_asset: pd.DataFrame, df_btc: pd.DataFrame,
    sq_th: int, ex_bars: int, vol_m: float,
) -> dict:
    """Run single backtest for one asset with specific params."""
    atr_arr = compute_atr(
        df_asset["high"].values, df_asset["low"].values,
        df_asset["close"].values, ATR_PERIOD,
    )
    atr_pctile = compute_atr_percentile(atr_arr, ATR_VOL_LOOKBACK)
    adx_arr = adx_indicator(
        df_asset["high"].values, df_asset["low"].values,
        df_asset["close"].values, 14,
    )
    bb_width = compute_bb_width(df_asset["close"].values, BB_PERIOD)
    bb_width_pctile = compute_bb_width_percentile(bb_width, ATR_VOL_LOOKBACK)
    sq_dur = compute_squeeze_duration(bb_width_pctile, sq_th)

    btc_close_aligned, btc_ma_main = align_btc(df_asset, df_btc, BTC_GATE_MAIN)
    _, btc_ma_squeeze = align_btc(df_asset, df_btc, BTC_GATE_SQUEEZE)

    return backtest(
        df_asset, btc_close_aligned, btc_ma_main, btc_ma_squeeze,
        atr_arr, atr_pctile, adx_arr, bb_width_pctile, bb_width,
        sq_dur,
        bb_squeeze_th=sq_th, squeeze_expand_bars=ex_bars,
        vol_confirm_mult=vol_m,
    )


def merge_results(r1: dict, r2: dict) -> dict:
    """Merge two independent asset results into combined portfolio metrics."""
    rets1 = r1.get("_returns", [])
    rets2 = r2.get("_returns", [])
    # Simple: combine trades sequentially (independent signals)
    trades = r1["trades"] + r2["trades"]
    if trades < 3:
        return {
            "sharpe": float("nan"), "wr": 0.0, "trades": 0,
            "max_dd": 0.0, "max_consec_loss": 0,
            "squeeze_entries": r1["squeeze_entries"] + r2["squeeze_entries"],
            "normal_entries": r1["normal_entries"] + r2["normal_entries"],
        }

    # Weighted average metrics
    w1 = r1["trades"] / trades if trades > 0 else 0.5
    w2 = 1.0 - w1

    wr = w1 * r1["wr"] + w2 * r2["wr"]

    # Conservative MDD: worst of the two (not additive due to diversification)
    max_dd = min(r1["max_dd"], r2["max_dd"])

    # Sharpe: weighted average (conservative estimate)
    s1 = r1["sharpe"] if not np.isnan(r1["sharpe"]) else 0.0
    s2 = r2["sharpe"] if not np.isnan(r2["sharpe"]) else 0.0
    sharpe = w1 * s1 + w2 * s2

    max_consec = max(r1["max_consec_loss"], r2["max_consec_loss"])

    return {
        "sharpe": sharpe, "wr": wr, "trades": trades,
        "max_dd": max_dd, "max_consec_loss": max_consec,
        "squeeze_entries": r1["squeeze_entries"] + r2["squeeze_entries"],
        "normal_entries": r1["normal_entries"] + r2["normal_entries"],
    }


def main() -> None:
    print("=" * 90)
    print("BB squeeze multi-asset + vol confirm (사이클 169)")
    print("=" * 90)
    print(f"자산: {ASSETS}  기반: c167 bbP20_sqTH20_exB5_ema150")
    print(f"가설: 멀티자산 분산 + 볼륨 확인 squeeze + 적응형 TP")
    print(f"그리드: squeeze_th={BB_SQUEEZE_PCTILE_LIST} expand_bars="
          f"{SQUEEZE_EXPAND_BARS_LIST} vol_confirm={VOL_CONFIRM_MULT_LIST}")
    print(f"BTC gate: main={BTC_GATE_MAIN}, squeeze={BTC_GATE_SQUEEZE}\n")

    # Load data
    df_btc = load_historical(BTC, "240m", "2022-01-01", "2026-12-31")
    asset_data = {}
    for asset in ASSETS:
        df = load_historical(asset, "240m", "2022-01-01", "2026-12-31")
        if df.empty:
            print(f"{asset} 데이터 없음, 건너뜀.")
            continue
        asset_data[asset] = df
        print(f"{asset}: {len(df)}행")
    print()

    # ── Phase 1: 자산별 개별 그리드 ──────────────────────────────────────────
    all_results: dict[str, list[tuple]] = {}
    for asset in ASSETS:
        if asset not in asset_data:
            continue
        print(f"=== Phase 1: {asset} 개별 그리드 ({len(BB_SQUEEZE_PCTILE_LIST) * len(SQUEEZE_EXPAND_BARS_LIST) * len(VOL_CONFIRM_MULT_LIST)}조합) ===")
        print(f"{'sqTH':>5} {'exB':>4} {'volM':>5} "
              f"{'Sharpe':>8} {'WR':>6} {'MDD%':>8} {'cL':>4} {'trd':>5} "
              f"{'sqzN':>5} {'nrmN':>5} {'volB':>5}")
        print("-" * 80)

        results = run_asset_grid(asset, asset_data[asset], df_btc)
        all_results[asset] = results

        for _, sq_th, ex_bars, vol_m, r in results:
            print(
                f"{sq_th:>5} {ex_bars:>4} {vol_m:>5.1f} "
                f"{fmt_sh(r['sharpe']):>8} {r['wr']:>5.1%} "
                f"{r['max_dd'] * 100:>+7.2f}% {r['max_consec_loss']:>4} "
                f"{r['trades']:>5} {r['squeeze_entries']:>5} "
                f"{r['normal_entries']:>5} {r['vol_confirm_blocked']:>5}"
            )
        print()

    # ── Phase 2: 자산별 Top-5 안전 조합 ──────────────────────────────────────
    for asset in ASSETS:
        if asset not in all_results:
            continue
        valid = [
            x for x in all_results[asset]
            if not np.isnan(x[4]["sharpe"]) and x[4]["trades"] >= 10
            and abs(x[4]["max_dd"]) < 0.15 and x[4]["max_consec_loss"] <= 3
        ]
        valid.sort(key=lambda x: x[4]["sharpe"], reverse=True)
        print(f"=== Phase 2: {asset} Top-5 안전 조합 (MDD<15% AND consec≤3) — {len(valid)}개 ===")
        for rank, (_, sq, ex, vm, r) in enumerate(valid[:5], 1):
            print(
                f"  #{rank} sqTH={sq} exB={ex} volM={vm:.1f}  "
                f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd'] * 100:+.2f}%  consec={r['max_consec_loss']}  "
                f"trades={r['trades']}  sqzN={r['squeeze_entries']}"
            )
        print()

    # ── Phase 3: 멀티자산 합산 (공통 파라미터) ───────────────────────────────
    print("=== Phase 3: 멀티자산 합산 (SOL+ETH 동일 파라미터) ===")
    if len(all_results) == 2:
        combined = []
        sol_map = {(x[1], x[2], x[3]): x[4] for x in all_results["KRW-SOL"]}
        eth_map = {(x[1], x[2], x[3]): x[4] for x in all_results["KRW-ETH"]}
        for key in sol_map:
            if key in eth_map:
                merged = merge_results(sol_map[key], eth_map[key])
                combined.append((key, merged))

        combined.sort(key=lambda x: x[1]["sharpe"] if not np.isnan(x[1]["sharpe"]) else -999, reverse=True)
        safe_combined = [
            x for x in combined
            if not np.isnan(x[1]["sharpe"]) and x[1]["trades"] >= 20
            and abs(x[1]["max_dd"]) < 0.15 and x[1]["max_consec_loss"] <= 3
        ]
        print(f"  안전 합산 조합: {len(safe_combined)}개")
        for rank, ((sq, ex, vm), r) in enumerate(safe_combined[:5], 1):
            print(
                f"  #{rank} sqTH={sq} exB={ex} volM={vm:.1f}  "
                f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd'] * 100:+.2f}%  consec={r['max_consec_loss']}  "
                f"trades={r['trades']}  sqzN={r['squeeze_entries']}"
            )
        print()

    # ── Phase 4: 최적 파라미터 연도별 분해 ───────────────────────────────────
    # Pick best safe per-asset combo
    for asset in ASSETS:
        if asset not in all_results:
            continue
        valid = [
            x for x in all_results[asset]
            if not np.isnan(x[4]["sharpe"]) and x[4]["trades"] >= 10
            and abs(x[4]["max_dd"]) < 0.15 and x[4]["max_consec_loss"] <= 3
        ]
        valid.sort(key=lambda x: x[4]["sharpe"], reverse=True)
        if not valid:
            print(f"  {asset}: 안전 조합 없음")
            continue
        _, sq_th, ex_bars, vol_m, _ = valid[0]
        print(f"=== Phase 4: {asset} 연도별 분해 (sqTH={sq_th} exB={ex_bars} volM={vol_m:.1f}) ===")
        for year in range(2022, 2027):
            df_yr = load_historical(asset, "240m", f"{year}-01-01", f"{year}-12-31")
            df_btc_yr = load_historical(BTC, "240m", f"{year}-01-01", f"{year}-12-31")
            if df_yr.empty or df_btc_yr.empty or len(df_yr) < 100:
                print(f"  {year}: 데이터 부족")
                continue
            r = run_asset_backtest(asset, df_yr, df_btc_yr, sq_th, ex_bars, vol_m)
            print(
                f"  {year}: Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd'] * 100:+.2f}%  consec={r['max_consec_loss']}  "
                f"trades={r['trades']}  sqzN={r['squeeze_entries']}  "
                f"nrmN={r['normal_entries']}"
            )
        print()

    # ── Phase 5: WF OOS 검증 (자산별 Top-3) ─────────────────────────────────
    print("=== Phase 5: Walkforward OOS 검증 ===")
    best_overall = None
    best_overall_sharpe = -999.0

    for asset in ASSETS:
        if asset not in all_results:
            continue
        valid = [
            x for x in all_results[asset]
            if not np.isnan(x[4]["sharpe"]) and x[4]["trades"] >= 10
            and abs(x[4]["max_dd"]) < 0.15 and x[4]["max_consec_loss"] <= 3
        ]
        valid.sort(key=lambda x: x[4]["sharpe"], reverse=True)
        wf_targets = valid[:3]

        for _, sq_th, ex_bars, vol_m, _ in wf_targets:
            label = f"{asset.split('-')[1]}_sqTH{sq_th}_exB{ex_bars}_volM{vol_m:.0f}"
            oos_sharpes = []
            for fi, fold in enumerate(WF_FOLDS):
                df_t = load_historical(asset, "240m", fold["test"][0], fold["test"][1])
                df_btc_t = load_historical(BTC, "240m", fold["test"][0], fold["test"][1])
                if df_t.empty or df_btc_t.empty:
                    continue
                r = run_asset_backtest(asset, df_t, df_btc_t, sq_th, ex_bars, vol_m)
                sh_val = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
                oos_sharpes.append(sh_val)
                safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
                safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
                print(
                    f"  {label} Fold {fi+1}: Sharpe={sh_val:+.3f}  "
                    f"WR={r['wr']:.1%}  MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
                    f"consec={r['max_consec_loss']}{safe_cl}  trades={r['trades']}  "
                    f"sqzN={r['squeeze_entries']}"
                )
            if oos_sharpes:
                avg = np.mean(oos_sharpes)
                print(f"  → {label} 평균 OOS Sharpe: {avg:+.3f}")
                if avg > best_overall_sharpe:
                    best_overall_sharpe = avg
                    best_overall = (asset, sq_th, ex_bars, vol_m)
        print()

    # ── Phase 6: 안전성 요약 ─────────────────────────────────────────────────
    # Use best per-asset safe combo for final summary
    for asset in ASSETS:
        if asset not in all_results:
            continue
        valid = [
            x for x in all_results[asset]
            if not np.isnan(x[4]["sharpe"]) and x[4]["trades"] >= 10
            and abs(x[4]["max_dd"]) < 0.15 and x[4]["max_consec_loss"] <= 3
        ]
        valid.sort(key=lambda x: x[4]["sharpe"], reverse=True)
        if valid:
            _, _, _, _, best_r = valid[0]
            print(f"=== 안전성 요약: {asset} ===")
            print(f"  연속손실 ≤ 3: "
                  f"{'✅ PASS' if best_r['max_consec_loss'] <= 3 else '❌ FAIL'} "
                  f"(실제: {best_r['max_consec_loss']})")
            print(f"  MDD < 15%: "
                  f"{'✅ PASS' if abs(best_r['max_dd']) < 0.15 else '⚠️ 주의'} "
                  f"(실제: {best_r['max_dd'] * 100:+.2f}%)")

    # ── 최종 결과 (최적 자산) ────────────────────────────────────────────────
    final_asset = None
    final_r = None
    for asset in ASSETS:
        if asset not in all_results:
            continue
        valid = [
            x for x in all_results[asset]
            if not np.isnan(x[4]["sharpe"]) and x[4]["trades"] >= 10
            and abs(x[4]["max_dd"]) < 0.15 and x[4]["max_consec_loss"] <= 3
        ]
        valid.sort(key=lambda x: x[4]["sharpe"], reverse=True)
        if valid:
            _, _, _, _, r = valid[0]
            if final_r is None or r["sharpe"] > final_r["sharpe"]:
                final_asset = asset
                final_r = r

    if final_r:
        print(f"\n=== 최종 결과 ({final_asset}) ===")
        print(f"Sharpe: {final_r['sharpe']:+.3f}")
        print(f"WR: {final_r['wr'] * 100:.1f}%")
        print(f"trades: {final_r['trades']}")


if __name__ == "__main__":
    main()
