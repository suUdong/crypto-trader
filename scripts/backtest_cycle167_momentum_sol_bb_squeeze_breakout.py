"""
momentum_sol BB squeeze breakout — 사이클 167
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배경: 사이클 165 최적 sma200_gLv6 ovr=False
      OOS Fold1 Sharpe +49.32, Fold2 +16.58, 평균 +32.95
      문제: 2026년 거래 0건 — 저변동+BTC 횡보 구간에서 진입 불가

가설:
  1) Bollinger Band 폭(squeeze)이 극도로 좁아진 후 확장 시작 = 변동성 폭발 전조
     → BB width percentile < squeeze_th (20~40%) 이후 확장 시작 시 진입 허용
  2) squeeze 구간에서는 ADX gradient 필터를 완전 해제 (변동성 축소 중이라 ADX 낮음)
  3) squeeze breakout은 BTC gate 완화 허용: BTC MA 위 조건을 EMA100으로 완화
  4) 기존 momentum entry도 유지 (dual path: 기존 path + squeeze path)

그리드:
  - bb_period: [20, 30] (2)
  - bb_squeeze_pctile: [20, 30, 40] — squeeze 인식 임계값 (3)
  - squeeze_expand_bars: [2, 3, 5] — 확장 확인 봉 수 (3)
  - btc_gate_squeeze: ["ema100", "ema150", "sma200"] — squeeze 경로용 BTC gate (3)
  = 2×3×3×3 = 54 조합
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

# Confirmed from cycle 165 best (sma200_gLv6_ovrFalse)
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

# Grid axes
BB_PERIOD_LIST = [20, 30]
BB_SQUEEZE_PCTILE_LIST = [20, 30, 40]
SQUEEZE_EXPAND_BARS_LIST = [2, 3, 5]
BTC_GATE_SQUEEZE_LIST = ["ema100", "ema150", "sma200"]

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
    """Bollinger Band width = (upper - lower) / middle."""
    n = len(closes)
    width = np.full(n, np.nan)
    sma = compute_sma(closes, period)
    for i in range(period - 1, n):
        std = np.std(closes[i - period + 1:i + 1])
        if sma[i] > 0:
            width[i] = (2 * 2 * std) / sma[i]  # 2σ bands
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
    df_sol: pd.DataFrame,
    btc_close_aligned: np.ndarray,
    btc_ma_main: np.ndarray,
    btc_ma_squeeze: np.ndarray,
    atr_arr: np.ndarray,
    atr_pctile: np.ndarray,
    adx_arr_ind: np.ndarray,
    bb_width_pctile: np.ndarray,
    bb_width: np.ndarray,
    *,
    bb_squeeze_th: float,
    squeeze_expand_bars: int,
) -> dict:
    c = df_sol["close"].values
    o = df_sol["open"].values
    v = df_sol["volume"].values
    n = len(c)

    mom = np.full(n, np.nan)
    mom[LOOKBACK:] = c[LOOKBACK:] / c[:n - LOOKBACK] - 1.0
    rsi_arr = rsi(c, RSI_PERIOD)
    vol_ma = pd.Series(v).rolling(20, min_periods=20).mean().values
    vol_ok = v > VOL_MULT * vol_ma

    returns: list[float] = []
    warmup = max(LOOKBACK + RSI_PERIOD + 28, 210)
    consec_loss = 0
    cooldown_until = 0
    vol_filtered = 0
    adx_grad_filtered = 0
    btc_blocked = 0
    squeeze_entries = 0
    normal_entries = 0

    i = warmup
    while i < n - 1:
        if i < cooldown_until:
            i += 1
            continue

        # ★ Squeeze 감지: BB width percentile이 임계값 이하이다가 확장 시작
        is_squeeze_breakout = False
        if (
            not np.isnan(bb_width_pctile[i])
            and squeeze_expand_bars > 0
            and i >= squeeze_expand_bars
        ):
            # 최근 squeeze_expand_bars 이전에 squeeze 상태였는지
            was_squeezed = False
            for k in range(1, squeeze_expand_bars + 1):
                ref = i - k
                if ref >= 0 and not np.isnan(bb_width_pctile[ref]):
                    if bb_width_pctile[ref] <= bb_squeeze_th:
                        was_squeezed = True
                        break
            # 현재 BB width가 squeeze 이전 대비 확장 시작
            if was_squeezed and bb_width_pctile[i] > bb_squeeze_th:
                is_squeeze_breakout = True

        # ★ BTC gate (dual path)
        btc_above_main = (
            not np.isnan(btc_ma_main[i])
            and btc_close_aligned[i] > btc_ma_main[i]
        )
        btc_above_squeeze = (
            not np.isnan(btc_ma_squeeze[i])
            and btc_close_aligned[i] > btc_ma_squeeze[i]
        )

        # Path 1: 기존 진입 (strict BTC gate)
        # Path 2: squeeze breakout (완화된 BTC gate + ADX grad 해제)
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
            grad_bars = ADX_GRAD_BARS
            if in_lowvol:
                grad_bars = ADX_GRAD_BARS  # normal path: 유지
            if grad_bars > 0:
                ref_idx = i - grad_bars
                if (
                    ref_idx >= 0
                    and not np.isnan(adx_arr_ind[i])
                    and not np.isnan(adx_arr_ind[ref_idx])
                    and adx_arr_ind[i] <= adx_arr_ind[ref_idx]
                ):
                    adx_grad_filtered += 1
                    i += 1
                    continue
        # squeeze path: ADX gradient 필터 완전 해제

        # 적응형 ADX 임계값
        adx_thresh = ADX_THRESH_LOWVOL if in_lowvol else ADX_THRESH_BASE
        # squeeze path: ADX 임계값도 완화
        if path == "squeeze":
            adx_thresh = min(adx_thresh, ADX_THRESH_LOWVOL)

        # SOL entry signal
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

            # squeeze 진입: TP/SL 보수적 축소 (변동성 확장 초기)
            if path == "squeeze":
                tp_mult *= 0.8
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
            "normal_entries": normal_entries,
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
        "normal_entries": normal_entries,
    }


def align_btc_to_sol(
    df_sol: pd.DataFrame, df_btc: pd.DataFrame, gate_type: str,
) -> tuple[np.ndarray, np.ndarray]:
    btc_close = df_btc["close"].reindex(df_sol.index, method="ffill").values
    btc_ma = compute_btc_ma(df_btc["close"].values, gate_type)
    btc_ma_s = pd.Series(btc_ma, index=df_btc.index)
    btc_ma_aligned = btc_ma_s.reindex(df_sol.index, method="ffill").values
    return btc_close, btc_ma_aligned


def fmt_sh(val: float) -> str:
    return f"{val:+.3f}" if not np.isnan(val) else "  nan"


def main() -> None:
    print("=" * 80)
    print("momentum_sol BB squeeze breakout (사이클 167)")
    print("=" * 80)
    print(f"심볼: {SYMBOL}  기반: c165 sma200_gLv6")
    print(f"가설: BB squeeze→expansion 감지로 저변동 구간 진입 확보")
    print(f"그리드: bb_period={BB_PERIOD_LIST} squeeze_th={BB_SQUEEZE_PCTILE_LIST} "
          f"expand_bars={SQUEEZE_EXPAND_BARS_LIST} "
          f"btc_gate_squeeze={BTC_GATE_SQUEEZE_LIST}\n")

    df_sol = load_historical(SYMBOL, "240m", "2022-01-01", "2026-12-31")
    df_btc = load_historical(BTC, "240m", "2022-01-01", "2026-12-31")
    if df_sol.empty or df_btc.empty:
        print("데이터 없음.")
        return
    print(f"SOL 데이터: {len(df_sol)}행  BTC 데이터: {len(df_btc)}행\n")

    # Pre-compute SOL indicators
    atr_arr = compute_atr(
        df_sol["high"].values, df_sol["low"].values,
        df_sol["close"].values, ATR_PERIOD,
    )
    atr_pctile = compute_atr_percentile(atr_arr, ATR_VOL_LOOKBACK)
    adx_arr = adx_indicator(
        df_sol["high"].values, df_sol["low"].values, df_sol["close"].values, 14,
    )

    # BTC main gate: sma200 (c165 best)
    btc_close_aligned, btc_ma_main = align_btc_to_sol(df_sol, df_btc, "sma200")

    # ── Phase 1: Baseline (c165 best, no squeeze) ───────────────────────────
    print("=== Phase 1: Baseline (c165 sma200_gLv6, no squeeze path) ===")
    bb_w_dummy = np.full(len(df_sol), np.nan)
    bb_wp_dummy = np.full(len(df_sol), np.nan)
    base = backtest(
        df_sol, btc_close_aligned, btc_ma_main, btc_ma_main,
        atr_arr, atr_pctile, adx_arr, bb_wp_dummy, bb_w_dummy,
        bb_squeeze_th=0, squeeze_expand_bars=0,
    )
    print(f"  Sharpe={fmt_sh(base['sharpe'])}  WR={base['wr']:.1%}  "
          f"MDD={base['max_dd'] * 100:+.2f}%  consec={base['max_consec_loss']}  "
          f"trades={base['trades']}  sqzN={base['squeeze_entries']}  "
          f"normN={base['normal_entries']}")
    print()

    # ── Phase 2: 전체 그리드 탐색 ────────────────────────────────────────────
    print("=== Phase 2: BB squeeze breakout 그리드 ===")
    print(f"{'bbP':>4} {'sqTH':>5} {'exB':>4} {'sqGate':>8} "
          f"{'Sharpe':>8} {'WR':>6} {'MDD%':>8} {'cL':>4} {'trd':>5} "
          f"{'sqzN':>5} {'nrmN':>5} {'btcB':>5} {'adxF':>5}")
    print("-" * 95)

    results = []
    for bb_period in BB_PERIOD_LIST:
        bb_width = compute_bb_width(df_sol["close"].values, bb_period)
        bb_width_pctile = compute_bb_width_percentile(bb_width, ATR_VOL_LOOKBACK)

        for sq_th in BB_SQUEEZE_PCTILE_LIST:
            for ex_bars in SQUEEZE_EXPAND_BARS_LIST:
                for sq_gate in BTC_GATE_SQUEEZE_LIST:
                    _, btc_ma_sq = align_btc_to_sol(df_sol, df_btc, sq_gate)
                    r = backtest(
                        df_sol, btc_close_aligned, btc_ma_main, btc_ma_sq,
                        atr_arr, atr_pctile, adx_arr, bb_width_pctile, bb_width,
                        bb_squeeze_th=sq_th, squeeze_expand_bars=ex_bars,
                    )
                    results.append((bb_period, sq_th, ex_bars, sq_gate, r))
                    print(
                        f"{bb_period:>4} {sq_th:>5} {ex_bars:>4} {sq_gate:>8} "
                        f"{fmt_sh(r['sharpe']):>8} {r['wr']:>5.1%} "
                        f"{r['max_dd'] * 100:>+7.2f}% {r['max_consec_loss']:>4} "
                        f"{r['trades']:>5} {r['squeeze_entries']:>5} "
                        f"{r['normal_entries']:>5} {r['btc_blocked']:>5} "
                        f"{r['adx_grad_filtered']:>5}"
                    )

    # ── Phase 3: Top-10 by Sharpe ────────────────────────────────────────────
    valid = [x for x in results if not np.isnan(x[4]["sharpe"]) and x[4]["trades"] >= 10]
    valid.sort(key=lambda x: x[4]["sharpe"], reverse=True)
    top10 = valid[:10]

    print(f"\n=== Phase 3: Top-10 조합 ===")
    for rank, (bp, sq, ex, sg, r) in enumerate(top10, 1):
        safe_cl = "✅" if r["max_consec_loss"] <= 3 else "❌"
        safe_mdd = "✅" if abs(r["max_dd"]) < 0.15 else "⚠️"
        print(
            f"  #{rank:>2} bbP={bp} sqTH={sq} exB={ex} sqGate={sg}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%{safe_mdd}  "
            f"consec={r['max_consec_loss']}{safe_cl}  trades={r['trades']}  "
            f"sqzN={r['squeeze_entries']}  nrmN={r['normal_entries']}"
        )

    # ── Phase 3b: 안전 조합 ──────────────────────────────────────────────────
    safe_combos = [
        x for x in valid
        if abs(x[4]["max_dd"]) < 0.15 and x[4]["max_consec_loss"] <= 3
    ]
    safe_combos.sort(key=lambda x: x[4]["sharpe"], reverse=True)
    print(f"\n=== Phase 3b: 안전 조합 (MDD<15% AND consec≤3) — {len(safe_combos)}개 ===")
    for rank, (bp, sq, ex, sg, r) in enumerate(safe_combos[:5], 1):
        print(
            f"  #{rank} bbP={bp} sqTH={sq} exB={ex} sqGate={sg}  "
            f"Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
            f"MDD={r['max_dd'] * 100:+.2f}%  consec={r['max_consec_loss']}  "
            f"trades={r['trades']}  sqzN={r['squeeze_entries']}"
        )

    # ── Phase 4: 연도별 성과 분해 ────────────────────────────────────────────
    analysis_target = safe_combos[0] if safe_combos else (top10[0] if top10 else None)
    if analysis_target:
        bp, sq, ex, sg, _ = analysis_target
        print(f"\n=== Phase 4: 연도별 성과 분해 ===")
        print(f"  파라미터: bbP={bp} sqTH={sq} exB={ex} sqGate={sg}")
        for year in range(2022, 2027):
            df_sol_yr = load_historical(SYMBOL, "240m", f"{year}-01-01", f"{year}-12-31")
            df_btc_yr = load_historical(BTC, "240m", f"{year}-01-01", f"{year}-12-31")
            if df_sol_yr.empty or df_btc_yr.empty or len(df_sol_yr) < 100:
                print(f"  {year}: 데이터 부족")
                continue
            btc_c_yr, btc_ma_yr = align_btc_to_sol(df_sol_yr, df_btc_yr, "sma200")
            _, btc_ma_sq_yr = align_btc_to_sol(df_sol_yr, df_btc_yr, sg)
            atr_yr = compute_atr(
                df_sol_yr["high"].values, df_sol_yr["low"].values,
                df_sol_yr["close"].values, ATR_PERIOD,
            )
            pctile_yr = compute_atr_percentile(atr_yr, ATR_VOL_LOOKBACK)
            adx_yr = adx_indicator(
                df_sol_yr["high"].values, df_sol_yr["low"].values,
                df_sol_yr["close"].values, 14,
            )
            bb_w_yr = compute_bb_width(df_sol_yr["close"].values, bp)
            bb_wp_yr = compute_bb_width_percentile(bb_w_yr, ATR_VOL_LOOKBACK)
            r = backtest(
                df_sol_yr, btc_c_yr, btc_ma_yr, btc_ma_sq_yr,
                atr_yr, pctile_yr, adx_yr, bb_wp_yr, bb_w_yr,
                bb_squeeze_th=sq, squeeze_expand_bars=ex,
            )
            print(
                f"  {year}: Sharpe={fmt_sh(r['sharpe'])}  WR={r['wr']:.1%}  "
                f"MDD={r['max_dd'] * 100:+.2f}%  consec={r['max_consec_loss']}  "
                f"trades={r['trades']}  sqzN={r['squeeze_entries']}  "
                f"nrmN={r['normal_entries']}"
            )

    # ── Phase 5: Walkforward OOS 검증 ────────────────────────────────────────
    wf_targets = safe_combos[:3] if safe_combos else top10[:3]
    print(f"\n=== Phase 5: Walkforward OOS 검증 (Top-3) ===")
    best_oos = None
    best_oos_sharpe = -999.0
    for rank, (bp, sq, ex, sg, _) in enumerate(wf_targets, 1):
        label = f"bbP{bp}_sqTH{sq}_exB{ex}_{sg}"
        oos_sharpes = []
        for fi, fold in enumerate(WF_FOLDS):
            df_sol_t = load_historical(SYMBOL, "240m", fold["test"][0], fold["test"][1])
            df_btc_t = load_historical(BTC, "240m", fold["test"][0], fold["test"][1])
            if df_sol_t.empty or df_btc_t.empty:
                continue
            btc_c_t, btc_ma_t = align_btc_to_sol(df_sol_t, df_btc_t, "sma200")
            _, btc_ma_sq_t = align_btc_to_sol(df_sol_t, df_btc_t, sg)
            atr_t = compute_atr(
                df_sol_t["high"].values, df_sol_t["low"].values,
                df_sol_t["close"].values, ATR_PERIOD,
            )
            pctile_t = compute_atr_percentile(atr_t, ATR_VOL_LOOKBACK)
            adx_t = adx_indicator(
                df_sol_t["high"].values, df_sol_t["low"].values,
                df_sol_t["close"].values, 14,
            )
            bb_w_t = compute_bb_width(df_sol_t["close"].values, bp)
            bb_wp_t = compute_bb_width_percentile(bb_w_t, ATR_VOL_LOOKBACK)
            r = backtest(
                df_sol_t, btc_c_t, btc_ma_t, btc_ma_sq_t,
                atr_t, pctile_t, adx_t, bb_wp_t, bb_w_t,
                bb_squeeze_th=sq, squeeze_expand_bars=ex,
            )
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
            if avg > best_oos_sharpe:
                best_oos_sharpe = avg
                best_oos = (bp, sq, ex, sg)

    # ── Phase 6: 안전성 요약 ─────────────────────────────────────────────────
    final = analysis_target
    if final:
        _, _, _, _, best_r = final
        print(f"\n=== 안전성 요약 ===")
        print(f"  연속손실 ≤ 3: "
              f"{'✅ PASS' if best_r['max_consec_loss'] <= 3 else '❌ FAIL'} "
              f"(실제: {best_r['max_consec_loss']})")
        print(f"  MDD < 15%: "
              f"{'✅ PASS' if abs(best_r['max_dd']) < 0.15 else '⚠️ 주의'} "
              f"(실제: {best_r['max_dd'] * 100:+.2f}%)")

    # ── 최종 결과 ────────────────────────────────────────────────────────────
    if final:
        _, _, _, _, best_r = final
        print(f"\nSharpe: {best_r['sharpe']:+.3f}")
        print(f"WR: {best_r['wr'] * 100:.1f}%")
        print(f"trades: {best_r['trades']}")


if __name__ == "__main__":
    main()
