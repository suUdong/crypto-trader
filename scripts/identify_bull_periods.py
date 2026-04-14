#!/usr/bin/env python3
"""
BTC 불장 구간 라벨링 — 역사적 날짜 + 자동 감지 복합 방식

Phase 1: 검증된 역사적 불장 기간 하드코딩
Phase 2: BTC > SMA200(일봉) + SMA50>SMA200 복합 자동 감지
결과: artifacts/bull_periods.json

Usage:
    .venv/bin/python3 scripts/identify_bull_periods.py
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

ARTIFACTS = _root / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUTPUT    = ARTIFACTS / "bull_periods.json"

# ── Phase 1: 역사적 불장 기간 (검증된 날짜) ───────────────────────────────────
#
# 기준: BTC 가격이 전 고점 대비 +50% 이상 상승 유지 구간
# 출처: CoinMarketCap / Glassnode 등 검증
#
HISTORICAL_BULL_PERIODS = [
    {
        "id":    "2017_bull",
        "start": "2017-01-01",
        "end":   "2017-12-17",
        "peak_price": 19_800,
        "peak_gain_pct": 9879,
        "note": "2017 대불장 — ICO 붐, 전고점 $1,200 → $19,800",
    },
    {
        "id":    "2020_2021_bull",
        "start": "2020-10-01",
        "end":   "2021-11-10",
        "peak_price": 69_000,
        "peak_gain_pct": 1614,
        "note": "2020~21 불장 — 기관 진입, 전고점 $4,000 → $69,000",
    },
    {
        "id":    "2024_2025_bull",
        "start": "2024-10-01",
        "end":   "2025-01-20",   # 1차 고점 (실제 종료는 추후 갱신)
        "peak_price": 108_000,
        "peak_gain_pct": 72,
        "note": "2024~25 불장 — ETF 승인, 반감기 효과. 현재 진행 중(조정 구간)",
        "ongoing": True,
    },
]


# ── Phase 2: 자동 감지 알고리즘 ──────────────────────────────────────────────

def sma(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full_like(series, np.nan)
    for i in range(period - 1, len(series)):
        result[i] = series[i - period + 1 : i + 1].mean()
    return result


def detect_bull_periods_auto(df: pd.DataFrame) -> list[dict]:
    """
    복합 자동 감지:
      조건 A: BTC 종가 > SMA1200 (4h 기준 ≈ 일봉 SMA200)
      조건 B: SMA300 > SMA1200  (4h 기준 ≈ 일봉 SMA50 > SMA200 골든크로스)
      확정: A AND B 가 3봉(12h) 이상 연속 유지

    반환: [{"start": ..., "end": ..., "duration_days": ...}, ...]
    """
    closes = df["close"].values.astype(float)
    dates  = df.index

    # SMA 계산 (4h 봉 기준)
    SMA_SLOW  = 1200   # ≈ 일봉 SMA200  (200일 × 6봉/일)
    SMA_MED   = 300    # ≈ 일봉 SMA50   (50일  × 6봉/일)
    CONFIRM_BARS = 3   # 12h 연속 확인

    sma_slow = sma(closes, SMA_SLOW)
    sma_med  = sma(closes, SMA_MED)

    bull_flag = np.zeros(len(closes), dtype=bool)
    for i in range(SMA_SLOW, len(closes)):
        if closes[i] > sma_slow[i] and sma_med[i] > sma_slow[i]:
            bull_flag[i] = True

    # CONFIRM_BARS 연속 충족 시에만 불장으로 인정
    confirmed = np.zeros(len(closes), dtype=bool)
    for i in range(CONFIRM_BARS - 1, len(closes)):
        if bull_flag[i - CONFIRM_BARS + 1 : i + 1].all():
            confirmed[i] = True

    # 연속 구간 추출
    periods = []
    in_bull  = False
    start_i  = 0
    for i in range(len(confirmed)):
        if confirmed[i] and not in_bull:
            in_bull  = True
            start_i  = i
        elif not confirmed[i] and in_bull:
            in_bull  = False
            end_i    = i - 1
            dur_days = (end_i - start_i) * 4 / 24
            if dur_days >= 7:   # 최소 7일 이상인 구간만
                periods.append({
                    "start":         str(dates[start_i].date()),
                    "end":           str(dates[end_i].date()),
                    "duration_days": round(dur_days, 1),
                    "entry_price":   float(closes[start_i]),
                    "peak_price":    float(closes[start_i:end_i+1].max()),
                })

    if in_bull:  # 현재도 불장 중
        end_i    = len(closes) - 1
        dur_days = (end_i - start_i) * 4 / 24
        periods.append({
            "start":         str(dates[start_i].date()),
            "end":           "ongoing",
            "duration_days": round(dur_days, 1),
            "entry_price":   float(closes[start_i]),
            "peak_price":    float(closes[start_i:].max()),
            "ongoing":       True,
        })

    return periods


# ── BTC 데이터 fetch ──────────────────────────────────────────────────────────

def fetch_btc_long(interval: str = "minute240", count: int = 2500) -> pd.DataFrame | None:
    """
    Upbit API는 한 번에 최대 200봉.
    count > 200 이면 여러 번 나눠서 fetch 후 concat.
    """
    try:
        import pyupbit

        dfs = []
        remaining = count
        to_param  = None   # None = 최신부터

        while remaining > 0:
            fetch_n = min(200, remaining)
            kwargs  = dict(interval=interval, count=fetch_n)
            if to_param:
                kwargs["to"] = to_param

            df = pyupbit.get_ohlcv("KRW-BTC", **kwargs)
            if df is None or df.empty:
                break

            dfs.append(df)
            remaining -= len(df)
            to_param   = str(df.index[0])    # 다음 fetch는 이보다 이전 데이터
            time.sleep(0.3)

        if not dfs:
            return None

        combined = pd.concat(dfs[::-1])        # 오래된 것 앞으로
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
        return combined

    except Exception as e:
        print(f"  Fetch error: {e}")
        return None


# ── 일봉 fetch (긴 역사용) ────────────────────────────────────────────────────

def fetch_btc_daily(count: int = 2000) -> pd.DataFrame | None:
    """
    일봉 BTC 데이터 fetch. 200봉/요청 × n회.
    count=2000 → ~5.5년 (2020~2026)
    """
    return fetch_btc_long(interval="day", count=count)


def detect_bull_periods_daily(df: pd.DataFrame) -> list[dict]:
    """
    일봉 기준 자동 감지 — 훨씬 안정적.
      조건 A: BTC > SMA200 (일봉)
      조건 B: SMA50 > SMA200 (골든크로스)
      확정: A AND B 가 3일 이상 연속
    """
    closes = df["close"].values.astype(float)
    dates  = df.index

    SMA_SLOW     = 200
    SMA_MED      = 50
    CONFIRM_DAYS = 3
    MIN_DAYS     = 14

    if len(closes) < SMA_SLOW:
        return []

    sma_slow = sma(closes, SMA_SLOW)
    sma_med  = sma(closes, SMA_MED)

    bull_flag = np.zeros(len(closes), dtype=bool)
    for i in range(SMA_SLOW, len(closes)):
        if closes[i] > sma_slow[i] and sma_med[i] > sma_slow[i]:
            bull_flag[i] = True

    confirmed = np.zeros(len(closes), dtype=bool)
    for i in range(CONFIRM_DAYS - 1, len(closes)):
        if bull_flag[i - CONFIRM_DAYS + 1 : i + 1].all():
            confirmed[i] = True

    periods = []
    in_bull = False
    start_i = 0
    for i in range(len(confirmed)):
        if confirmed[i] and not in_bull:
            in_bull = True
            start_i = i
        elif not confirmed[i] and in_bull:
            in_bull = False
            end_i = i - 1
            dur = end_i - start_i
            if dur >= MIN_DAYS:
                periods.append({
                    "start":         str(dates[start_i].date()),
                    "end":           str(dates[end_i].date()),
                    "duration_days": dur,
                    "entry_price":   float(closes[start_i]),
                    "peak_price":    float(closes[start_i:end_i+1].max()),
                    "gain_pct":      round((closes[start_i:end_i+1].max() / closes[start_i] - 1) * 100, 1),
                })

    if in_bull:
        end_i = len(closes) - 1
        dur = end_i - start_i
        periods.append({
            "start":         str(dates[start_i].date()),
            "end":           "ongoing",
            "duration_days": dur,
            "entry_price":   float(closes[start_i]),
            "peak_price":    float(closes[start_i:].max()),
            "gain_pct":      round((closes[start_i:].max() / closes[start_i] - 1) * 100, 1),
            "ongoing":       True,
        })

    return periods


# ── 불장 구간 검증 (역사적 날짜 vs 실제 가격) ────────────────────────────────

def validate_historical(df: pd.DataFrame) -> list[dict]:
    """역사적 불장 기간의 실제 수익률/최대 낙폭 측정."""
    validated = []
    for p in HISTORICAL_BULL_PERIODS:
        entry = {**p}

        start_dt = pd.Timestamp(p["start"])
        end_dt   = pd.Timestamp(p["end"])

        # 데이터 범위 내에 있는 구간만
        df_slice = df[(df.index >= start_dt) & (df.index <= end_dt)]
        if df_slice.empty:
            entry["data_available"] = False
            validated.append(entry)
            continue

        entry_price = float(df_slice["close"].iloc[0])
        peak_price  = float(df_slice["close"].max())
        exit_price  = float(df_slice["close"].iloc[-1])
        max_dd_pct  = float(
            ((df_slice["close"] - df_slice["close"].cummax()) / df_slice["close"].cummax()).min() * 100
        )
        actual_gain = (peak_price / entry_price - 1) * 100

        entry["data_available"]   = True
        entry["actual_entry_price"] = entry_price
        entry["actual_peak_price"]  = peak_price
        entry["actual_exit_price"]  = exit_price
        entry["actual_gain_pct"]    = round(actual_gain, 1)
        entry["max_drawdown_pct"]   = round(max_dd_pct, 1)
        entry["n_bars_4h"]          = len(df_slice)
        validated.append(entry)

    return validated


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  BTC 불장 구간 라벨링")
    print("  일봉(역사) + 4h봉(최근) 병행")
    print("=" * 60)

    # ── 일봉 데이터 fetch (~5.5년) ──────────────────────────────────────────
    print("\n[1/4] 일봉 fetch (~2000봉 ≈ 5.5년)...")
    df_daily = fetch_btc_daily(count=2000)
    if df_daily is not None:
        print(f"  OK: {len(df_daily)}일 | {df_daily.index[0].date()} ~ {df_daily.index[-1].date()}")
    else:
        print("  WARNING: 일봉 fetch 실패")

    # ── 4h봉 데이터 fetch (~400일) ──────────────────────────────────────────
    print("\n[2/4] 4h봉 fetch (~2500봉 ≈ 400일)...")
    df_4h = fetch_btc_long(count=2500)
    if df_4h is not None:
        print(f"  OK: {len(df_4h)}봉 | {df_4h.index[0].date()} ~ {df_4h.index[-1].date()}")
    else:
        print("  WARNING: 4h봉 fetch 실패")

    if df_daily is None and df_4h is None:
        print("ERROR: 데이터 없음")
        return

    # Phase 1: 역사적 날짜 검증 (일봉 우선, 없으면 4h)
    print("\n[3/4] Phase 1 — 역사적 불장 기간 검증...")
    df_for_hist = df_daily if df_daily is not None else df_4h
    validated = validate_historical(df_for_hist)
    for p in validated:
        avail = p.get("data_available", False)
        if avail:
            src = "일봉" if df_daily is not None else "4h봉"
            print(f"  [{src}] {p['id']:<22} {p['start']} ~ {p['end']}")
            print(f"    entry: ₩{p['actual_entry_price']:>12,.0f}  "
                  f"peak: ₩{p['actual_peak_price']:>12,.0f}  "
                  f"gain: {p['actual_gain_pct']:>+.1f}%  "
                  f"max_dd: {p['max_drawdown_pct']:.1f}%")
        else:
            print(f"  {p['id']:<22} → 데이터 범위 밖")

    # Phase 2: 자동 감지 (일봉 + 4h봉 둘 다)
    print("\n[4/4] Phase 2 — 자동 감지...")
    daily_auto = []
    h4_auto    = []

    if df_daily is not None and len(df_daily) >= 200:
        print("  [일봉] BTC > SMA200 AND SMA50 > SMA200 (골든크로스)")
        daily_auto = detect_bull_periods_daily(df_daily)
        for p in daily_auto:
            end_label = p['end'] if p['end'] != "ongoing" else "진행 중"
            print(f"    {p['start']} ~ {end_label}  "
                  f"({p['duration_days']}일)  "
                  f"entry=₩{p['entry_price']:>12,.0f}  "
                  f"+{p['gain_pct']:.1f}%")
        if not daily_auto:
            print("    감지 없음")

    if df_4h is not None and len(df_4h) >= 1200:
        print("  [4h봉] BTC > SMA1200 AND SMA300 > SMA1200")
        h4_auto = detect_bull_periods_auto(df_4h)
        for p in h4_auto:
            end_label = p['end'] if p['end'] != "ongoing" else "진행 중"
            print(f"    {p['start']} ~ {end_label}  "
                  f"({p['duration_days']:.0f}일)  "
                  f"entry=₩{p['entry_price']:>12,.0f}")
        if not h4_auto:
            print("    감지 없음")

    # 저장
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "data_range_daily": {
            "start": str(df_daily.index[0].date()) if df_daily is not None else None,
            "end":   str(df_daily.index[-1].date()) if df_daily is not None else None,
            "n_bars": len(df_daily) if df_daily is not None else 0,
        },
        "data_range_4h": {
            "start": str(df_4h.index[0].date()) if df_4h is not None else None,
            "end":   str(df_4h.index[-1].date()) if df_4h is not None else None,
            "n_bars": len(df_4h) if df_4h is not None else 0,
        },
        "phase1_historical": validated,
        "phase2_daily_auto": daily_auto,
        "phase2_4h_auto":    h4_auto,
        "note": (
            "phase1: 역사적 날짜 검증 (백테스트 기준). "
            "phase2_daily: 일봉 SMA50>SMA200 자동 감지 (신뢰도 높음). "
            "phase2_4h: 4h봉 SMA300>SMA1200 자동 감지 (세밀하지만 노이즈 있음)."
        ),
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n저장 완료 → {OUTPUT.relative_to(_root)}")

    # 핵심 결론 요약
    print("\n" + "=" * 60)
    print("  핵심 결론")
    print("=" * 60)
    data_periods = [p for p in validated if p.get("data_available")]
    if data_periods:
        print("  역사적 불장 검증:")
        for p in data_periods:
            print(f"    {p['id']}: {p.get('actual_gain_pct', '?'):>+.1f}% gain  "
                  f"max_dd {p.get('max_drawdown_pct', '?'):.1f}%")
    if daily_auto:
        print(f"\n  일봉 자동 감지: {len(daily_auto)}개 불장 구간")
        for p in daily_auto:
            print(f"    {p['start']} ~ {p['end']} ({p['duration_days']}일, +{p['gain_pct']:.1f}%)")
    if h4_auto:
        print(f"\n  4h봉 자동 감지: {len(h4_auto)}개 불장 구간")


if __name__ == "__main__":
    main()
