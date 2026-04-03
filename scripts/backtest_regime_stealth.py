#!/usr/bin/env python3
"""
C 단계: BTC 레짐 + 알트 Stealth 2-Factor 전략 백테스트

비교 실험:
  A) Stealth only      — 레짐 무시, stealth 발동 시 진입
  B) Regime only       — BTC 불장 구간 내내 보유
  C) Regime + Stealth  — 불장 확인 후 stealth 진입 (2-factor)
  D) Buy & Hold        — 전 구간 보유 기준선

결과: 각 조합의 Sharpe / 승률 / avg_ret / max_drawdown 비교
      TP/SL 그리드 탐색으로 최적 파라미터 도출

Usage:
    .venv/bin/python3 scripts/backtest_regime_stealth.py
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime, UTC
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

ARTIFACTS = _root / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# ── 파라미터 ──────────────────────────────────────────────────────────────────

SYMBOLS     = [
    "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-DOGE",
    "KRW-AVAX", "KRW-DOT", "KRW-LINK", "KRW-MATIC", "KRW-ATOM",
    "KRW-LTC", "KRW-BCH", "KRW-ETC", "KRW-TRX", "KRW-NEAR",
    "KRW-SUI", "KRW-APT", "KRW-OP", "KRW-ARB", "KRW-SAND",
    "KRW-MANA", "KRW-AXS", "KRW-CHZ", "KRW-HBAR", "KRW-STX",
]

ALT_INTERVAL   = "day"         # 일봉 (~5.5년 커버)
ALT_COUNT      = 2000          # ~5.5년
BTC_INTERVAL   = "day"         # 일봉 (레짐)
BTC_COUNT      = 3200          # ~8.7년

STEALTH_LB     = 14            # stealth lookback (14일)
STEALTH_RECENT = 7             # CVD 최근 창
REGIME_MA      = 100           # BTC > SMA100 = 불장

FEE_RATE       = 0.0005        # 0.05% 편도

# 그리드 탐색 파라미터
TP_LIST = [0.05, 0.10, 0.15, 0.20]
SL_LIST = [0.03, 0.05, 0.08]

MIN_TRADES = 3  # 최소 거래수 미만이면 결과 제외


# ── 데이터 fetch ──────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval: str, count: int,
                sleep_s: float = 0.3) -> pd.DataFrame | None:
    try:
        import pyupbit
        dfs, remaining, to_param = [], count, None
        while remaining > 0:
            n  = min(200, remaining)
            kw = dict(interval=interval, count=n)
            if to_param:
                kw["to"] = to_param
            df = pyupbit.get_ohlcv(symbol, **kw)
            if df is None or df.empty:
                break
            dfs.append(df)
            remaining -= len(df)
            to_param   = str(df.index[0])
            time.sleep(sleep_s)
        if not dfs:
            return None
        combined = pd.concat(dfs[::-1])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
        return combined
    except Exception as e:
        print(f"  fetch error {symbol}: {e}")
        return None


# ── BTC 레짐 ─────────────────────────────────────────────────────────────────

def compute_regime(btc_daily: pd.DataFrame) -> pd.Series:
    """
    BTC 일봉 close > SMA100 → 불장(True), 그 외 → 횡보/하락(False)
    SMA50>SMA200 golden cross보다 빠른 반응.
    """
    c   = btc_daily["close"]
    ma  = c.rolling(REGIME_MA).mean()
    regime = (c > ma).rename("btc_regime")
    return regime


def align_regime_to_alt(regime: pd.Series,
                         alt_index: pd.DatetimeIndex) -> np.ndarray:
    """
    일봉 레짐을 4h 알트 인덱스에 forward-fill 맞춤.
    """
    regime_utc = regime.copy()
    if regime_utc.index.tz is not None:
        regime_utc.index = regime_utc.index.tz_convert("UTC")
    else:
        regime_utc.index = regime_utc.index.tz_localize("UTC")

    alt_utc = alt_index
    if alt_utc.tz is None:
        alt_utc = alt_utc.tz_localize("UTC")

    aligned = regime_utc.reindex(alt_utc, method="ffill").fillna(False)
    return aligned.values.astype(bool)


# ── Stealth 신호 ──────────────────────────────────────────────────────────────

def compute_stealth(df: pd.DataFrame) -> np.ndarray:
    """
    알트 4h 봉 기준 stealth 발동 bool 배열.
    조건: net_ret<1 + acc>1 + CVD slope>0
    """
    c = df["close"].values.astype(float)
    v = df["volume"].values.astype(float)
    o = df["open"].values.astype(float)
    n = len(c)
    lb = STEALTH_LB
    rw = STEALTH_RECENT

    stealth = np.zeros(n, dtype=bool)
    for i in range(lb + rw, n):
        if c[i] / c[i - lb] >= 1.0:
            continue
        close_ma = c[i - lb:i].mean()
        vol_ma   = v[i - lb:i].mean() + 1e-9
        acc      = (c[i] / close_ma) * (v[i] / vol_ma)
        if acc <= 1.0:
            continue
        dirn      = np.where(c[i - lb:i] >= o[i - lb:i], 1.0, -1.0)
        cvd       = (v[i - lb:i] * dirn).cumsum()
        if cvd[-1] - cvd[-rw] <= 0:
            continue
        stealth[i] = True
    return stealth


# ── 백테스트 엔진 ─────────────────────────────────────────────────────────────

@dataclass
class TradeResult:
    ret: float      # 순수익률 (수수료 제외)
    win: bool


def backtest_trades(c: np.ndarray, signal: np.ndarray,
                    tp: float, sl: float) -> list[TradeResult]:
    """
    signal[i]=True 시 c[i] 진입, TP/SL 도달 또는 다음 신호까지 청산.
    """
    n      = len(c)
    trades = []
    in_pos = False
    entry  = 0.0

    for i in range(n):
        if in_pos:
            ret_raw = c[i] / entry - 1.0
            if ret_raw >= tp or ret_raw <= -sl or signal[i]:
                net = ret_raw - FEE_RATE * 2
                trades.append(TradeResult(net, net > 0))
                in_pos = False
                if not signal[i]:
                    continue
        if signal[i] and not in_pos:
            entry  = c[i]
            in_pos = True

    # 미청산 포지션
    if in_pos:
        net = (c[-1] / entry - 1.0) - FEE_RATE * 2
        trades.append(TradeResult(net, net > 0))

    return trades


def metrics(trades: list[TradeResult]) -> dict:
    if len(trades) < MIN_TRADES:
        return {}
    rets  = np.array([t.ret for t in trades])
    sigma = rets.std()
    sharpe = (rets.mean() / sigma * np.sqrt(252)) if sigma > 0.01 else 0.0
    return {
        "n":          len(trades),
        "win_rate":   float((rets > 0).mean() * 100),
        "avg_ret":    float(rets.mean() * 100),
        "sharpe":     float(sharpe),
        "max_dd":     float(_max_drawdown(rets) * 100),
    }


def _max_drawdown(rets: np.ndarray) -> float:
    equity = (1 + rets).cumprod()
    peak   = np.maximum.accumulate(equity)
    dd     = (equity - peak) / peak
    return float(dd.min())


# ── 메인 실험 ─────────────────────────────────────────────────────────────────

def run_symbol(symbol: str, btc_regime_daily: pd.Series,
               tp: float, sl: float) -> dict | None:
    df = fetch_ohlcv(symbol, ALT_INTERVAL, ALT_COUNT)
    if df is None or len(df) < STEALTH_LB + STEALTH_RECENT + 50:
        return None

    c       = df["close"].values.astype(float)
    stealth = compute_stealth(df)
    regime  = align_regime_to_alt(btc_regime_daily, df.index)

    # 4가지 조합
    sig_stealth_only  = stealth
    sig_regime_only   = regime
    sig_combined      = stealth & regime
    # buy & hold: 첫 봉 진입 → 마지막 봉 청산
    bh_ret = (c[-1] / c[0] - 1.0) - FEE_RATE * 2

    results = {}
    for name, sig in [
        ("stealth_only", sig_stealth_only),
        ("regime_only",  sig_regime_only),
        ("combined",     sig_combined),
    ]:
        trades = backtest_trades(c, sig, tp, sl)
        m = metrics(trades)
        if m:
            results[name] = m

    results["buy_hold"] = {"ret_pct": float(bh_ret * 100)}
    return results


def main():
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*65}")
    print(f"  BTC 레짐 + 알트 Stealth 2-Factor 백테스트  |  {now_str}")
    print(f"{'='*65}")

    # BTC 일봉 fetch & 레짐 계산
    print(f"\n[1/3] BTC 일봉 fetch & 레짐 계산 (SMA{REGIME_MA})...")
    btc = fetch_ohlcv("KRW-BTC", BTC_INTERVAL, BTC_COUNT, sleep_s=0.3)
    if btc is None:
        print("  ERROR: BTC 데이터 fetch 실패")
        return
    regime_series = compute_regime(btc)
    bull_pct = regime_series.sum() / len(regime_series) * 100
    print(f"  OK: {len(btc)}봉 | 불장 비율 {bull_pct:.1f}%")

    # 그리드 탐색
    print(f"\n[2/3] 그리드 탐색 (TP×SL: {len(TP_LIST)}×{len(SL_LIST)}={len(TP_LIST)*len(SL_LIST)}조합)")
    print(f"      알트 {len(SYMBOLS)}종목 × 각 조합...")

    best: dict[str, dict] = {}   # key: (tp, sl) → aggregated metrics

    for tp, sl in product(TP_LIST, SL_LIST):
        key = f"tp{int(tp*100)}_sl{int(sl*100)}"
        agg: dict[str, list] = {
            "stealth_only": [], "regime_only": [], "combined": []
        }

        for sym in SYMBOLS:
            res = run_symbol(sym, regime_series, tp, sl)
            if res is None:
                continue
            for mode in agg:
                if mode in res:
                    agg[mode].append(res[mode])

        summary: dict[str, dict] = {}
        for mode, items in agg.items():
            if not items:
                continue
            summary[mode] = {
                "n_symbols": len(items),
                "avg_sharpe":   float(np.mean([x["sharpe"]   for x in items])),
                "avg_win_rate": float(np.mean([x["win_rate"] for x in items])),
                "avg_ret":      float(np.mean([x["avg_ret"]  for x in items])),
                "avg_trades":   float(np.mean([x["n"]        for x in items])),
            }
        best[key] = {"tp": tp, "sl": sl, "summary": summary}
        _print_grid_row(tp, sl, summary)

    # 최적 조합 도출
    print(f"\n[3/3] 최적 파라미터 (combined Sharpe 기준)")
    print(f"  {'TP':>5} {'SL':>5}  {'Sharpe':>8} {'WinRate':>9} {'AvgRet':>8} {'nSym':>6}")
    print("  " + "─" * 46)

    ranked = sorted(
        [(k, v) for k, v in best.items() if "combined" in v.get("summary", {})],
        key=lambda x: x[1]["summary"]["combined"]["avg_sharpe"],
        reverse=True,
    )
    for k, v in ranked[:5]:
        s = v["summary"]["combined"]
        print(f"  {v['tp']*100:>4.0f}%  {v['sl']*100:>4.0f}%  "
              f"{s['avg_sharpe']:>8.3f}  {s['avg_win_rate']:>8.1f}%  "
              f"{s['avg_ret']:>7.2f}%  {s['n_symbols']:>5}")

    # 결과 저장
    import json
    out = ARTIFACTS / "regime_stealth_backtest.json"
    with open(out, "w") as f:
        json.dump({"generated_at": now_str, "grid": best}, f,
                  indent=2, ensure_ascii=False)

    _append_history(now_str, ranked)
    print(f"\n결과 저장: artifacts/regime_stealth_backtest.json")


def _print_grid_row(tp: float, sl: float, summary: dict):
    parts = []
    for mode in ("stealth_only", "combined"):
        if mode in summary:
            s = summary[mode]
            parts.append(f"{mode[:7]} Sh={s['avg_sharpe']:+.2f} WR={s['avg_win_rate']:.0f}%")
    if parts:
        print(f"  TP={tp*100:.0f}% SL={sl*100:.0f}%  |  " + "  |  ".join(parts))


def _append_history(now_str: str, ranked: list):
    hist = _root / "docs" / "backtest_history.md"
    if not ranked:
        return
    best_k, best_v = ranked[0]
    s = best_v["summary"].get("combined", {})
    if not s:
        return

    lines = [
        f"\n## {now_str} — BTC 레짐 + Stealth 2-Factor 백테스트\n\n",
        f"| 조합 | avg_sharpe | win_rate | avg_ret | n_symbols |\n",
        f"|---|:---:|:---:|:---:|:---:|\n",
    ]
    for _, v in ranked[:5]:
        s2 = v["summary"].get("combined", {})
        if s2:
            lines.append(
                f"| TP={v['tp']*100:.0f}%/SL={v['sl']*100:.0f}% | "
                f"{s2['avg_sharpe']:+.3f} | {s2['avg_win_rate']:.1f}% | "
                f"{s2['avg_ret']:+.2f}% | {s2['n_symbols']} |\n"
            )
    lines.append(
        f"\n**최적**: TP={best_v['tp']*100:.0f}% / SL={best_v['sl']*100:.0f}%  "
        f"Sharpe={s['avg_sharpe']:+.3f}  WR={s['avg_win_rate']:.1f}%\n"
    )

    # stealth only vs combined 비교
    stealth_sharpes = [v["summary"]["stealth_only"]["avg_sharpe"]
                       for _, v in ranked if "stealth_only" in v.get("summary", {})]
    if stealth_sharpes:
        best_stealth = max(stealth_sharpes)
        lines.append(
            f"\n**레짐 필터 효과**: combined {s['avg_sharpe']:+.3f} "
            f"vs stealth_only {best_stealth:+.3f}\n"
        )

    if hist.exists():
        with open(hist, "a") as f:
            f.writelines(lines)


if __name__ == "__main__":
    main()
