"""
momentum_sol ATR z-score 급락 탈출 — 사이클 172
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경:
  c165 (Sharpe +49.32): EMA gate + ADX relax — 단기 모멘텀 진입 우수
  c167 (Sharpe +51.05): BB squeeze breakout — 저변동 구간 진입 확보
  공통 문제: 급락 구간(2025 BEAR)에서 고정 SL이 늦게 작동 → MDD 확대

가설:
  1) ATR z-score (현재 ATR의 최근 분포 대비 z-score) 기반 동적 긴급 청산
     z-score > exit_th (2.0~3.0) → ATR이 평소 대비 극단적 확대 = 변동성 폭발
     → 즉시 청산 (손실이든 이익이든 포지션 보호)
  2) c165 최적 파라미터 유지 + ATR z-score exit overlay
  3) squeeze 경로 진입 유지 (c167): BB squeeze→expansion 감지
  4) z-score exit은 SL보다 빠르게 작동 → MDD 개선 기대

그리드:
  - atr_zscore_lookback: [60, 90, 120] — z-score 계산 윈도우 (3)
  - atr_zscore_exit_th: [1.5, 2.0, 2.5, 3.0] — 긴급 청산 임계 (4)
  - squeeze_tp_scale: [0.7, 0.8, 1.0] — squeeze 진입 TP 스케일 (3)
  - trail_tighten_zscore: [1.0, 1.5, 2.0] — z-score 상승 시 trail 강화 배수 (3)
  = 3×4×3×3 = 108 조합
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

SYMBOL = "KRW-SOL"
BTC = "KRW-BTC"
FEE = 0.0005

# ── c165 최적 파라미터 (고정) ──────────────────────────────────────────────────
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

# BB squeeze (c167 최적)
BB_PERIOD = 20
BB_SQUEEZE_PCTILE = 30
SQUEEZE_EXPAND_BARS = 3

# Grid axes
ATR_ZSCORE_LOOKBACK_LIST = [60, 90, 120]
ATR_ZSCORE_EXIT_TH_LIST = [1.5, 2.0, 2.5, 3.0]
SQUEEZE_TP_SCALE_LIST = [0.7, 0.8, 1.0]
TRAIL_TIGHTEN_ZSCORE_LIST = [1.0, 1.5, 2.0]

WF_FOLDS = [
    {"train": ("2022-01-01", "2024-06-30"), "test": ("2024-07-01", "2025-06-30")},
    {"train": ("2023-01-01", "2025-06-30"), "test": ("2025-07-01", "2026-04-01")},
]

SLIPPAGE_LEVELS = [0.0005, 0.0010, 0.0015, 0.0020]


# ── 지표 ──────────────────────────────────────────────────────────────────────

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


# ── 백테스트 ──────────────────────────────────────────────────────────────────

def backtest(
    df_sol: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_ma_main: np.ndarray,
    atr_arr: np.ndarray,
    atr_pctile: np.ndarray,
    atr_zscore: np.ndarray,
    adx_arr_ind: np.ndarray,
    bb_width_pctile: np.ndarray,
    *,
    atr_zscore_exit_th: float,
    squeeze_tp_scale: float,
    trail_tighten_zscore: float,
    slippage: float = 0.0005,
) -> dict:
    c = df_sol["close"].values
    o = df_sol["open"].values
    v = df_sol["volume"].values
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

        # Squeeze breakout 감지
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

        # BTC gate
        btc_above = (
            not np.isnan(btc_ma_main[i])
            and btc_close_aligned[i] > btc_ma_main[i]
        )
        if not btc_above and not is_squeeze_breakout:
            i += 1
            continue
        if not btc_above and is_squeeze_breakout:
            # squeeze 경로: 완화된 BTC gate 불필요 (SMA200 기본)
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

        # ADX gradient (squeeze path 해제)
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

            # Squeeze 진입: TP 스케일 적용
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

            ret = None
            exit_bar = i + 1
            trailing_active = False
            highest_ret = 0.0

            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                r = c[j] / buy - 1

                if r > highest_ret:
                    highest_ret = r

                # ★ ATR z-score 긴급 청산
                cur_zscore = atr_zscore[j] if not np.isnan(atr_zscore[j]) else 0.0
                if cur_zscore > atr_zscore_exit_th:
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


def align_btc_to_sol(
    df_sol: pd.DataFrame, df_btc: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].reindex(df_sol.index, method="ffill").values
    btc_ma_raw = compute_sma(df_btc["close"].values, 200)
    btc_ma_s = pd.Series(btc_ma_raw, index=df_btc.index)
    btc_ma_aligned = btc_ma_s.reindex(df_sol.index, method="ffill").values
    return btc_close, btc_ma_aligned


def buy_and_hold(df: pd.DataFrame) -> float:
    c = df["close"].values
    if len(c) < 2:
        return 0.0
    return float(c[-1] / c[0] - 1)


def fmt_sh(val: float) -> str:
    return f"{val:+.3f}" if not np.isnan(val) else "  nan"


def main() -> None:
    print("=" * 80)
    print("=== momentum_sol ATR z-score 급락 탈출 (사이클 172) ===")
    print(f"심볼: {SYMBOL}")
    print(f"기반: c165 EMA gate + c167 BB squeeze")
    print(f"가설: ATR z-score 기반 동적 긴급 청산 + trailing 강화")
    print(f"그리드: zsLB={ATR_ZSCORE_LOOKBACK_LIST} zsTH={ATR_ZSCORE_EXIT_TH_LIST} "
          f"sqTP={SQUEEZE_TP_SCALE_LIST} trTight={TRAIL_TIGHTEN_ZSCORE_LIST}")
    print("=" * 80)

    df_sol = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC, "240m", "2022-01-01", "2026-12-31")
    if df_sol.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"\nSOL: {len(df_sol)}행 ({df_sol.index[0]} ~ {df_sol.index[-1]})")
    print(f"BTC: {len(df_btc)}행 ({df_btc.index[0]} ~ {df_btc.index[-1]})")
    bh = buy_and_hold(df_sol)
    print(f"SOL Buy-and-Hold: {bh * 100:+.1f}%")

    # Pre-compute indicators
    btc_close_aligned, btc_ma_main = align_btc_to_sol(df_sol, df_btc)
    atr_arr = compute_atr(
        df_sol["high"].values, df_sol["low"].values,
        df_sol["close"].values, ATR_PERIOD,
    )
    atr_pctile = compute_atr_percentile(atr_arr, ATR_VOL_LOOKBACK)
    adx_arr = adx_indicator(
        df_sol["high"].values, df_sol["low"].values,
        df_sol["close"].values, 14,
    )
    bb_width = compute_bb_width(df_sol["close"].values, BB_PERIOD)
    bb_width_pctile = compute_bb_width_percentile(bb_width, ATR_VOL_LOOKBACK)

    # ── Phase 0: 베이스라인 (c165, no z-score exit) ─────────────────────────
    print("\n--- 베이스라인 (c165+c167, no z-score exit) ---")
    atr_zs_dummy = np.full(len(df_sol), 0.0)
    base = backtest(
        df_sol, btc_close_aligned, btc_ma_main,
        atr_arr, atr_pctile, atr_zs_dummy, adx_arr, bb_width_pctile,
        atr_zscore_exit_th=999.0, squeeze_tp_scale=0.8,
        trail_tighten_zscore=1.0,
    )
    print(f"  Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"avg={base['avg_ret'] * 100:+.2f}%  MDD={base['max_dd'] * 100:+.2f}%  "
          f"MCL={base['mcl']}  n={base['trades']}  "
          f"sqzN={base['squeeze_entries']}  nrmN={base['normal_entries']}")

    # ── Phase 1: 전체기간 그리드 서치 ─────────────────────────────────────────
    total = (len(ATR_ZSCORE_LOOKBACK_LIST) * len(ATR_ZSCORE_EXIT_TH_LIST)
             * len(SQUEEZE_TP_SCALE_LIST) * len(TRAIL_TIGHTEN_ZSCORE_LIST))
    print(f"\n총 조합: {total}개")
    print(f"\n{'zsLB':>5} {'zsTH':>5} {'sqTP':>5} {'trTi':>5} | "
          f"{'Sharpe':>7} {'WR':>6} {'avg%':>7} {'MDD':>7} {'MCL':>4} {'n':>5} "
          f"{'zsX':>4} {'trX':>4} {'tpX':>4} {'slX':>4} {'hldX':>5}")
    print("-" * 105)

    results: list[dict] = []
    for zs_lb in ATR_ZSCORE_LOOKBACK_LIST:
        atr_zscore = compute_atr_zscore(atr_arr, zs_lb)
        for zs_th in ATR_ZSCORE_EXIT_TH_LIST:
            for sq_tp in SQUEEZE_TP_SCALE_LIST:
                for tr_ti in TRAIL_TIGHTEN_ZSCORE_LIST:
                    r = backtest(
                        df_sol, btc_close_aligned, btc_ma_main,
                        atr_arr, atr_pctile, atr_zscore, adx_arr,
                        bb_width_pctile,
                        atr_zscore_exit_th=zs_th, squeeze_tp_scale=sq_tp,
                        trail_tighten_zscore=tr_ti,
                    )
                    results.append({
                        "zs_lb": zs_lb, "zs_th": zs_th,
                        "sq_tp": sq_tp, "tr_ti": tr_ti, **r,
                    })
                    print(
                        f"{zs_lb:>5} {zs_th:>5.1f} {sq_tp:>5.1f} {tr_ti:>5.1f} | "
                        f"{fmt_sh(r['sharpe']):>7} {r['wr']:>5.1%} "
                        f"{r['avg_ret'] * 100:>+6.2f}% "
                        f"{r['max_dd'] * 100:>+6.2f}% {r['mcl']:>4} "
                        f"{r['trades']:>5} {r['zscore_exits']:>4} "
                        f"{r['trail_exits']:>4} {r['tp_exits']:>4} "
                        f"{r['sl_exits']:>4} {r['hold_exits']:>5}"
                    )

    valid = [r for r in results
             if r["trades"] >= 30
             and not np.isnan(r["sharpe"])
             and r["sharpe"] >= 3.0]
    valid.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n유효 조합 (n≥30, Sharpe≥3.0): {len(valid)}/{len(results)}")

    high_n = [r for r in valid if r["trades"] >= 50]
    display = high_n[:15] if high_n else valid[:15]
    label = "n≥50 Top 15" if high_n else "Top 15"

    print(f"\n=== {label} (전체기간) ===")
    for rank, r in enumerate(display, 1):
        safe_cl = "✅" if r["mcl"] <= 3 else "❌"
        safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
        print(
            f"  #{rank:>2} zsLB={r['zs_lb']} zsTH={r['zs_th']:.1f} "
            f"sqTP={r['sq_tp']:.1f} trTi={r['tr_ti']:.1f}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
            f"MCL={r['mcl']}{safe_cl}  n={r['trades']}  "
            f"zsX={r['zscore_exits']}"
        )

    if not valid:
        print("유효 조합 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    best = valid[0]
    print(f"\n★ 전체기간 최적: zsLB={best['zs_lb']} zsTH={best['zs_th']:.1f} "
          f"sqTP={best['sq_tp']:.1f} trTi={best['tr_ti']:.1f}")

    # ── Phase 2: Walkforward 검증 (Top 10) ────────────────────────────────
    wf_candidates = (high_n[:10] if len(high_n) >= 5 else valid[:10])
    print(f"\n{'=' * 80}")
    print("=== Walk-Forward 검증 (Top 10, 2-fold) ===")

    wf_results: list[dict] = []
    for rank, params in enumerate(wf_candidates, 1):
        zslb = params["zs_lb"]
        zsth = params["zs_th"]
        sqtp = params["sq_tp"]
        trti = params["tr_ti"]
        print(f"\n--- #{rank}: zsLB={zslb} zsTH={zsth:.1f} "
              f"sqTP={sqtp:.1f} trTi={trti:.1f} ---")

        oos_sharpes: list[float] = []
        oos_trades: list[int] = []
        fold_details: list[dict] = []
        for fold_i, fold in enumerate(WF_FOLDS):
            df_sol_t = load_historical(
                SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_t = load_historical(
                BTC, "240m", fold["test"][0], fold["test"][1])
            if df_sol_t.empty or df_btc_t.empty:
                print(f"  Fold {fold_i + 1}: 데이터 없음")
                continue
            btc_c_t, btc_ma_t = align_btc_to_sol(df_sol_t, df_btc_t)
            atr_t = compute_atr(
                df_sol_t["high"].values, df_sol_t["low"].values,
                df_sol_t["close"].values, ATR_PERIOD,
            )
            pctile_t = compute_atr_percentile(atr_t, ATR_VOL_LOOKBACK)
            zscore_t = compute_atr_zscore(atr_t, zslb)
            adx_t = adx_indicator(
                df_sol_t["high"].values, df_sol_t["low"].values,
                df_sol_t["close"].values, 14,
            )
            bb_w_t = compute_bb_width(df_sol_t["close"].values, BB_PERIOD)
            bb_wp_t = compute_bb_width_percentile(bb_w_t, ATR_VOL_LOOKBACK)

            r = backtest(
                df_sol_t, btc_c_t, btc_ma_t,
                atr_t, pctile_t, zscore_t, adx_t, bb_wp_t,
                atr_zscore_exit_th=zsth, squeeze_tp_scale=sqtp,
                trail_tighten_zscore=trti,
            )
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            oos_sharpes.append(sh)
            oos_trades.append(r["trades"])
            fold_details.append(r)
            bh_fold = buy_and_hold(df_sol_t)
            print(f"  Fold {fold_i + 1} OOS [{fold['test'][0]}~{fold['test'][1]}]: "
                  f"Sharpe={sh:+.3f}  WR={r['wr']:.1%}  n={r['trades']}  "
                  f"avg={r['avg_ret'] * 100:+.2f}%  MDD={r['max_dd'] * 100:+.2f}%  "
                  f"zsX={r['zscore_exits']}  BH={bh_fold * 100:+.1f}%")

        if oos_sharpes:
            avg_oos = np.mean(oos_sharpes)
            min_oos = min(oos_sharpes)
            print(f"  평균 OOS Sharpe: {avg_oos:+.3f} | 최소: {min_oos:+.3f}")
            wf_results.append({
                **params,
                "avg_oos_sharpe": avg_oos,
                "min_oos_sharpe": min_oos,
                "oos_sharpes": oos_sharpes,
                "oos_trades": oos_trades,
                "fold_details": fold_details,
            })

    # ── Phase 3: 슬리피지 스트레스 (WF Top 3) ────────────────────────────────
    if not wf_results:
        print("\nWF 검증 결과 없음.")
        print("\nSharpe: nan")
        print("WR: 0.0%")
        print("trades: 0")
        return

    wf_sorted = sorted(wf_results, key=lambda x: x["avg_oos_sharpe"],
                        reverse=True)
    wf_top3 = wf_sorted[:3]

    print(f"\n{'=' * 80}")
    print("=== 슬리피지 스트레스 테스트 (WF Top 3) ===")

    for rank, params in enumerate(wf_top3, 1):
        zslb = params["zs_lb"]
        zsth = params["zs_th"]
        sqtp = params["sq_tp"]
        trti = params["tr_ti"]
        print(f"\n--- #{rank}: zsLB={zslb} zsTH={zsth:.1f} "
              f"sqTP={sqtp:.1f} trTi={trti:.1f} "
              f"(avg OOS: {params['avg_oos_sharpe']:+.3f}) ---")
        print(f"{'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7} "
              f"{'MDD':>7} {'MCL':>4} {'n':>5}")
        print("-" * 55)

        atr_zscore_full = compute_atr_zscore(atr_arr, zslb)
        for slip in SLIPPAGE_LEVELS:
            r = backtest(
                df_sol, btc_close_aligned, btc_ma_main,
                atr_arr, atr_pctile, atr_zscore_full, adx_arr,
                bb_width_pctile,
                atr_zscore_exit_th=zsth, squeeze_tp_scale=sqtp,
                trail_tighten_zscore=trti, slippage=slip,
            )
            sh = r["sharpe"] if not np.isnan(r["sharpe"]) else 0.0
            print(f"  {slip * 100:.2f}% {sh:>+8.3f} {r['wr']:>5.1%} "
                  f"{r['avg_ret'] * 100:>+6.2f}% {r['max_dd'] * 100:>+6.2f}% "
                  f"{r['mcl']:>4} {r['trades']:>5}")

    # ── 최종 요약 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    best_wf = wf_sorted[0]
    print(f"★ WF 최고: zsLB={best_wf['zs_lb']} zsTH={best_wf['zs_th']:.1f} "
          f"sqTP={best_wf['sq_tp']:.1f} trTi={best_wf['tr_ti']:.1f}")
    print(f"  (기반: c165 EMA gate + c167 BB squeeze + ATR z-score exit)")
    print(f"  avg OOS Sharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    for fi, sh in enumerate(best_wf["oos_sharpes"]):
        fd = best_wf["fold_details"][fi]
        print(f"  Fold {fi + 1}: Sharpe={sh:+.3f}  WR={fd['wr']:.1%}  "
              f"n={best_wf['oos_trades'][fi]}  MDD={fd['max_dd'] * 100:+.2f}%  "
              f"zsX={fd['zscore_exits']}  trX={fd['trail_exits']}")

    print(f"\n  vs 베이스라인 (no z-score): "
          f"Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  n={base['trades']}")

    avg_wr = np.mean([fd["wr"] for fd in best_wf["fold_details"]])
    total_n = sum(best_wf["oos_trades"])
    print(f"\nSharpe: {best_wf['avg_oos_sharpe']:+.3f}")
    print(f"WR: {avg_wr * 100:.1f}%")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    main()
