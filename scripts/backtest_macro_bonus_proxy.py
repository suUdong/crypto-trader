#!/usr/bin/env python3
"""
Macro Bonus Proxy 백테스트 (사이클 94)

CLAUDE.md TODO:
  macro_bonus = vix_falling(+0.2) + dxy_falling(+0.1) + expansionary(+0.3)
  pre_bull_score_adjusted = pre_bull_score + macro_bonus

역사적 데이터로 macro_bonus 효과를 검증하기 위해 BTC OHLCV 기반 proxy 사용:
  - vix_proxy_falling : BTC 20봉 realized vol < 40봉 realized vol (변동성 압축)
  - btc_trend_pos     : BTC 10봉 수익률 > 0 (DXY 약세 proxy — BTC/USD 역상관)
  - expansionary      : N>=8 연속 SMA20 위 유지 (기존 필터에 이미 내포)

테스트 조합:
  A) N=12 단독 (사이클 93 기준선)
  B) N=8  + vix_falling
  C) N=8  + btc_trend_pos
  D) N=8  + vix_falling + btc_trend_pos  (full macro_bonus proxy)
  E) N=12 + vix_falling
  F) N=12 + btc_trend_pos
  G) N=12 + vix_falling + btc_trend_pos  (full macro_bonus proxy)

Usage:
    .venv/bin/python3 scripts/backtest_macro_bonus_proxy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))

from historical_loader import load_historical  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────
CTYPE = "240m"          # 4h 캔들
START = "2022-01-01"
END   = "2026-04-03"
SMA_WINDOW = 20

LOOKBACK = 12
RECENT_W = 4
ALT_SYMBOLS = ["KRW-SOL", "KRW-ETH", "KRW-XRP", "KRW-TRX"]

TP_SL = {
    "KRW-SOL": (0.12, 0.04),
    "KRW-ETH": (0.10, 0.03),
    "KRW-XRP": (0.12, 0.04),
    "KRW-TRX": (0.12, 0.03),
}

FORWARD_BARS_STEALTH = 24  # 최대 보유봉 (96h)

# macro_bonus proxy 파라미터
VOL_SHORT = 20    # realized vol 단기 윈도우 (봉)
VOL_LONG  = 40    # realized vol 장기 윈도우 (봉)
TREND_W   = 10    # BTC trend 윈도우 (봉)


# ── Macro Proxy 계산 ──────────────────────────────────────────────────────────

def compute_macro_proxy(btc: pd.DataFrame) -> pd.DataFrame:
    """
    BTC OHLCV로 macro_bonus proxy 계산.
    Returns DataFrame with columns: vix_falling, btc_trend_pos, macro_score
    """
    close = btc["close"]
    log_ret = np.log(close / close.shift(1))

    # vix_proxy_falling: 단기 realized vol < 장기 realized vol (변동성 압축)
    vol_short = log_ret.rolling(VOL_SHORT).std()
    vol_long  = log_ret.rolling(VOL_LONG).std()
    vix_falling = (vol_short < vol_long).astype(float)

    # btc_trend_pos: BTC 10봉 수익률 > 0 (DXY 약세 proxy)
    trend_ret = close / close.shift(TREND_W) - 1.0
    btc_trend_pos = (trend_ret > 0).astype(float)

    # macro_score proxy (CLAUDE.md 가중치 적용)
    macro_score = vix_falling * 0.2 + btc_trend_pos * 0.1

    btc["vix_falling"]    = vix_falling
    btc["btc_trend_pos"]  = btc_trend_pos
    btc["macro_score"]    = macro_score
    return btc


# ── Helpers (v2와 동일) ────────────────────────────────────────────────────────

def compute_alt_stealth(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    btc_idx: int,
    lb: int = LOOKBACK,
    rw: int = RECENT_W,
    rs_window: int = 20,
) -> bool:
    if btc_idx < max(lb + rw, rs_window):
        return False
    btc_ts = btc_df.index[btc_idx]
    if btc_ts not in alt_df.index:
        return False
    alt_idx = alt_df.index.get_loc(btc_ts)
    if not isinstance(alt_idx, int):
        alt_idx = int(alt_idx)
    if alt_idx < max(lb + rw, rs_window):
        return False

    win = alt_df.iloc[alt_idx - lb: alt_idx]
    btc_win = btc_df.iloc[btc_idx - lb: btc_idx]
    if len(win) < lb or len(btc_win) < lb:
        return False

    c = win["close"].values
    o = win["open"].values
    h = win["high"].values
    lv = win["low"].values
    v = win["volume"].values

    raw_ret = float(c[-1]) / max(float(c[0]), 1e-9) - 1.0
    rng = np.clip(h - lv, 1e-9, None)
    vpin = np.abs(c - o) / rng
    acc = vpin[-rw:].mean() / max(vpin[:-rw].mean(), 1e-9)
    sign_vol = np.where(c >= o, v, -v)
    cvd_slope = float(np.sum(sign_vol[-rw:])) / max(abs(float(np.sum(sign_vol))), 1e-9)

    rs_win_alt = alt_df.iloc[alt_idx - rs_window: alt_idx]["close"].values
    rs_win_btc = btc_df.iloc[btc_idx - rs_window: btc_idx]["close"].values
    alt_chg = float(rs_win_alt[-1]) / max(float(rs_win_alt[0]), 1e-9) - 1.0
    btc_chg = float(rs_win_btc[-1]) / max(float(rs_win_btc[0]), 1e-9) - 1.0
    rs = (1.0 + alt_chg) / max(1.0 + btc_chg, 1e-9) if btc_chg > -1 else 0.0

    return bool((raw_ret < 0.0) and (acc > 1.0) and (cvd_slope > 0.0) and (0.5 <= rs < 1.0))


def sim_tp_sl(
    df: pd.DataFrame,
    entry_idx: int,
    tp: float,
    sl: float,
    max_bars: int = 24,
) -> tuple[float, str]:
    if entry_idx >= len(df) - 1:
        return 0.0, "expired"
    entry_price = df["close"].iloc[entry_idx]
    tp_price = entry_price * (1 + tp)
    sl_price = entry_price * (1 - sl)
    for i in range(entry_idx + 1, min(entry_idx + max_bars + 1, len(df))):
        if df["low"].iloc[i] <= sl_price:
            return -sl, "sl"
        if df["high"].iloc[i] >= tp_price:
            return tp, "tp"
    final_price = df["close"].iloc[min(entry_idx + max_bars, len(df) - 1)]
    return final_price / entry_price - 1.0, "expired"


def run_stealth_backtest(
    btc: pd.DataFrame,
    alt_data: dict[str, pd.DataFrame],
    events: list[int],
    label: str,
) -> dict:
    """이벤트당 심볼당 1회 진입 (v2 방식)."""
    results: dict[str, list[float]] = {sym: [] for sym in ALT_SYMBOLS}
    exits: dict[str, dict[str, int]] = {sym: {"tp": 0, "sl": 0, "expired": 0} for sym in ALT_SYMBOLS}

    for trans_idx in events:
        entered_syms: set[str] = set()

        for fwd in range(0, 7):
            check_idx = trans_idx + fwd
            if check_idx >= len(btc):
                break
            if len(entered_syms) == len(ALT_SYMBOLS):
                break

            for sym in ALT_SYMBOLS:
                if sym in entered_syms:
                    continue

                adf = alt_data[sym]
                btc_ts = btc.index[check_idx]
                if btc_ts not in adf.index:
                    continue
                alt_idx = adf.index.get_loc(btc_ts)
                if not isinstance(alt_idx, int):
                    alt_idx = int(alt_idx)

                if not compute_alt_stealth(adf, btc, check_idx):
                    continue

                tp, sl = TP_SL[sym]
                ret, exit_type = sim_tp_sl(adf, alt_idx, tp=tp, sl=sl, max_bars=FORWARD_BARS_STEALTH)
                results[sym].append(ret)
                exits[sym][exit_type] += 1
                entered_syms.add(sym)

    all_rets: list[float] = []
    sym_stats = {}
    for sym in ALT_SYMBOLS:
        rets = results[sym]
        if not rets:
            sym_stats[sym] = {"n": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0}
            continue
        wr = sum(1 for r in rets if r > 0) / len(rets)
        avg = float(np.mean(rets))
        std = float(np.std(rets)) if len(rets) > 1 else 0.0
        sh = avg / std if std > 0 else 0.0
        sym_stats[sym] = {
            "n": len(rets), "wr": wr, "avg": avg, "sharpe": sh,
            "tp": exits[sym]["tp"], "sl": exits[sym]["sl"], "exp": exits[sym]["expired"],
        }
        all_rets.extend(rets)

    total_stats: dict = {}
    if all_rets:
        wr = sum(1 for r in all_rets if r > 0) / len(all_rets)
        avg = float(np.mean(all_rets))
        std = float(np.std(all_rets)) if len(all_rets) > 1 else 0.0
        sh = avg / std if std > 0 else 0.0
        total_stats = {"n": len(all_rets), "wr": wr, "avg": avg, "sharpe": sh}

    return {"label": label, "events": len(events), "sym_stats": sym_stats, "total": total_stats}


def print_result(r: dict) -> None:
    label = r["label"]
    n_ev = r["events"]
    print(f"\n--- {label} (이벤트 {n_ev}개) ---")
    print(f"{'심볼':12s} {'진입수':>6} {'WR%':>6} {'avg_ret':>8} {'Sharpe':>7}")
    print("-" * 48)
    for sym in ALT_SYMBOLS:
        s = r["sym_stats"].get(sym, {})
        if not s or s.get("n", 0) == 0:
            print(f"{sym:12s} {'0':>6}")
            continue
        print(
            f"{sym:12s} {s['n']:>6} {s['wr']*100:>5.1f}% "
            f"{s['avg']*100:>+7.2f}% {s['sharpe']:>+7.2f}"
        )
    if r["total"]:
        t = r["total"]
        print("-" * 48)
        print(
            f"{'TOTAL':12s} {t['n']:>6} {t['wr']*100:>5.1f}% "
            f"{t['avg']*100:>+7.2f}% {t['sharpe']:>+8.2f}"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("[사이클 94] Macro Bonus Proxy 백테스트")
    print("VIX proxy (BTC vol 압축) + DXY proxy (BTC 추세) 복합 필터 효과 검증")
    print("=" * 70)

    print(f"\nLoading BTC {CTYPE} data ({START} ~ {END})...")
    btc = load_historical("KRW-BTC", CTYPE, START, END)
    btc = compute_macro_proxy(btc)
    print(f"BTC rows: {len(btc)}")

    print("Loading alt data...")
    alt_data: dict[str, pd.DataFrame] = {}
    for sym in ALT_SYMBOLS:
        df = load_historical(sym, CTYPE, START, END)
        alt_data[sym] = df
        print(f"  {sym}: {len(df)} rows")

    # BTC SMA20
    btc["sma20"] = btc["close"].rolling(SMA_WINDOW).mean()
    btc["above_sma"] = btc["close"] > btc["sma20"]

    min_idx = max(SMA_WINDOW, VOL_LONG, TREND_W) + LOOKBACK + RECENT_W + 12 + 5

    # 기준선: SMA20 최초 돌파 이벤트
    raw_transitions: list[int] = []
    for i in range(min_idx, len(btc) - 12 - 30):
        if not btc["above_sma"].iloc[i - 1] and btc["above_sma"].iloc[i]:
            raw_transitions.append(i)

    print(f"\n원본 SMA20 돌파 이벤트: {len(raw_transitions)}개")

    # ── 필터 이벤트 생성 ──────────────────────────────────────────────────────
    def get_n_filtered(n: int) -> list[int]:
        out = []
        for idx in raw_transitions:
            if idx + n >= len(btc):
                continue
            if all(btc["above_sma"].iloc[idx + k] for k in range(1, n + 1)):
                out.append(idx)
        return out

    def apply_macro_filter(events: list[int], use_vix: bool, use_trend: bool) -> list[int]:
        out = []
        for idx in events:
            if use_vix and btc["vix_falling"].iloc[idx] < 0.5:
                continue
            if use_trend and btc["btc_trend_pos"].iloc[idx] < 0.5:
                continue
            out.append(idx)
        return out

    n8_events  = get_n_filtered(8)
    n12_events = get_n_filtered(12)

    print(f"N=8  이벤트: {len(n8_events)}개")
    print(f"N=12 이벤트: {len(n12_events)}개")

    # 복합 필터 조합 생성
    combos: list[tuple[str, list[int]]] = [
        ("N=12 단독 (사이클93 기준선)",         n12_events),
        ("N=8  + vix_falling",                  apply_macro_filter(n8_events,  True,  False)),
        ("N=8  + btc_trend_pos",                apply_macro_filter(n8_events,  False, True)),
        ("N=8  + vix+trend (full macro_bonus)", apply_macro_filter(n8_events,  True,  True)),
        ("N=12 + vix_falling",                  apply_macro_filter(n12_events, True,  False)),
        ("N=12 + btc_trend_pos",                apply_macro_filter(n12_events, False, True)),
        ("N=12 + vix+trend (full macro_bonus)", apply_macro_filter(n12_events, True,  True)),
    ]

    print("\n=== 복합 필터 이벤트 수 요약 ===")
    for label, evts in combos:
        print(f"  {label:42s}: {len(evts):>4}개")

    # ── 백테스트 실행 ─────────────────────────────────────────────────────────
    print("\n=== 복합 필터별 stealth_3gate 성과 ===")
    all_results = []
    for label, evts in combos:
        r = run_stealth_backtest(btc, alt_data, evts, label)
        print_result(r)
        all_results.append(r)

    # ── 최종 요약 표 ──────────────────────────────────────────────────────────
    print("\n" + "=" * 85)
    print("최종 요약: macro_bonus proxy 복합 필터 비교")
    print("=" * 85)
    print(f"{'필터':42s} {'이벤트':>6} {'진입':>5} {'WR%':>6} {'avg_ret':>8} {'Sharpe':>8}")
    print("-" * 85)
    for r in all_results:
        t = r.get("total", {})
        if not t:
            print(f"{r['label']:42s} {r['events']:>6} {'(없음)':>5}")
            continue
        marker = " ★" if t["sharpe"] == max(
            rr["total"]["sharpe"] for rr in all_results if rr.get("total")
        ) else ""
        print(
            f"{r['label']:42s} {r['events']:>6} {t['n']:>5} "
            f"{t['wr']*100:>5.1f}% {t['avg']*100:>+7.2f}% {t['sharpe']:>+8.2f}{marker}"
        )

    # ── 매크로 보너스 현재 상태 ────────────────────────────────────────────────
    last_vix  = float(btc["vix_falling"].iloc[-1])
    last_trnd = float(btc["btc_trend_pos"].iloc[-1])
    last_mac  = float(btc["macro_score"].iloc[-1])
    print(f"\n=== 현재 시장 macro_bonus proxy 상태 ===")
    print(f"  vix_falling  : {last_vix:.0f}  (+0.2 가산)")
    print(f"  btc_trend_pos: {last_trnd:.0f}  (+0.1 가산)")
    print(f"  macro_score  : {last_mac:.2f}")
    print(f"  (현재 pre_bull=+0.673 → macro_bonus 포함 시: {0.673 + last_mac:.3f})")


if __name__ == "__main__":
    main()
