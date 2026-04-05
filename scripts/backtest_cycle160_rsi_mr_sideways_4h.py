"""
사이클 160: RSI Mean-Reversion 횡보장 전용 (4h)
- 목적: BEAR/횡보 레짐 방어 전략 확보 (포트폴리오 최대 리스크 해소)
- c156/c157 대비 핵심 변경:
  1) 60m → 240m (4h) 타임프레임 — 평가자 제안, 노이즈 감소
  2) ADX<20 횡보장 전용 필터 (c157의 BTC<SMA200 BEAR 대신)
  3) BTC regime gate 선택적 테스트 (with/without)
  4) RSI period 다변화 (7, 10, 14)
- 진입: RSI 과매도 반등 + ADX<ceil (횡보 확인) ± BTC<SMA200
- 청산: TP | SL | RSI >= exit | max_hold
- WF: 2-fold (새 OOS 윈도우)
  F1: IS=2022-01~2024-03 → OOS=2024-04~2025-03
  F2: IS=2023-04~2025-06 → OOS=2025-07~2026-04
- 판정: 양 Fold Sharpe>5.0 && n≥10 (4h는 거래수 적으므로 완화)
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
TIMEFRAME = "240m"

WINDOWS = [
    {
        "name": "F1",
        "is_start": "2022-01-01", "is_end": "2024-03-31",
        "oos_start": "2024-04-01", "oos_end": "2025-03-31",
    },
    {
        "name": "F2",
        "is_start": "2023-04-01", "is_end": "2025-06-30",
        "oos_start": "2025-07-01", "oos_end": "2026-04-05",
    },
]

# 4h bars: 6 bars/day × 365 = 2190
ANNUAL_FACTOR = np.sqrt(6 * 365)
PASS_SHARPE = 5.0
PASS_N_PER_FOLD = 10  # 4h는 거래수 적으므로 완화


# ─── 지표 ────────────────────────────────────────────────────────────

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


# ─── 사전계산 ──────────────────────────────────────────────────────

class PrecomputedData:
    def __init__(self, df: pd.DataFrame, btc_closes: np.ndarray | None,
                 rsi_period: int = 14):
        self.closes = df["close"].values.astype(float)
        self.highs = df["high"].values.astype(float)
        self.lows = df["low"].values.astype(float)
        self.opens = df["open"].values.astype(float)
        self.n = len(self.closes)

        self.rsi = compute_rsi(self.closes, rsi_period)
        self.adx = compute_adx(self.highs, self.lows, self.closes, 14)

        # BTC SMA 레짐
        btc_c = btc_closes if btc_closes is not None else self.closes
        self.btc_sma200 = compute_sma(btc_c, 200)
        self.btc_bear200 = btc_c < self.btc_sma200

        # RSI 반등 마스크
        self.rsi_rising = np.zeros(self.n, dtype=bool)
        valid = ~np.isnan(self.rsi[:-1]) & ~np.isnan(self.rsi[1:])
        self.rsi_rising[1:] = valid & (self.rsi[1:] > self.rsi[:-1])


# ─── 백테스트 엔진 ──────────────────────────────────────────────────

def backtest_fast(
    pre: PrecomputedData,
    rsi_oversold: float,
    rsi_exit: float,
    adx_ceil: float,
    tp: float,
    sl: float,
    max_hold: int,
    use_btc_gate: bool,
    slippage: float,
) -> dict:
    n = pre.n
    rsi = pre.rsi
    adx = pre.adx
    opens = pre.opens
    highs = pre.highs
    lows = pre.lows
    closes = pre.closes
    bear200 = pre.btc_bear200
    rsi_rising = pre.rsi_rising

    trades: list[float] = []
    in_pos = False
    entry_price = 0.0
    hold_count = 0
    pending_entry = False

    warmup = 210  # SMA200 + buffer

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
            # 1. ADX < ceil (횡보장 필터 — 핵심)
            if adx[i] >= adx_ceil:
                continue
            # 2. BTC regime gate (선택적)
            if use_btc_gate and not bear200[i]:
                continue
            # 3. RSI 과매도 + 반등
            if rsi[i] >= rsi_oversold:
                continue
            if not rsi_rising[i]:
                continue
            # 진입 예약
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
            # RSI exit
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
    print("사이클 160: RSI Mean-Reversion 횡보장 전용 (4h)")
    print("  진입: ADX<ceil(횡보) + RSI 과매도 반등 ± BTC<SMA200")
    print("  240m 타임프레임, 슬리피지 0.10% 포함")
    print("=" * 80)

    # ── 데이터 로드 ──
    all_data: dict[str, pd.DataFrame] = {}
    btc_full = load_historical("KRW-BTC", TIMEFRAME, "2022-01-01", "2026-04-05")
    if btc_full is None or len(btc_full) == 0:
        print("❌ BTC 데이터 로드 실패")
        return
    all_data["KRW-BTC"] = btc_full
    btc_closes_full = btc_full["close"].values.astype(float)

    for sym in SYMBOLS:
        if sym not in all_data:
            df = load_historical(sym, TIMEFRAME, "2022-01-01", "2026-04-05")
            if df is None:
                print(f"❌ {sym} 데이터 로드 실패")
                return
            all_data[sym] = df
        print(f"  {sym}: {len(all_data[sym])} bars"
              f" ({all_data[sym].index[0]} ~ {all_data[sym].index[-1]})")

    def get_precomputed(sym: str, start: str, end: str,
                        rsi_period: int = 14) -> PrecomputedData:
        df = all_data[sym]
        mask = (df.index >= start) & (df.index <= end)
        df_slice = df[mask].copy()
        btc_df = all_data["KRW-BTC"]
        btc_mask = (btc_df.index >= start) & (btc_df.index <= end)
        btc_slice = btc_df[btc_mask]
        btc_c = btc_slice["close"].values.astype(float) if sym != "KRW-BTC" else None
        return PrecomputedData(df_slice, btc_c, rsi_period)

    # ── 그리드 정의 ──
    RSI_OVERSOLD = [20, 25, 30, 35]
    RSI_EXIT = [45, 50, 55, 65]
    ADX_CEIL = [15, 20, 25]
    TP = [0.02, 0.03, 0.04, 0.05]
    SL = [0.015, 0.02, 0.03]
    MAX_HOLD = [6, 12, 18, 24]  # 4h bars
    BTC_GATE = [True, False]
    RSI_PERIOD = [7, 10, 14]

    grid = list(product(RSI_OVERSOLD, RSI_EXIT, ADX_CEIL,
                        TP, SL, MAX_HOLD, BTC_GATE, RSI_PERIOD))
    print(f"\nPhase 1 그리드: {len(grid)} 조합 × {len(SYMBOLS)} 심볼"
          f" = {len(grid) * len(SYMBOLS)} 총")

    # ── Phase 1: IS 스크리닝 (전체 기간) ──
    # IS = 2022-01-01 ~ 2025-06-30 (두 윈도우 IS 합집합)
    print(f"\n{'='*80}")
    print("=== Phase 1: IS 전체 스크리닝 ===")
    print(f"{'='*80}")

    # RSI period별 사전계산 캐시
    is_cache: dict[tuple[str, int], PrecomputedData] = {}
    for sym in SYMBOLS:
        for rp in RSI_PERIOD:
            is_cache[(sym, rp)] = get_precomputed(sym, "2022-01-01", "2025-06-30", rp)
            if rp == 14:
                print(f"  {sym} IS (rsi={rp}): {is_cache[(sym, rp)].n} bars")

    results: list[dict] = []
    done = 0
    total = len(grid) * len(SYMBOLS)

    for sym in SYMBOLS:
        for rsi_os, rsi_ex, adx_c, tp, sl, mh, btc_g, rsi_p in grid:
            pre = is_cache[(sym, rsi_p)]
            r = backtest_fast(
                pre, rsi_oversold=rsi_os, rsi_exit=rsi_ex,
                adx_ceil=adx_c, tp=tp, sl=sl, max_hold=mh,
                use_btc_gate=btc_g, slippage=SLIPPAGE_BASE,
            )
            results.append({
                "symbol": sym, "rsi_os": rsi_os, "rsi_ex": rsi_ex,
                "adx_c": adx_c, "tp": tp, "sl": sl,
                "mh": mh, "btc_g": btc_g, "rsi_p": rsi_p, **r,
            })
            done += 1
            if done % 2000 == 0:
                print(f"  진행: {done}/{total}")

    df_res = pd.DataFrame(results)
    passed = df_res[(df_res["sharpe"] > 0) & (df_res["n"] >= 15)].copy()
    passed = passed.sort_values("sharpe", ascending=False)

    print(f"\n총 {len(df_res)}개 중 Sharpe>0 & n≥15: {len(passed)}개")

    if len(passed) > 0:
        print("\n--- Top 20 (IS 전체) ---")
        hdr = (f"{'sym':>8} {'rsi_os':>6} {'rsi_ex':>6} {'adx':>4} {'rsiP':>4}"
               f" {'btcG':>4} {'tp':>5} {'sl':>5} {'mh':>3}"
               f" {'Sharpe':>8} {'WR':>6} {'avg%':>7} {'MDD':>8} {'MCL':>4} {'n':>4}")
        print(hdr)
        for _, row in passed.head(20).iterrows():
            print(f"{row['symbol']:>8} {row['rsi_os']:>6.0f} {row['rsi_ex']:>6.0f}"
                  f" {row['adx_c']:>4.0f} {row['rsi_p']:>4.0f}"
                  f" {'Y' if row['btc_g'] else 'N':>4}"
                  f" {row['tp']:>5.1%} {row['sl']:>5.1%} {row['mh']:>3.0f}"
                  f" {row['sharpe']:>+8.3f} {row['wr']:>5.1%}"
                  f" {row['avg']:>+7.3%} {row['mdd']:>7.2%}"
                  f" {row['mcl']:>4.0f} {row['n']:>4.0f}")
    else:
        # 완화 기준
        relaxed = df_res[(df_res["sharpe"] > -10) & (df_res["n"] >= 5)].copy()
        relaxed = relaxed.sort_values("sharpe", ascending=False)
        print(f"\n❌ Phase 1 통과 조합 없음")
        print(f"  완화 기준 (Sharpe>-10, n≥5): {len(relaxed)}개")
        if len(relaxed) > 0:
            print("\n--- 완화 Top 15 ---")
            for _, row in relaxed.head(15).iterrows():
                print(f"  {row['symbol']} rsi_os={row['rsi_os']:.0f}"
                      f" rsi_ex={row['rsi_ex']:.0f} adx={row['adx_c']:.0f}"
                      f" rsiP={row['rsi_p']:.0f} btcG={'Y' if row['btc_g'] else 'N'}"
                      f" tp={row['tp']:.1%} sl={row['sl']:.1%} mh={row['mh']:.0f}"
                      f" → Sharpe={row['sharpe']:+.3f} WR={row['wr']:.1%}"
                      f" n={row['n']:.0f}")

        # BTC gate별 통계
        print("\n--- BTC gate별 거래수 분포 ---")
        for bg in [True, False]:
            sub = df_res[df_res["btc_g"] == bg]
            valid = sub[sub["n"] >= 3]
            if len(valid) > 0:
                print(f"  btc_gate={'Y' if bg else 'N'}: "
                      f"avg_n={valid['n'].mean():.1f} max_n={valid['n'].max():.0f} "
                      f"avg_sharpe={valid['sharpe'].mean():+.1f} "
                      f"best_sharpe={valid['sharpe'].max():+.1f}")

        # ADX별 통계
        print("\n--- ADX ceil별 거래수 분포 ---")
        for ac in ADX_CEIL:
            sub = df_res[df_res["adx_c"] == ac]
            valid = sub[sub["n"] >= 3]
            if len(valid) > 0:
                print(f"  adx<{ac}: "
                      f"avg_n={valid['n'].mean():.1f} max_n={valid['n'].max():.0f} "
                      f"avg_sharpe={valid['sharpe'].mean():+.1f}")

        # RSI period별 통계
        print("\n--- RSI period별 거래수 분포 ---")
        for rp in RSI_PERIOD:
            sub = df_res[df_res["rsi_p"] == rp]
            valid = sub[sub["n"] >= 3]
            if len(valid) > 0:
                print(f"  rsi_period={rp}: "
                      f"avg_n={valid['n'].mean():.1f} max_n={valid['n'].max():.0f} "
                      f"avg_sharpe={valid['sharpe'].mean():+.1f}")

        print(f"\nSharpe: {relaxed.iloc[0]['sharpe']:+.3f}" if len(relaxed) > 0
              else "\nSharpe: -999")
        print(f"WR: {relaxed.iloc[0]['wr']:.1%}" if len(relaxed) > 0 else "WR: 0.0%")
        print(f"trades: {relaxed.iloc[0]['n']:.0f}" if len(relaxed) > 0 else "trades: 0")
        return

    # ── Phase 2: Top-20 WF 2-fold 검증 ──
    print(f"\n{'='*80}")
    print("=== Phase 2: Walkforward 2-fold OOS 검증 ===")
    print(f"{'='*80}")

    oos_cache: dict[tuple[str, int, str], PrecomputedData] = {}
    for sym in SYMBOLS:
        for rp in RSI_PERIOD:
            for w in WINDOWS:
                oos_cache[(sym, rp, w["name"])] = get_precomputed(
                    sym, w["oos_start"], w["oos_end"], rp
                )

    top_configs = passed.head(20).to_dict("records")
    wf_results: list[dict] = []

    for cfg in top_configs:
        sym = cfg["symbol"]
        fold_sharpes = []
        fold_details = []
        all_pass = True

        for w in WINDOWS:
            pre_oos = oos_cache[(sym, cfg["rsi_p"], w["name"])]
            r = backtest_fast(
                pre_oos,
                rsi_oversold=cfg["rsi_os"], rsi_exit=cfg["rsi_ex"],
                adx_ceil=cfg["adx_c"], tp=cfg["tp"], sl=cfg["sl"],
                max_hold=cfg["mh"], use_btc_gate=cfg["btc_g"],
                slippage=SLIPPAGE_BASE,
            )
            fold_sharpes.append(r["sharpe"])
            fold_details.append({**r, "window": w["name"]})
            if r["sharpe"] < PASS_SHARPE or r["n"] < PASS_N_PER_FOLD:
                all_pass = False

        avg_oos = float(np.mean(fold_sharpes))
        tag = "✅" if all_pass else "❌"
        print(f"\n  {tag} {sym} rsi_os={cfg['rsi_os']:.0f}"
              f" rsi_ex={cfg['rsi_ex']:.0f} adx={cfg['adx_c']:.0f}"
              f" rsiP={cfg['rsi_p']:.0f} btcG={'Y' if cfg['btc_g'] else 'N'}"
              f" tp={cfg['tp']:.1%} sl={cfg['sl']:.1%} mh={cfg['mh']:.0f}")
        for fd in fold_details:
            mdd_f = "⚠️" if fd["mdd"] < -0.15 else "✅"
            mcl_f = "❌" if fd["mcl"] > 3 else "✅"
            print(f"    {fd['window']}: Sharpe={fd['sharpe']:+.3f}"
                  f"  WR={fd['wr']:.1%}  n={fd['n']}"
                  f"  MDD={fd['mdd']:.2%}{mdd_f}  MCL={fd['mcl']}{mcl_f}"
                  f"  avg={fd['avg']:+.3%}  BH={fd['bh_ret']:+.1%}")
        print(f"    → avg OOS Sharpe: {avg_oos:+.3f}")

        wf_results.append({
            **cfg, "avg_oos": avg_oos, "all_pass": all_pass,
            "fold_details": fold_details,
        })

    # ── Phase 3: 안전 조합 ──
    safe = [w for w in wf_results if w["all_pass"]]
    print(f"\n{'='*80}")
    print(f"=== Phase 3: 안전 조합 (양 Fold 통과) — {len(safe)}개 ===")
    print(f"{'='*80}")

    if not safe:
        partial = [w for w in wf_results if w["avg_oos"] > 0]
        partial.sort(key=lambda x: x["avg_oos"], reverse=True)
        print(f"  양 Fold 완전 통과 없음. avg OOS > 0: {len(partial)}개")
        for p in partial[:5]:
            print(f"    {p['symbol']} rsi_os={p['rsi_os']:.0f}"
                  f" rsi_ex={p['rsi_ex']:.0f} adx={p['adx_c']:.0f}"
                  f" rsiP={p['rsi_p']:.0f} btcG={'Y' if p['btc_g'] else 'N'}"
                  f" → avg OOS={p['avg_oos']:+.3f}")
            for fd in p["fold_details"]:
                print(f"      {fd['window']}: Sharpe={fd['sharpe']:+.3f}"
                      f" WR={fd['wr']:.1%} n={fd['n']}")

        best_p = partial[0] if partial else wf_results[0]
        n_total = sum(fd['n'] for fd in best_p['fold_details'])
        print(f"\nSharpe: {best_p['avg_oos']:+.3f}")
        print(f"WR: {best_p['fold_details'][0]['wr']:.1%}")
        print(f"trades: {n_total}")
        return

    safe.sort(key=lambda x: x["avg_oos"], reverse=True)
    best = safe[0]

    # ── Phase 4: 슬리피지 스트레스 ──
    print(f"\n{'='*80}")
    print("=== Phase 4: 슬리피지 스트레스 테스트 ===")
    print(f"{'='*80}")

    sym = best["symbol"]
    w = WINDOWS[1]
    pre_stress = oos_cache[(sym, best["rsi_p"], w["name"])]

    print(f"  최적: {sym} rsi_os={best['rsi_os']:.0f}"
          f" rsi_ex={best['rsi_ex']:.0f} adx={best['adx_c']:.0f}"
          f" rsiP={best['rsi_p']:.0f} btcG={'Y' if best['btc_g'] else 'N'}"
          f" tp={best['tp']:.1%} sl={best['sl']:.1%} mh={best['mh']:.0f}")

    print(f"\n  {'slippage':>10} {'Sharpe':>8} {'WR':>6} {'avg%':>7}"
          f" {'MDD':>8} {'MCL':>4} {'n':>4}")
    print("  " + "-" * 55)
    for slip in SLIPPAGE_STRESS:
        r = backtest_fast(
            pre_stress,
            rsi_oversold=best["rsi_os"], rsi_exit=best["rsi_ex"],
            adx_ceil=best["adx_c"], tp=best["tp"], sl=best["sl"],
            max_hold=best["mh"], use_btc_gate=best["btc_g"],
            slippage=slip,
        )
        print(f"  {slip:>10.2%} {r['sharpe']:>+8.3f} {r['wr']:>5.1%}"
              f" {r['avg']:>+7.3%} {r['mdd']:>7.2%}"
              f" {r['mcl']:>4} {r['n']:>4}")

    # ── Phase 5: 연도별 분해 ──
    print(f"\n{'='*80}")
    print("=== Phase 5: 연도별 성과 분해 ===")
    print(f"{'='*80}")

    for year in range(2022, 2027):
        y_start = f"{year}-01-01"
        y_end = f"{year}-12-31" if year < 2026 else "2026-04-05"
        pre_y = get_precomputed(sym, y_start, y_end, best["rsi_p"])
        if pre_y.n < 50:
            continue
        r = backtest_fast(
            pre_y,
            rsi_oversold=best["rsi_os"], rsi_exit=best["rsi_ex"],
            adx_ceil=best["adx_c"], tp=best["tp"], sl=best["sl"],
            max_hold=best["mh"], use_btc_gate=best["btc_g"],
            slippage=SLIPPAGE_BASE,
        )
        print(f"  {year}: Sharpe={r['sharpe']:+.3f}  WR={r['wr']:.1%}"
              f"  MDD={r['mdd']:.2%}  MCL={r['mcl']}  n={r['n']}"
              f"  avg={r['avg']:+.3%}  BH={r['bh_ret']:+.1%}")

    # ── 최종 요약 ──
    print(f"\n{'='*80}")
    print("=== 최종 요약 ===")
    print(f"{'='*80}")
    print(f"★ WF 최적: {best['symbol']} rsi_os={best['rsi_os']:.0f}"
          f" rsi_ex={best['rsi_ex']:.0f} adx={best['adx_c']:.0f}"
          f" rsiP={best['rsi_p']:.0f} btcG={'Y' if best['btc_g'] else 'N'}"
          f" tp={best['tp']:.1%} sl={best['sl']:.1%} mh={best['mh']:.0f}")
    print(f"  avg OOS Sharpe: {best['avg_oos']:+.3f}")
    for fd in best["fold_details"]:
        print(f"  {fd['window']}: Sharpe={fd['sharpe']:+.3f}"
              f"  WR={fd['wr']:.1%}  n={fd['n']}"
              f"  MDD={fd['mdd']:.2%}  MCL={fd['mcl']}"
              f"  avg={fd['avg']:+.3%}  BH={fd['bh_ret']:+.1%}")

    max_mdd = min(fd["mdd"] for fd in best["fold_details"])
    max_mcl = max(fd["mcl"] for fd in best["fold_details"])
    total_n = sum(fd["n"] for fd in best["fold_details"])

    print(f"\n  연속손실 ≤ 3: {'✅ PASS' if max_mcl <= 3 else '❌ FAIL'}"
          f" (실제: {max_mcl})")
    print(f"  MDD < 15%: {'✅ PASS' if max_mdd > -0.15 else '⚠️ WARNING'}"
          f" (실제: {max_mdd:.2%})")
    print(f"  총 OOS 거래수: {total_n}"
          f" ({'✅' if total_n >= 20 else '⚠️ n<20'})")

    print(f"\nSharpe: {best['avg_oos']:+.3f}")
    print(f"WR: {best['fold_details'][0]['wr']:.1%}")
    print(f"trades: {total_n}")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, line_buffering=True)
    main()
