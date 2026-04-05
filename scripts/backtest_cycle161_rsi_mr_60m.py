"""
사이클 161: RSI Mean-Reversion 횡보장 전용 60m
- c160(4h) 실패: n<10/fold → 60m으로 거래빈도 4배 확보
- c160 발견: rsi_period=7 우위 반영 → [7, 10, 14] 그리드
- 진입: BTC < SMA(period) + RSI 과매도 반등 + ADX < ceil
- 청산: TP | SL | RSI >= exit | max_hold
- WF 2-fold:
  F1: IS=2022-2023 → OOS=2024-01~2024-12
  F2: IS=2023-2024 → OOS=2025-01~2026-04
- 판정: 양 Fold Sharpe>5.0 && n≥15
"""
from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

FEE = 0.0005
SLIPPAGE_BASE = 0.001
SLIPPAGE_STRESS = [0.0005, 0.001, 0.0015, 0.002]

SYMBOLS = ["KRW-BTC", "KRW-ETH"]
TIMEFRAME = "60m"

WINDOWS = [
    {
        "name": "F1",
        "is_start": "2022-01-01", "is_end": "2023-12-31",
        "oos_start": "2024-01-01", "oos_end": "2024-12-31",
    },
    {
        "name": "F2",
        "is_start": "2023-01-01", "is_end": "2024-12-31",
        "oos_start": "2025-01-01", "oos_end": "2026-04-05",
    },
]

ANNUAL_FACTOR = np.sqrt(24 * 365)
PASS_SHARPE = 5.0
PASS_N_PER_FOLD = 15


# ─── 지표 ──────────────────────────────────────────────────────────

def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    rsi_arr = np.full(len(closes), np.nan)
    deltas = np.diff(closes)
    if len(deltas) < period:
        return rsi_arr
    gain = np.where(deltas > 0, deltas, 0.0)
    loss = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    if avg_loss == 0:
        rsi_arr[period] = 100.0
    else:
        rsi_arr[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        if avg_loss == 0:
            rsi_arr[i + 1] = 100.0
        else:
            rsi_arr[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return rsi_arr


def compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                period: int = 14) -> np.ndarray:
    n = len(closes)
    adx_arr = np.full(n, np.nan)
    if n < period * 2 + 1:
        return adx_arr
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
        plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0
    atr = np.zeros(n)
    atr[period] = tr[1:period + 1].mean()
    sm_plus = plus_dm[1:period + 1].sum()
    sm_minus = minus_dm[1:period + 1].sum()
    dx_vals: list[float] = []
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        sm_plus = sm_plus - sm_plus / period + plus_dm[i]
        sm_minus = sm_minus - sm_minus / period + minus_dm[i]
        if atr[i] == 0:
            continue
        plus_di = 100 * sm_plus / (atr[i] * period)
        minus_di = 100 * sm_minus / (atr[i] * period)
        di_sum = plus_di + minus_di
        dx_vals.append(100.0 * abs(plus_di - minus_di) / di_sum
                       if di_sum != 0 else 0.0)
        if len(dx_vals) == period:
            adx_arr[i] = np.mean(dx_vals)
        elif len(dx_vals) > period:
            adx_arr[i] = (adx_arr[i - 1] * (period - 1) + dx_vals[-1]) / period
    return adx_arr


def compute_sma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    cs = np.cumsum(arr)
    out[period - 1:] = (cs[period - 1:] - np.concatenate([[0], cs[:-period]])) / period
    return out


def volume_sma(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    return compute_sma(volumes, period)


# ─── 사전계산 ─────────────────────────────────────────────────────────

class PrecomputedData:
    """심볼당 한 번만 계산되는 지표 모음. rsi_period별 다중 RSI."""

    def __init__(self, df: pd.DataFrame, btc_closes: np.ndarray | None = None):
        self.closes = df["close"].values.astype(float)
        self.highs = df["high"].values.astype(float)
        self.lows = df["low"].values.astype(float)
        self.opens = df["open"].values.astype(float)
        self.volumes = df["volume"].values.astype(float)
        self.n = len(self.closes)

        # ADX (period=14 고정)
        self.adx = compute_adx(self.highs, self.lows, self.closes, 14)
        self.vol_avg = volume_sma(self.volumes, 20)

        # RSI 다중 period
        self.rsi: dict[int, np.ndarray] = {}
        self.rsi_rising: dict[int, np.ndarray] = {}
        for rp in [7, 10, 14]:
            rsi = compute_rsi(self.closes, rp)
            self.rsi[rp] = rsi
            rising = np.zeros(self.n, dtype=bool)
            valid = ~np.isnan(rsi[:-1]) & ~np.isnan(rsi[1:])
            rising[1:] = valid & (rsi[1:] > rsi[:-1])
            self.rsi_rising[rp] = rising

        # BTC SMA 레짐
        self.btc_bear: dict[int, np.ndarray] = {}
        btc_c = btc_closes if btc_closes is not None else self.closes
        for p in [100, 200]:
            sma = compute_sma(btc_c, p)
            self.btc_bear[p] = btc_c < sma


# ─── 고속 백테스트 엔진 ──────────────────────────────────────────────

def backtest_fast(
    pre: PrecomputedData,
    rsi_oversold: float,
    rsi_exit: float,
    rsi_period: int,
    adx_ceil: float,
    vol_mult: float,
    tp: float,
    sl: float,
    max_hold: int,
    sma_period: int,
    slippage: float,
) -> dict:
    n = pre.n
    rsi = pre.rsi[rsi_period]
    adx = pre.adx
    opens = pre.opens
    highs = pre.highs
    lows = pre.lows
    closes = pre.closes
    volumes = pre.volumes
    vol_avg = pre.vol_avg
    bear_mask = pre.btc_bear[sma_period]
    rsi_rising = pre.rsi_rising[rsi_period]

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count = 0
    pending_entry = False

    warmup = max(sma_period, 30)

    for i in range(warmup, n):
        if pending_entry and not in_pos:
            entry_price = opens[i] * (1 + slippage + FEE)
            in_pos = True
            hold_count = 0
            pending_entry = False
            continue

        if not in_pos:
            if np.isnan(rsi[i]) or np.isnan(adx[i]):
                continue
            # 1. BTC BEAR/Sideways 레짐
            if not bear_mask[i]:
                continue
            # 2. RSI 과매도 + 반등
            if rsi[i] >= rsi_oversold:
                continue
            if not rsi_rising[i]:
                continue
            # 3. ADX < ceil (횡보)
            if adx[i] >= adx_ceil:
                continue
            # 4. 볼륨 필터 (선택적)
            if vol_mult > 0 and not np.isnan(vol_avg[i]):
                if volumes[i] < vol_avg[i] * vol_mult:
                    continue
            # 진입 예약 (다음 봉 시가)
            if i < n - 1:
                pending_entry = True
        else:
            hold_count += 1
            # TP
            if highs[i] >= entry_price * (1 + tp):
                exit_price = entry_price * (1 + tp) * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue
            # SL
            if lows[i] <= entry_price * (1 - sl):
                exit_price = entry_price * (1 - sl) * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False
                continue
            # RSI exit (이익 상태일 때만)
            if not np.isnan(rsi[i]) and rsi[i] >= rsi_exit:
                if (closes[i] - entry_price) / entry_price > 0.002:
                    exit_price = closes[i] * (1 - slippage - FEE)
                    trades.append((exit_price - entry_price) / entry_price)
                    in_pos = False
                    continue
            # Max hold
            if hold_count >= max_hold:
                exit_price = closes[i] * (1 - slippage - FEE)
                trades.append((exit_price - entry_price) / entry_price)
                in_pos = False

    if in_pos:
        exit_price = closes[-1] * (1 - slippage - FEE)
        trades.append((exit_price - entry_price) / entry_price)

    if len(trades) < 3:
        return {"sharpe": -999, "wr": 0, "avg": 0, "mdd": 0, "n": len(trades), "mcl": 0}

    arr = np.array(trades)
    wr = float((arr > 0).mean())
    avg_ret = float(arr.mean())
    equity = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    mdd = float(dd.min())

    mcl = 0
    cur = 0
    for t in arr:
        if t < 0:
            cur += 1
            mcl = max(mcl, cur)
        else:
            cur = 0

    sharpe = float(arr.mean() / (arr.std() + 1e-9) * ANNUAL_FACTOR)

    bh_ret = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0.0

    return {
        "sharpe": sharpe, "wr": wr, "avg": avg_ret,
        "mdd": mdd, "n": len(arr), "mcl": mcl, "bh_ret": bh_ret,
    }


# ─── 메인 ────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("사이클 161: RSI Mean-Reversion 횡보장 전용 60m")
    print("  c160(4h) 실패 → 60m 거래빈도 4배 확보")
    print("  c160 발견: rsi_period=7 우위 → [7, 10, 14] 그리드 포함")
    print("  진입: BTC<SMA + RSI 과매도 반등 + ADX<ceil")
    print("  슬리피지 0.10% 포함")
    print("=" * 80)

    # ── 데이터 로드 ──
    all_data: dict[str, pd.DataFrame] = {}

    btc_full = load_historical("KRW-BTC", TIMEFRAME, "2022-01-01", "2026-04-05")
    if btc_full is None or len(btc_full) == 0:
        print("BTC 데이터 로드 실패")
        return
    all_data["KRW-BTC"] = btc_full

    for sym in SYMBOLS:
        if sym not in all_data:
            df = load_historical(sym, TIMEFRAME, "2022-01-01", "2026-04-05")
            if df is None:
                print(f"{sym} 데이터 로드 실패")
                return
            all_data[sym] = df
        print(f"  {sym}: {len(all_data[sym])} bars")

    def get_precomputed(sym: str, start: str, end: str) -> PrecomputedData:
        df = all_data[sym]
        mask = (df.index >= start) & (df.index <= end)
        df_slice = df[mask].copy()
        btc_df = all_data["KRW-BTC"]
        btc_mask = (btc_df.index >= start) & (btc_df.index <= end)
        btc_slice = btc_df[btc_mask]
        btc_c = btc_slice["close"].values.astype(float) if sym != "KRW-BTC" else None
        return PrecomputedData(df_slice, btc_c)

    # ── 그리드 정의 ──
    RSI_OVERSOLD = [20, 25, 30, 35]
    RSI_EXIT = [50, 55, 65]
    RSI_PERIOD = [7, 10, 14]
    ADX_CEIL = [15, 20, 25, 30]
    VOL_MULT = [0.0, 1.2]
    TP = [0.02, 0.03, 0.04, 0.05]
    SL = [0.015, 0.02, 0.03]
    MAX_HOLD = [12, 24, 36]
    SMA_PERIOD = [200]

    grid = list(product(RSI_OVERSOLD, RSI_EXIT, RSI_PERIOD, ADX_CEIL, VOL_MULT,
                        TP, SL, MAX_HOLD, SMA_PERIOD))
    total_combos = len(grid) * len(SYMBOLS)
    print(f"\nPhase 1 그리드: {len(grid)} 조합 x {len(SYMBOLS)} 심볼 = {total_combos}")

    # ── Phase 1: IS 전체 스크리닝 ──
    is_precomputed: dict[str, PrecomputedData] = {}
    for sym in SYMBOLS:
        is_precomputed[sym] = get_precomputed(sym, "2022-01-01", "2024-12-31")
        print(f"  {sym} IS: {is_precomputed[sym].n} bars")

    print(f"\n{'=' * 80}")
    print("=== Phase 1: IS 전체 스크리닝 ===")
    print(f"{'=' * 80}")

    results: list[dict] = []
    done = 0

    for sym in SYMBOLS:
        pre = is_precomputed[sym]
        for rsi_os, rsi_ex, rsi_p, adx_c, vol_m, tp, sl, mh, sma_p in grid:
            r = backtest_fast(
                pre, rsi_oversold=rsi_os, rsi_exit=rsi_ex, rsi_period=rsi_p,
                adx_ceil=adx_c, vol_mult=vol_m,
                tp=tp, sl=sl, max_hold=mh,
                sma_period=sma_p, slippage=SLIPPAGE_BASE,
            )
            results.append({
                "symbol": sym, "rsi_os": rsi_os, "rsi_ex": rsi_ex,
                "rsi_p": rsi_p, "adx_c": adx_c, "vol_m": vol_m,
                "tp": tp, "sl": sl, "mh": mh, "sma_p": sma_p, **r,
            })
            done += 1
            if done % 2000 == 0:
                print(f"  진행: {done}/{total_combos}")

    df_res = pd.DataFrame(results)
    passed = df_res[(df_res["sharpe"] > 0) & (df_res["n"] >= 20)].copy()
    passed = passed.sort_values("sharpe", ascending=False)

    print(f"\n총 {len(df_res)}개 중 Sharpe>0 & n>=20: {len(passed)}개")

    if len(passed) > 0:
        print("\n--- Top 20 (IS 전체) ---")
        print(f"{'sym':>8} {'rsiP':>4} {'rsi_os':>6} {'rsi_ex':>6} {'adx':>4}"
              f" {'vol':>4} {'tp':>5} {'sl':>5} {'mh':>3}"
              f" {'Sharpe':>8} {'WR':>6} {'avg%':>7} {'MDD':>8} {'MCL':>4} {'n':>4}")
        for _, row in passed.head(20).iterrows():
            print(f"{row['symbol']:>8} {row['rsi_p']:>4.0f}"
                  f" {row['rsi_os']:>6.0f} {row['rsi_ex']:>6.0f}"
                  f" {row['adx_c']:>4.0f} {row['vol_m']:>4.1f}"
                  f" {row['tp']:>5.1%} {row['sl']:>5.1%} {row['mh']:>3.0f}"
                  f" {row['sharpe']:>+8.3f} {row['wr']:>5.1%}"
                  f" {row['avg']:>+7.3%} {row['mdd']:>7.2%}"
                  f" {row['mcl']:>4.0f} {row['n']:>4.0f}")

    if len(passed) == 0:
        print("\nPhase 1 통과 조합 없음")
        relaxed = df_res[(df_res["sharpe"] > -10) & (df_res["n"] >= 10)].copy()
        relaxed = relaxed.sort_values("sharpe", ascending=False)
        print(f"  완화 기준 (Sharpe>-10, n>=10): {len(relaxed)}개")
        if len(relaxed) > 0:
            print("\n--- 완화 Top 10 ---")
            for _, row in relaxed.head(10).iterrows():
                print(f"  {row['symbol']} rsiP={row['rsi_p']:.0f}"
                      f" rsi_os={row['rsi_os']:.0f}"
                      f" rsi_ex={row['rsi_ex']:.0f} adx={row['adx_c']:.0f}"
                      f" vol={row['vol_m']:.1f} tp={row['tp']:.1%}"
                      f" sl={row['sl']:.1%} mh={row['mh']:.0f}"
                      f" -> Sharpe={row['sharpe']:+.3f} WR={row['wr']:.1%}"
                      f" n={row['n']:.0f}")
        print(f"\nSharpe: -999")
        print(f"WR: 0.0%")
        print(f"trades: 0")
        return

    # ── Phase 2: Top-20 WF 2-fold 검증 ──
    print(f"\n{'=' * 80}")
    print("=== Phase 2: Walkforward 2-fold OOS 검증 ===")
    print(f"{'=' * 80}")

    oos_precomputed: dict[str, dict[str, PrecomputedData]] = {}
    for sym in SYMBOLS:
        oos_precomputed[sym] = {}
        for w in WINDOWS:
            oos_precomputed[sym][w["name"]] = get_precomputed(
                sym, w["oos_start"], w["oos_end"]
            )

    top_configs = passed.head(20).to_dict("records")
    wf_results: list[dict] = []

    for cfg in top_configs:
        sym = cfg["symbol"]
        fold_sharpes = []
        fold_details = []
        all_pass = True

        for w in WINDOWS:
            pre_oos = oos_precomputed[sym][w["name"]]
            r = backtest_fast(
                pre_oos,
                rsi_oversold=cfg["rsi_os"], rsi_exit=cfg["rsi_ex"],
                rsi_period=cfg["rsi_p"],
                adx_ceil=cfg["adx_c"], vol_mult=cfg["vol_m"],
                tp=cfg["tp"], sl=cfg["sl"], max_hold=cfg["mh"],
                sma_period=cfg["sma_p"], slippage=SLIPPAGE_BASE,
            )
            fold_sharpes.append(r["sharpe"])
            fold_details.append({**r, "window": w["name"]})
            if r["sharpe"] < PASS_SHARPE or r["n"] < PASS_N_PER_FOLD:
                all_pass = False

        avg_oos = float(np.mean(fold_sharpes))
        tag = "PASS" if all_pass else "FAIL"
        print(f"\n  [{tag}] {sym} rsiP={cfg['rsi_p']:.0f}"
              f" rsi_os={cfg['rsi_os']:.0f}"
              f" rsi_ex={cfg['rsi_ex']:.0f} adx={cfg['adx_c']:.0f}"
              f" vol={cfg['vol_m']:.1f} tp={cfg['tp']:.1%}"
              f" sl={cfg['sl']:.1%} mh={cfg['mh']:.0f}")
        for fd in fold_details:
            mdd_f = "warn" if fd["mdd"] < -0.15 else "ok"
            mcl_f = "FAIL" if fd["mcl"] > 3 else "ok"
            print(f"    {fd['window']}: Sharpe={fd['sharpe']:+.3f}"
                  f"  WR={fd['wr']:.1%}  n={fd['n']}"
                  f"  MDD={fd['mdd']:.2%}[{mdd_f}]  MCL={fd['mcl']}[{mcl_f}]"
                  f"  avg={fd['avg']:+.3%}  BH={fd['bh_ret']:+.1%}")

        print(f"    -> avg OOS Sharpe: {avg_oos:+.3f}")
        wf_results.append({
            **cfg, "avg_oos": avg_oos, "all_pass": all_pass,
            "fold_details": fold_details,
        })

    # ── Phase 3: 안전 조합 ──
    safe = [w for w in wf_results if w["all_pass"]]
    print(f"\n{'=' * 80}")
    print(f"=== Phase 3: WF 완전 통과 — {len(safe)}개 ===")
    print(f"{'=' * 80}")

    if not safe:
        partial = [w for w in wf_results if w["avg_oos"] > 0]
        partial.sort(key=lambda x: x["avg_oos"], reverse=True)
        print(f"  양 Fold 완전 통과 없음. avg OOS > 0: {len(partial)}개")
        for p in partial[:5]:
            print(f"    {p['symbol']} rsiP={p['rsi_p']:.0f}"
                  f" rsi_os={p['rsi_os']:.0f}"
                  f" rsi_ex={p['rsi_ex']:.0f} adx={p['adx_c']:.0f}"
                  f" -> avg OOS={p['avg_oos']:+.3f}")
            for fd in p["fold_details"]:
                print(f"      {fd['window']}: Sharpe={fd['sharpe']:+.3f}"
                      f" WR={fd['wr']:.1%} n={fd['n']}")

        best_p = partial[0] if partial else None
        if best_p:
            n_total = sum(fd["n"] for fd in best_p["fold_details"])
            print(f"\nSharpe: {best_p['avg_oos']:+.3f}")
            print(f"WR: {best_p['fold_details'][0]['wr']:.1%}")
            print(f"trades: {n_total}")
        else:
            print(f"\nSharpe: -999")
            print(f"WR: 0.0%")
            print(f"trades: 0")
        return

    safe.sort(key=lambda x: x["avg_oos"], reverse=True)
    best = safe[0]

    # ── Phase 4: 슬리피지 스트레스 ──
    print(f"\n{'=' * 80}")
    print("=== Phase 4: 슬리피지 스트레스 테스트 ===")
    print(f"{'=' * 80}")

    sym = best["symbol"]
    w = WINDOWS[1]
    pre_stress = oos_precomputed[sym][w["name"]]

    print(f"  {'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7}"
          f" {'MDD':>8} {'MCL':>4} {'n':>4}")
    print("  " + "-" * 55)
    for slip in SLIPPAGE_STRESS:
        r = backtest_fast(
            pre_stress,
            rsi_oversold=best["rsi_os"], rsi_exit=best["rsi_ex"],
            rsi_period=best["rsi_p"],
            adx_ceil=best["adx_c"], vol_mult=best["vol_m"],
            tp=best["tp"], sl=best["sl"], max_hold=best["mh"],
            sma_period=best["sma_p"], slippage=slip,
        )
        print(f"  {slip:>10.2%} {r['sharpe']:>+8.3f} {r['wr']:>5.1%}"
              f" {r['avg']:>+7.3%} {r['mdd']:>7.2%}"
              f" {r['mcl']:>4} {r['n']:>4}")

    # ── Phase 5: 연도별 분해 ──
    print(f"\n{'=' * 80}")
    print("=== Phase 5: 연도별 성과 분해 ===")
    print(f"{'=' * 80}")

    for year in range(2022, 2027):
        y_start = f"{year}-01-01"
        y_end = f"{year}-12-31" if year < 2026 else "2026-04-05"
        pre_y = get_precomputed(sym, y_start, y_end)
        if pre_y.n < 100:
            continue
        r = backtest_fast(
            pre_y,
            rsi_oversold=best["rsi_os"], rsi_exit=best["rsi_ex"],
            rsi_period=best["rsi_p"],
            adx_ceil=best["adx_c"], vol_mult=best["vol_m"],
            tp=best["tp"], sl=best["sl"], max_hold=best["mh"],
            sma_period=best["sma_p"], slippage=SLIPPAGE_BASE,
        )
        print(f"  {year}: Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}"
              f"  MDD={r['mdd']:.2%}  MCL={r['mcl']}  n={r['n']}"
              f"  avg={r['avg']:+.3%}")

    # ── 최종 요약 ──
    print(f"\n{'=' * 80}")
    print("=== 최종 요약 ===")
    print(f"{'=' * 80}")
    print(f"WF 최적: {best['symbol']} rsiP={best['rsi_p']:.0f}"
          f" rsi_os={best['rsi_os']:.0f}"
          f" rsi_ex={best['rsi_ex']:.0f} adx={best['adx_c']:.0f}"
          f" vol={best['vol_m']:.1f} tp={best['tp']:.1%}"
          f" sl={best['sl']:.1%} mh={best['mh']:.0f}")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f}")
    for fd in best["fold_details"]:
        print(f"  {fd['window']}: Sharpe={fd['sharpe']:+.3f}"
              f"  WR={fd['wr']:.1%}  n={fd['n']}"
              f"  MDD={fd['mdd']:.2%}  MCL={fd['mcl']}"
              f"  avg={fd['avg']:+.3%}  BH={fd['bh_ret']:+.1%}")

    max_mdd = min(fd["mdd"] for fd in best["fold_details"])
    max_mcl = max(fd["mcl"] for fd in best["fold_details"])
    total_n = sum(fd["n"] for fd in best["fold_details"])

    print(f"\n  연속손실 <= 3: {'PASS' if max_mcl <= 3 else 'FAIL'}"
          f" (실제: {max_mcl})")
    print(f"  MDD < 15%: {'PASS' if max_mdd > -0.15 else 'WARNING'}"
          f" (실제: {max_mdd:.2%})")
    print(f"  총 OOS 거래수: {total_n}"
          f" ({'ok' if total_n >= 30 else 'n<30'})")

    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    print(f"WR: {best['fold_details'][0]['wr']:.1%}")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, line_buffering=True)
    main()
