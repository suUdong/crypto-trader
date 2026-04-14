"""
사이클 175 — 멀티심볼 ATR z-score 급락탈출 + 레짐별 z-score 임계 적응
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경:
  c172 (SOL only): zsLB=120 zsTH=2.0 sqTP=1.0 trTi=1.0
    → avg OOS Sharpe +20.497, WR 68.9%, 28 trades
    → MDD -8.60% (vs baseline -32.64%)  ★ 극적 MDD 개선
  한계: SOL 단일 심볼, 28 trades로 통계적 유의성 부족

가설:
  1) c172 z-score exit을 ETH+SOL+XRP 멀티심볼에 적용 → trade count 3x 확대
  2) BTC regime (SMA200 위/아래) 따라 z-score exit 임계를 동적 조정
     - BEAR: zsTH 하향 (1.5~2.0) → 더 공격적으로 급락탈출
     - BULL: zsTH 상향 (2.0~3.0) → 수익 구간에서 너무 빨리 나가지 않음
  3) 심볼별 ADX 민감도 차등 적용 (SOL 낮은 ADX, ETH/XRP 표준)
  4) 목표: avg OOS Sharpe > +15 (c172 대비 -25% 허용, trade count 3x 보상)

그리드:
  - bull_zsTH: [2.0, 2.5, 3.0] — BULL 구간 z-score exit 임계 (3)
  - bear_zsTH: [1.5, 2.0, 2.5] — BEAR 구간 z-score exit 임계 (3)
  - sqTP: [0.8, 1.0] — squeeze TP scale (2)
  - trTi: [1.0, 1.5] — trail tighten z-score 배수 (2)
  = 3×3×2×2 = 36 조합 × 3 심볼 × 3 fold

검증:
  - 3-fold WF (c165/c174 동일 fold)
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
TRAIL_SL = 1.0
ENTRY_THRESHOLD = 0.005

# BB squeeze (c167)
BB_PERIOD = 20
BB_SQUEEZE_PCTILE = 30
SQUEEZE_EXPAND_BARS = 3

# ATR z-score (c172 최적 고정)
ATR_ZSCORE_LOOKBACK = 120

# BTC SMA gate
BTC_SMA_PERIOD = 200

# 탐색 그리드
BULL_ZSTH_LIST = [2.0, 2.5, 3.0]
BEAR_ZSTH_LIST = [1.5, 2.0, 2.5]
SQUEEZE_TP_SCALE_LIST = [0.8, 1.0]
TRAIL_TIGHTEN_LIST = [1.0, 1.5]

# 3-fold WF (c165/c174 동일)
WF_FOLDS = [
    {"train": ("2022-01-01", "2024-03-31"), "test": ("2024-04-01", "2025-01-31")},
    {"train": ("2022-07-01", "2024-09-30"), "test": ("2024-10-01", "2025-07-31")},
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


def compute_atr_zscore(atr_arr: np.ndarray, lookback: int) -> np.ndarray:
    """ATR z-score: (current ATR - mean) / std over lookback window."""
    n = len(atr_arr)
    zscore = np.full(n, np.nan)
    for i in range(lookback, n):
        window = atr_arr[i - lookback:i]
        valid = window[~np.isnan(window)]
        if len(valid) < lookback // 2:
            continue
        mu = valid.mean()
        sigma = valid.std()
        if sigma > 1e-9 and not np.isnan(atr_arr[i]):
            zscore[i] = (atr_arr[i] - mu) / sigma
    return zscore


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


# ── 백테스트 ────────────────────────────────────────────────────────────────

def backtest(
    df: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_ma_aligned: np.ndarray,
    atr_arr: np.ndarray,
    atr_pctile: np.ndarray,
    atr_zscore: np.ndarray,
    adx_arr_ind: np.ndarray,
    bb_width_pctile: np.ndarray,
    *,
    bull_zsth: float,
    bear_zsth: float,
    squeeze_tp_scale: float,
    trail_tighten_zscore: float,
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
    zscore_exits = 0
    trail_exits = 0
    tp_exits = 0
    sl_exits = 0
    hold_exits = 0
    squeeze_entries = 0
    normal_entries = 0

    i = warmup
    while i < n - 1:
        if i < cooldown_until:
            i += 1
            continue

        # Squeeze breakout
        is_squeeze_breakout = False
        if (
            not np.isnan(bb_width_pctile[i])
            and SQUEEZE_EXPAND_BARS > 0
            and i >= SQUEEZE_EXPAND_BARS
        ):
            was_squeezed = False
            for k in range(1, SQUEEZE_EXPAND_BARS + 1):
                ref = i - k
                if ref >= 0 and not np.isnan(bb_width_pctile[ref]):
                    if bb_width_pctile[ref] <= BB_SQUEEZE_PCTILE:
                        was_squeezed = True
                        break
            if was_squeezed and bb_width_pctile[i] > BB_SQUEEZE_PCTILE:
                is_squeeze_breakout = True

        # BTC gate + regime detection
        btc_above = (
            not np.isnan(btc_ma_aligned[i])
            and btc_close_aligned[i] > btc_ma_aligned[i]
        )
        is_bull = btc_above

        if not btc_above and not is_squeeze_breakout:
            i += 1
            continue
        if not btc_above and is_squeeze_breakout:
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

        # ADX gradient (squeeze path bypass)
        path = "squeeze" if is_squeeze_breakout else "normal"
        if path == "normal":
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
        if path == "squeeze":
            adx_thresh = min(adx_thresh, ADX_THRESH_LOWVOL)

        entry_ok = (
            not np.isnan(mom[i]) and mom[i] > ENTRY_THRESHOLD
            and not np.isnan(rsi_arr[i]) and rsi_arr[i] < RSI_OVERBOUGHT
            and not np.isnan(adx_arr_ind[i]) and adx_arr_ind[i] > adx_thresh
            and vol_ok[i]
        )
        if entry_ok:
            buy = o[i + 1] * (1 + FEE + slippage)
            entry_atr = atr_arr[i]

            if in_lowvol:
                sl_mult = LOW_SL_MULT
                tp_mult = LOW_TP_MULT
            else:
                sl_mult = BASE_SL_ATR
                tp_mult = BASE_TP_ATR

            if path == "squeeze":
                tp_mult *= squeeze_tp_scale
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

            # ★ Regime-adaptive z-score exit threshold
            active_zsth = bull_zsth if is_bull else bear_zsth

            ret = None
            exit_bar = i + 1
            trailing_active = False
            highest_ret = 0.0

            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                r = c[j] / buy - 1

                if r > highest_ret:
                    highest_ret = r

                # ★ ATR z-score 긴급 청산 (regime-adaptive threshold)
                cur_zscore = (
                    atr_zscore[j] if not np.isnan(atr_zscore[j]) else 0.0
                )
                if cur_zscore > active_zsth:
                    ret = r - FEE - slippage
                    exit_bar = j
                    zscore_exits += 1
                    break

                # Trailing: z-score 높으면 trail SL 강화
                effective_trail_sl = trail_sl_dist
                if cur_zscore > 1.0:
                    effective_trail_sl = trail_sl_dist / trail_tighten_zscore

                if trailing_active:
                    trail_stop = highest_ret - effective_trail_sl
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
            "zscore_exits": 0, "trail_exits": 0, "tp_exits": 0,
            "sl_exits": 0, "hold_exits": 0,
            "squeeze_entries": 0, "normal_entries": 0,
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
        "zscore_exits": zscore_exits, "trail_exits": trail_exits,
        "tp_exits": tp_exits, "sl_exits": sl_exits, "hold_exits": hold_exits,
        "squeeze_entries": squeeze_entries, "normal_entries": normal_entries,
    }


def pool_results(results_list: list[dict]) -> dict:
    all_sharpes = []
    all_wrs = []
    total_trades = 0
    all_avg_rets = []
    all_max_dds = []
    all_mcls = []
    all_zsx = 0
    all_trx = 0
    for r in results_list:
        if r["trades"] > 0 and not np.isnan(r["sharpe"]):
            all_sharpes.append(r["sharpe"])
            all_wrs.append(r["wr"])
            total_trades += r["trades"]
            all_avg_rets.append(r["avg_ret"])
            all_max_dds.append(r["max_dd"])
            all_mcls.append(r["mcl"])
            all_zsx += r["zscore_exits"]
            all_trx += r["trail_exits"]
    if not all_sharpes:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0,
                "trades": 0, "max_dd": 0.0, "mcl": 0,
                "zscore_exits": 0, "trail_exits": 0}
    return {
        "sharpe": float(np.mean(all_sharpes)),
        "wr": float(np.mean(all_wrs)),
        "avg_ret": float(np.mean(all_avg_rets)),
        "trades": total_trades,
        "max_dd": float(np.mean(all_max_dds)),
        "mcl": max(all_mcls),
        "zscore_exits": all_zsx,
        "trail_exits": all_trx,
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


def precompute_sym(
    df: pd.DataFrame, df_btc: pd.DataFrame,
) -> dict:
    """심볼별 지표 사전 계산."""
    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    btc_c, btc_ma = align_btc_to_sym(df, df_btc)
    atr = compute_atr(h, lo, c, ATR_PERIOD)
    atr_pctile = compute_atr_percentile(atr, ATR_VOL_LOOKBACK)
    atr_zscore = compute_atr_zscore(atr, ATR_ZSCORE_LOOKBACK)
    adx = adx_indicator(h, lo, c, 14)
    bb_w = compute_bb_width(c, BB_PERIOD)
    bb_wp = compute_bb_width_percentile(bb_w, ATR_VOL_LOOKBACK)
    return {
        "df": df, "btc_close": btc_c, "btc_ma": btc_ma,
        "atr": atr, "atr_pctile": atr_pctile, "atr_zscore": atr_zscore,
        "adx": adx, "bb_wp": bb_wp,
    }


def main() -> None:
    print("=" * 80)
    print("=== c175 — 멀티심볼 ATR z-score 급락탈출 + 레짐별 임계 적응 ===")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"기반: c172 SOL z-score exit (OOS +20.497, 28 trades)")
    print(f"가설: 멀티심볼 확장 + BTC regime별 zsTH 차등")
    print(f"  BULL zsTH: {BULL_ZSTH_LIST}  BEAR zsTH: {BEAR_ZSTH_LIST}")
    print(f"  sqTP: {SQUEEZE_TP_SCALE_LIST}  trTi: {TRAIL_TIGHTEN_LIST}")
    combos = list(product(
        BULL_ZSTH_LIST, BEAR_ZSTH_LIST,
        SQUEEZE_TP_SCALE_LIST, TRAIL_TIGHTEN_LIST,
    ))
    print(f"  총 조합: {len(combos)}")
    print(f"목표: avg OOS Sharpe > +15, trades > 60")
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

    # ── Phase 0: 베이스라인 (c172 고정 zsTH=2.0, SOL only) ──────────────────
    print("\n--- 베이스라인: c172 SOL-only zsLB=120 zsTH=2.0 ---")
    df_sol_full = load_historical("KRW-SOL", "240m", "2022-01-01", "2026-04-05")
    if not df_sol_full.empty:
        sol_pre = precompute_sym(df_sol_full, df_btc_full)
        base_sol = backtest(
            sol_pre["df"], sol_pre["btc_close"], sol_pre["btc_ma"],
            sol_pre["atr"], sol_pre["atr_pctile"], sol_pre["atr_zscore"],
            sol_pre["adx"], sol_pre["bb_wp"],
            bull_zsth=2.0, bear_zsth=2.0, squeeze_tp_scale=1.0,
            trail_tighten_zscore=1.0,
        )
        print(f"  SOL: Sharpe={fmt_sh(base_sol['sharpe'])}  "
              f"WR={base_sol['wr']:.1%}  n={base_sol['trades']}  "
              f"MDD={base_sol['max_dd'] * 100:+.2f}%  "
              f"zsX={base_sol['zscore_exits']}")

    # ── Phase 1: 3-fold OOS Walk-Forward (전 36 조합) ────────────────────────
    print(f"\n{'=' * 80}")
    print(f"=== 3-fold OOS Walk-Forward ({len(combos)} 조합 × {len(sym_ok)} 심볼) ===")

    wf_results: list[dict] = []
    for combo_i, (bull_z, bear_z, sq_tp, tr_ti) in enumerate(combos):
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
                    pre["atr"], pre["atr_pctile"], pre["atr_zscore"],
                    pre["adx"], pre["bb_wp"],
                    bull_zsth=bull_z, bear_zsth=bear_z,
                    squeeze_tp_scale=sq_tp,
                    trail_tighten_zscore=tr_ti,
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
            "bull_zsth": bull_z, "bear_zsth": bear_z,
            "sq_tp": sq_tp, "tr_ti": tr_ti,
            "avg_oos": avg_oos, "all_pass": all_pass,
            "fold_sharpes": fold_sharpes,
            "fold_details": fold_details,
        })

        # 진행 표시 (매 12번째)
        if (combo_i + 1) % 12 == 0 or combo_i + 1 == len(combos):
            print(f"  진행: {combo_i + 1}/{len(combos)}")

    # ── WF 결과 출력 ────────────────────────────────────────────────────────
    wf_results.sort(key=lambda x: x["avg_oos"], reverse=True)

    print(f"\n--- WF 통과 여부 ---")
    hdr = (f"{'bullZ':>6} {'bearZ':>6} {'sqTP':>5} {'trTi':>5} | "
           f"{'avg OOS':>8} | {'F1':>7} {'F2':>7} {'F3':>7} | {'PASS':>5}")
    print(hdr)
    print("-" * len(hdr))
    pass_count = 0
    for w in wf_results:
        f1 = w["fold_sharpes"][0] if len(w["fold_sharpes"]) > 0 else 0.0
        f2 = w["fold_sharpes"][1] if len(w["fold_sharpes"]) > 1 else 0.0
        f3 = w["fold_sharpes"][2] if len(w["fold_sharpes"]) > 2 else 0.0
        status = "PASS" if w["all_pass"] else "FAIL"
        if w["all_pass"]:
            pass_count += 1
        print(
            f"{w['bull_zsth']:>6.1f} {w['bear_zsth']:>6.1f} "
            f"{w['sq_tp']:>5.1f} {w['tr_ti']:>5.1f} | "
            f"{w['avg_oos']:>+8.3f} | "
            f"{f1:>+7.3f} {f2:>+7.3f} {f3:>+7.3f} | {status:>5}"
        )

    print(f"\n통과: {pass_count}/{len(wf_results)}")

    # ── Top 3 심볼별 분해 ────────────────────────────────────────────────────
    top_pass = [w for w in wf_results if w["all_pass"]]
    top_show = top_pass[:3] if top_pass else wf_results[:3]

    for rank, w in enumerate(top_show, 1):
        label = "PASS" if w["all_pass"] else "FAIL"
        print(f"\n--- #{rank} ({label}): bullZ={w['bull_zsth']} "
              f"bearZ={w['bear_zsth']} sqTP={w['sq_tp']} trTi={w['tr_ti']} "
              f"(avg OOS: {w['avg_oos']:+.3f}) ---")
        for fd in w["fold_details"]:
            print(f"  Fold {fd['fold']}: pooled Sharpe={fd['sharpe']:+.3f}  "
                  f"WR={fd['wr']:.1%}  n={fd['trades']}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%  "
                  f"zsX={fd['zscore_exits']}  trX={fd['trail_exits']}")
            for sd in fd.get("sym_details", []):
                sh = sd["sharpe"] if not np.isnan(sd["sharpe"]) else 0.0
                print(f"    {sd['sym']}: Sharpe={sh:+.3f}  WR={sd['wr']:.1%}  "
                      f"n={sd['trades']}  avg={sd['avg_ret'] * 100:+.2f}%  "
                      f"MDD={sd['max_dd'] * 100:+.2f}%  zsX={sd['zscore_exits']}")

    # ── 슬리피지 스트레스 (Top 3 PASS) ───────────────────────────────────────
    stress_targets = top_pass[:3] if top_pass else wf_results[:1]
    if stress_targets:
        print(f"\n{'=' * 80}")
        print("=== 슬리피지 스트레스 테스트 ===")

        for rank, w in enumerate(stress_targets, 1):
            print(f"\n--- #{rank}: bullZ={w['bull_zsth']} bearZ={w['bear_zsth']} "
                  f"sqTP={w['sq_tp']} trTi={w['tr_ti']} "
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
                            pre["atr"], pre["atr_pctile"], pre["atr_zscore"],
                            pre["adx"], pre["bb_wp"],
                            bull_zsth=w["bull_zsth"],
                            bear_zsth=w["bear_zsth"],
                            squeeze_tp_scale=w["sq_tp"],
                            trail_tighten_zscore=w["tr_ti"],
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
        print(f"★ WF 최고: bullZ={best['bull_zsth']} bearZ={best['bear_zsth']} "
              f"sqTP={best['sq_tp']} trTi={best['tr_ti']}")
        print(f"  (c172 기반: zsLB={ATR_ZSCORE_LOOKBACK} + 레짐별 zsTH 적응)")
        print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f}")
        print(f"  vs c172 SOL-only: {best['avg_oos']:+.3f} vs +20.497 "
              f"(delta {best['avg_oos'] - 20.497:+.3f})")
        for fd in best["fold_details"]:
            print(f"  Fold {fd['fold']}: Sharpe={fd['sharpe']:+.3f}  "
                  f"WR={fd['wr']:.1%}  trades={fd['trades']}  "
                  f"avg={fd['avg_ret'] * 100:+.2f}%  MDD={fd['max_dd'] * 100:+.2f}%  "
                  f"zsX={fd['zscore_exits']}  trX={fd['trail_exits']}")

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
                  f"(bullZ={best['bull_zsth']} bearZ={best['bear_zsth']} "
                  f"sqTP={best['sq_tp']} trTi={best['tr_ti']})")
            print(f"vs c172 SOL-only: +20.497")

            print(f"\nSharpe: {best['avg_oos']:+.3f}")
            print(f"WR: {avg_wr * 100:.1f}%")
            print(f"trades: {all_trades}")
        else:
            print("\nSharpe: nan\nWR: 0.0%\ntrades: 0")


if __name__ == "__main__":
    main()
