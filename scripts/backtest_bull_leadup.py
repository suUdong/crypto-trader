#!/usr/bin/env python3
"""
BTC Stealth 선행 신호 분석 (Plan B)

불장 시작 T=0 기준으로 T-24h, T-48h, T-72h, T-96h 시점에
BTC stealth 신호가 얼마나 발동했는지 측정.

BTC stealth 정의:
  - BTC 12봉 순수익 < 0 (price net-down in window)
  - BTC accumulation > 1.0 (vol-weighted buying)
  - BTC CVD slope > 0 (매수 압력)

결과: "불장 T-48h 전에 stealth 신호 발동률 XX%"
→ 최적 선행 진입 타이밍 도출

Usage:
    .venv/bin/python3 scripts/backtest_bull_leadup.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical

ARTIFACTS = _root / "artifacts"
BULL_JSON = ARTIFACTS / "bull_periods.json"

INTERVAL  = "day"         # 일봉
START     = "2022-01-01"  # historical data 시작
END       = "2026-12-31"
LOOKBACK  = 14            # stealth window (14일)
LEAD_BARS = [7, 14, 21, 30]   # 선행 측정 시점: 1주, 2주, 3주, 4주 전
RECENT_W  = 7             # CVD/acc 최근 창

# ── 데이터 fetch ──────────────────────────────────────────────────────────────

def fetch_btc_daily() -> pd.DataFrame | None:
    try:
        df = load_historical("KRW-BTC", INTERVAL, START, END)
        return df if not df.empty else None
    except Exception as e:
        print(f"  fetch error: {e}")
        return None


# ── BTC Stealth 신호 계산 ─────────────────────────────────────────────────────

def compute_btc_stealth_series(df: pd.DataFrame) -> pd.Series:
    """
    각 4h 캔들 시점의 BTC stealth 발동 여부 (bool Series).

    Stealth 조건:
      1. net_ret = close[-1] / close[-LOOKBACK] < 1.0  (순수익 음수)
      2. acc     = (close / close_ma) × (volume / vol_ma) > 1.0
      3. cvd_slope > 0  (CVD 최근 상승 중)
    """
    c = df["close"].values.astype(float)
    v = df["volume"].values.astype(float)
    o = df["open"].values.astype(float)
    n = len(c)

    stealth = np.zeros(n, dtype=bool)

    for i in range(LOOKBACK + RECENT_W, n):
        # 1. 순수익 < 0
        net_ret = c[i] / c[i - LOOKBACK]
        if net_ret >= 1.0:
            continue

        # 2. Accumulation > 1.0
        close_ma = c[i - LOOKBACK:i].mean()
        vol_ma   = v[i - LOOKBACK:i].mean() + 1e-9
        acc      = (c[i] / close_ma) * (v[i] / vol_ma)
        if acc <= 1.0:
            continue

        # 3. CVD slope > 0 (매수 압력 증가)
        dirn       = np.where(c[i - LOOKBACK:i] >= o[i - LOOKBACK:i], 1.0, -1.0)
        cvd        = (v[i - LOOKBACK:i] * dirn).cumsum()
        cvd_recent = cvd[-RECENT_W:]
        cvd_slope  = cvd_recent[-1] - cvd_recent[0]
        if cvd_slope <= 0:
            continue

        stealth[i] = True

    return pd.Series(stealth, index=df.index, name="btc_stealth")


# ── 불장 시작점 주변 분석 ─────────────────────────────────────────────────────

def analyze_leadup(df: pd.DataFrame, stealth: pd.Series,
                   bull_periods: list[dict]) -> dict:
    """
    각 불장 시작 기준으로 lead_bars 시점 전 stealth 발동률 측정.
    """
    results = {lb: {"fired": 0, "total": 0} for lb in LEAD_BARS}
    event_log = []

    for p in bull_periods:
        start_dt = pd.Timestamp(p["start"])
        if df.index.tz is not None and start_dt.tz is None:
            start_dt = start_dt.tz_localize(df.index.tz)
        elif df.index.tz is None and start_dt.tz is not None:
            start_dt = start_dt.tz_localize(None)

        # 불장 시작 인덱스 찾기 (가장 가까운 캔들)
        diffs = np.abs((df.index - start_dt).total_seconds())
        start_i = int(np.argmin(diffs))

        row = {
            "period": p["id"] if "id" in p else p["start"],
            "start":  str(df.index[start_i].date()),
            "price":  float(df["close"].iloc[start_i]),
        }

        for lb in LEAD_BARS:
            lead_i = start_i - lb
            if lead_i < 0:
                continue
            fired = bool(stealth.iloc[lead_i])
            results[lb]["total"] += 1
            if fired:
                results[lb]["fired"] += 1
            row[f"T-{lb}d"] = "✅" if fired else "❌"

        event_log.append(row)

    # 발동률 계산
    rates = {}
    for lb, cnt in results.items():
        if cnt["total"] > 0:
            rates[lb] = {
                "days_before": lb,
                "fire_rate":    cnt["fired"] / cnt["total"] * 100,
                "fired":        cnt["fired"],
                "total":        cnt["total"],
            }

    return rates, event_log


# ── 불장 내 stealth 발동 vs 일반 발동 비교 ───────────────────────────────────

def analyze_stealth_quality(df: pd.DataFrame, stealth: pd.Series,
                             bull_periods: list[dict]) -> dict:
    """
    stealth 발동 후 forward return 분석:
      - 불장 시작 직전 (T-48h 이내) 발동 신호 vs 일반 발동 신호
    """
    c    = df["close"].values.astype(float)
    idx  = df.index

    # 불장 시작 마스크
    near_bull = np.zeros(len(idx), dtype=bool)
    for p in bull_periods:
        start_dt = pd.Timestamp(p["start"])
        if idx.tz is not None and start_dt.tz is None:
            start_dt = start_dt.tz_localize(idx.tz)
        elif idx.tz is None and start_dt.tz is not None:
            start_dt = start_dt.tz_localize(None)
        diffs = np.abs((idx - start_dt).total_seconds())
        si = int(np.argmin(diffs))
        # T-14일 ~ T-1일 범위를 "불장 직전"으로 정의
        for j in range(max(0, si - LOOKBACK), si):
            near_bull[j] = True

    stealth_arr = stealth.values

    # stealth 발동 후 LOOKBACK일 forward return
    fwd_n = np.full(len(c), np.nan)
    for i in range(len(c) - LOOKBACK):
        fwd_n[i] = (c[i + LOOKBACK] / c[i] - 1) * 100

    pre_bull_rets = fwd_n[stealth_arr & near_bull & ~np.isnan(fwd_n)]
    normal_rets   = fwd_n[stealth_arr & ~near_bull & ~np.isnan(fwd_n)]

    return {
        "pre_bull": {
            "n": len(pre_bull_rets),
            "avg_ret": float(pre_bull_rets.mean()) if len(pre_bull_rets) else 0,
            "win_rate": float((pre_bull_rets > 0).mean() * 100) if len(pre_bull_rets) else 0,
        },
        "normal": {
            "n": len(normal_rets),
            "avg_ret": float(normal_rets.mean()) if len(normal_rets) else 0,
            "win_rate": float((normal_rets > 0).mean() * 100) if len(normal_rets) else 0,
        },
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*60}")
    print(f"  BTC Stealth 선행 신호 분석  |  {now_str}")
    print(f"{'='*60}")

    # 불장 기간 로드
    if not BULL_JSON.exists():
        print("bull_periods.json 없음 — identify_bull_periods.py 먼저 실행")
        return
    with open(BULL_JSON) as f:
        data = json.load(f)
    bull_periods = data.get("phase2_daily_auto", [])
    # 역사적 검증 기간도 추가 (데이터 있는 것만)
    for p in data.get("phase1_historical", []):
        if p.get("data_available"):
            bull_periods.append(p)

    print(f"\n불장 기간 {len(bull_periods)}개:")
    for p in bull_periods:
        name = p.get("id", p["start"])
        gain = p.get("gain_pct") or p.get("actual_gain_pct") or "?"
        print(f"  {name:<25} {p['start']} ~ {p['end']}  +{gain}%")

    # BTC 4h 데이터 fetch
    print(f"\n[1/3] BTC 일봉 데이터 fetch (~{COUNT}봉)...")
    df = fetch_btc_daily()
    if df is None:
        print("  ERROR: fetch 실패")
        return
    print(f"  OK: {len(df)}봉 | {df.index[0].date()} ~ {df.index[-1].date()}")

    # Stealth 신호 계산
    print("\n[2/3] BTC Stealth 신호 계산...")
    stealth = compute_btc_stealth_series(df)
    total_fires = stealth.sum()
    fire_rate   = total_fires / len(stealth) * 100
    print(f"  전체 stealth 발동: {total_fires}회 / {len(stealth)}봉 ({fire_rate:.1f}%)")

    # 선행 분석
    print("\n[3/3] 불장 시작 전 선행 발동률 분석...")
    rates, event_log = analyze_leadup(df, stealth, bull_periods)

    print(f"\n  {'Lead time':<12} {'발동률':>8} {'발동/전체':>12}")
    print("  " + "─" * 36)
    best_lb = max(rates, key=lambda k: rates[k]["fire_rate"]) if rates else None
    for lb, r in sorted(rates.items()):
        marker = " ◀ 최적" if lb == best_lb else ""
        print(f"  T-{r['days_before']:>3}d 전      {r['fire_rate']:>7.1f}%   "
              f"{r['fired']}/{r['total']}{marker}")

    # 불장 직전 stealth vs 일반 stealth 수익 비교
    print("\n  불장 직전(T-48h 이내) stealth vs 일반 stealth 수익 비교:")
    quality = analyze_stealth_quality(df, stealth, bull_periods)
    pb = quality["pre_bull"]
    nm = quality["normal"]
    print(f"  {'':20} {'avg_ret':>8} {'win_rate':>10} {'n':>6}")
    print(f"  {'불장 직전 stealth':<20} {pb['avg_ret']:>7.2f}%  {pb['win_rate']:>8.1f}%  {pb['n']:>6}")
    print(f"  {'일반 stealth':<20} {nm['avg_ret']:>7.2f}%  {nm['win_rate']:>8.1f}%  {nm['n']:>6}")

    # 이벤트별 상세 테이블
    if event_log:
        print("\n  불장 시작 시점별 stealth 발동:")
        lead_cols = [f"T-{lb}d" for lb in LEAD_BARS]
        header    = f"  {'기간':<25} {'시작일':>12} {'가격':>14}  " + "  ".join(f"{c:>6}" for c in lead_cols)
        print(header)
        print("  " + "─" * (len(header) - 2))
        for row in event_log:
            cols = "  ".join(f"{row.get(c, '-'):>6}" for c in lead_cols)
            print(f"  {row['period']:<25} {row['start']:>12} ₩{row['price']:>12,.0f}  {cols}")

    # 결론 저장
    _save_result(rates, quality, event_log, now_str)


def _save_result(rates, quality, event_log, now_str):
    result = {
        "generated_at": now_str,
        "lead_rates":   rates,
        "quality":      quality,
        "events":       event_log,
    }
    out = ARTIFACTS / "bull_leadup_analysis.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # backtest_history.md 추가
    hist = _root / "docs" / "backtest_history.md"
    if not rates:
        return
    best_lb  = max(rates, key=lambda k: rates[k]["fire_rate"])
    best_r   = rates[best_lb]
    pb       = quality["pre_bull"]
    nm       = quality["normal"]

    lines = [
        f"\n## {now_str} — BTC Stealth 선행 신호 분석\n\n",
        "### 불장 시작 전 Stealth 발동률\n\n",
        "| Lead Time | 발동률 | 발동/전체 |\n",
        "|---|:---:|:---:|\n",
    ]
    for lb, r in sorted(rates.items()):
        star = " ⭐" if lb == best_lb else ""
        lines.append(f"| T-{r['days_before']}d 전 | {r['fire_rate']:.1f}%{star} | {r['fired']}/{r['total']} |\n")

    lines += [
        f"\n**최적 선행 시점**: T-{best_r['days_before']}d 전 (발동률 {best_r['fire_rate']:.1f}%)\n\n",
        "### 불장 직전 vs 일반 Stealth 수익 비교\n\n",
        "| 구분 | avg_ret | win_rate | n |\n",
        "|---|:---:|:---:|:---:|\n",
        f"| 불장 직전 stealth | {pb['avg_ret']:+.2f}% | {pb['win_rate']:.1f}% | {pb['n']} |\n",
        f"| 일반 stealth      | {nm['avg_ret']:+.2f}% | {nm['win_rate']:.1f}% | {nm['n']} |\n",
        f"\n**결론**: 불장 직전 stealth avg_ret = {pb['avg_ret']:+.2f}% vs 일반 = {nm['avg_ret']:+.2f}%\n",
    ]

    if hist.exists():
        with open(hist, "a") as f:
            f.writelines(lines)
    print(f"\n결과 저장: artifacts/bull_leadup_analysis.json + backtest_history.md")


if __name__ == "__main__":
    main()
