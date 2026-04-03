"""
stealth_3gate Gate 4 (btc_trend_pos) 활성화 전체 백테스트
- 최적 파라미터 고정: W=36, SMA20, RS[0.5,1.0), TP=15%, SL=3%
- btc_trend_pos_gate = False vs True 비교
- btc_trend_window = 10 (사이클 94-96 검증 값)

목적: Gate 4 활성화 시 전체 Sharpe 5.0 달성 여부 확인 → daemon 반영 경로
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

START = "2022-01-01"
END   = "2026-12-31"

# 고정 파라미터 (사이클 97 이전 최적 확정)
W      = 36     # BTC stealth 룩백 (4h 봉)
SMA_N  = 20     # BTC 레짐 기준 일봉 SMA
RS_LO  = 0.5   # alt RS 하한
RS_HI  = 1.0   # alt RS 상한
TP     = 0.15   # take profit
SL     = 0.03   # stop loss

BTC_TREND_WINDOW = 10  # Gate 4: BTC 10봉 수익률 > 0


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def btc_signal(df4h: pd.DataFrame, dfday: pd.DataFrame) -> pd.Series:
    """Gate 1+2: BTC 레짐 + BTC stealth"""
    day_sma = sma(dfday["close"], SMA_N)
    regime = dfday["close"] > day_sma
    idx = df4h.index.union(regime.index)
    reg4h = regime.reindex(idx).ffill().reindex(df4h.index).fillna(False)

    c = df4h["close"]
    v = df4h["volume"]
    ret_w = c / c.shift(W)
    c_ma  = c.rolling(W, min_periods=W).mean()
    v_ma  = v.rolling(W, min_periods=W).mean()
    acc   = (c / c_ma.replace(0, np.nan)) * (v / v_ma.replace(0, np.nan))
    stealth = (ret_w < 1.0) & (acc > 1.0)
    return reg4h & stealth


def btc_trend_pos_series(df4h: pd.DataFrame) -> pd.Series:
    """Gate 4: BTC 최근 10봉 수익률 > 0"""
    c = df4h["close"]
    trend = c > c.shift(BTC_TREND_WINDOW)
    return trend.fillna(False)


def alt_rs_acc(df_alt: pd.DataFrame, df_btc: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Gate 3: alt RS + acc"""
    idx = df_alt.index.intersection(df_btc.index)
    ac, vc = df_alt["close"].reindex(idx), df_alt["volume"].reindex(idx)
    bc = df_btc["close"].reindex(idx)
    rs = (ac / ac.shift(W)) / (bc / bc.shift(W)).replace(0, np.nan)
    c_ma = ac.rolling(W, min_periods=W).mean()
    v_ma = vc.rolling(W, min_periods=W).mean()
    acc  = (ac / c_ma.replace(0, np.nan)) * (vc / v_ma.replace(0, np.nan))
    return rs.reindex(df_alt.index), acc.reindex(df_alt.index)


def run_symbol(closes: np.ndarray, entry_arr: np.ndarray) -> list[float]:
    rets = []
    i = 0
    while i < len(closes) - 1:
        if entry_arr[i]:
            bp = closes[i + 1]
            for j in range(i + 1, min(i + 200, len(closes))):
                r = closes[j] / bp - 1
                if r >= TP:
                    rets.append(TP)
                    i = j
                    break
                if r <= -SL:
                    rets.append(-SL)
                    i = j
                    break
            else:
                rets.append(closes[min(i + 200, len(closes) - 1)] / bp - 1)
                i += 200
        else:
            i += 1
    return rets


def sharpe(rets: list[float]) -> float:
    if len(rets) < 3:
        return float("nan")
    a = np.array(rets)
    return float(a.mean() / (a.std() + 1e-9) * np.sqrt(252))


def run_backtest(
    alt_data: dict[str, pd.DataFrame],
    btc_sig: pd.Series,
    btc_trend: pd.Series | None,
    df_btc4h: pd.DataFrame,
) -> dict:
    all_rets: list[float] = []
    sym_results: dict[str, dict] = {}

    for mkt, df_alt in alt_data.items():
        try:
            rs, acc = alt_rs_acc(df_alt, df_btc4h)
            entry = (
                btc_sig.reindex(df_alt.index).fillna(False)
                & (rs >= RS_LO) & (rs < RS_HI)
                & (acc > 1.0)
            )
            if btc_trend is not None:
                entry = entry & btc_trend.reindex(df_alt.index).fillna(False)

            rets = run_symbol(df_alt["close"].values, entry.values)
            if rets:
                all_rets.extend(rets)
                sym_results[mkt] = {
                    "n": len(rets),
                    "wr": float(np.mean([r > 0 for r in rets])),
                    "avg": float(np.mean(rets)),
                    "sharpe": sharpe(rets),
                }
        except Exception:
            continue

    s  = sharpe(all_rets)
    wr = float(np.mean([r > 0 for r in all_rets])) if all_rets else 0.0
    ar = float(np.mean(all_rets)) if all_rets else 0.0
    return {
        "sharpe": s,
        "wr": wr,
        "avg_ret": ar,
        "n_trades": len(all_rets),
        "n_sym": len(sym_results),
        "sym_results": sym_results,
    }


def main() -> None:
    print("=== stealth_3gate Gate 4 (btc_trend_pos) 전체 백테스트 ===")
    print(f"기간: {START} ~ {END}")
    print(f"파라미터: W={W}, SMA{SMA_N}, RS[{RS_LO},{RS_HI}), TP={TP:.0%}, SL={SL:.0%}")
    print(f"Gate 4: btc_trend_window={BTC_TREND_WINDOW} (BTC 10봉 수익률 > 0)\n")

    # 데이터 로드
    print("BTC 데이터 로드...")
    df_btc4h  = load_historical("KRW-BTC", "240m", START, END)
    df_btcday = load_historical("KRW-BTC", "day",  START, END)
    print(f"  BTC 4h: {len(df_btc4h)}행 | BTC day: {len(df_btcday)}행\n")

    alt_dir = Path(__file__).resolve().parent.parent / "data/historical/monthly/240m/2022"
    markets = sorted({p.name.split("_")[0] for p in alt_dir.glob("KRW-*.zip")
                      if not p.name.startswith("KRW-BTC")})

    print(f"알트 데이터 로드 ({len(markets)}개 후보)...")
    alt_data: dict[str, pd.DataFrame] = {}
    for mkt in markets:
        df = load_historical(mkt, "240m", START, END)
        if df is not None and len(df) >= W + 200:
            alt_data[mkt] = df
    print(f"  유효 알트: {len(alt_data)}개\n")

    # 신호 계산
    btc_sig   = btc_signal(df_btc4h, df_btcday)
    btc_trend = btc_trend_pos_series(df_btc4h)

    # 베이스라인 (Gate 4 없음)
    print("--- 베이스라인 (Gate 1+2+3 only) ---")
    base = run_backtest(alt_data, btc_sig, None, df_btc4h)
    print(f"Sharpe={base['sharpe']:+.3f} | WR={base['wr']:.1%} | avg={base['avg_ret']:+.2%} "
          f"| trades={base['n_trades']} | syms={base['n_sym']}")

    # Gate 4 활성화
    print("\n--- Gate 4 활성화 (btc_trend_pos=True) ---")
    gate4 = run_backtest(alt_data, btc_sig, btc_trend, df_btc4h)
    print(f"Sharpe={gate4['sharpe']:+.3f} | WR={gate4['wr']:.1%} | avg={gate4['avg_ret']:+.2%} "
          f"| trades={gate4['n_trades']} | syms={gate4['n_sym']}")

    delta = gate4["sharpe"] - base["sharpe"]
    print(f"\nΔSharpe = {delta:+.3f} | trades 감소 = {base['n_trades'] - gate4['n_trades']}"
          f" ({(1 - gate4['n_trades'] / max(base['n_trades'], 1)):.0%})")

    # 심볼별 상위 기여 (Gate 4 기준)
    print("\n--- Gate 4 심볼별 Top-10 (Sharpe 기준) ---")
    sym_sorted = sorted(gate4["sym_results"].items(),
                        key=lambda x: x[1]["sharpe"] if not np.isnan(x[1]["sharpe"]) else -99,
                        reverse=True)
    for sym, r in sym_sorted[:10]:
        print(f"  {sym:<14} Sharpe={r['sharpe']:+.3f} WR={r['wr']:.0%} avg={r['avg']:+.2%} n={r['n']}")

    # 결과 평가
    print("\n=== 평가 ===")
    if gate4["sharpe"] >= 5.0:
        print(f"✅ Sharpe {gate4['sharpe']:+.3f} ≥ 5.0 → daemon 반영 기준 충족!")
    elif gate4["sharpe"] >= 4.5:
        print(f"◆ Sharpe {gate4['sharpe']:+.3f} (기준 5.0 미달, 추가 최적화 필요)")
    else:
        print(f"❌ Sharpe {gate4['sharpe']:+.3f} < 4.5 → daemon 반영 보류")

    # docs/backtest_history.md 기록
    _record(base, gate4, delta)
    print("\n완료 → docs/backtest_history.md 업데이트됨")


def _record(base: dict, gate4: dict, delta: float) -> None:
    hist = Path(__file__).resolve().parent.parent / "docs/backtest_history.md"
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verdict = (
        "✅ Sharpe ≥ 5.0 — daemon 반영 기준 충족" if gate4["sharpe"] >= 5.0
        else "◆ Sharpe 4.5~5.0 — 추가 최적화 필요" if gate4["sharpe"] >= 4.5
        else "❌ Sharpe < 4.5 — daemon 반영 보류"
    )
    entry = f"""
## {ts} — stealth_3gate Gate 4 (btc_trend_pos) 전체 백테스트 (사이클 98)

### 설정
- 고정 파라미터: W=36, SMA20, RS[0.5,1.0), TP=15%, SL=3%
- Gate 4: btc_trend_window=10 (BTC 10봉 수익률 > 0)
- 기간: 2022~2026, KRW 알트 전체

### 결과

| 조합 | Sharpe | WR | avg | trades | syms |
|---|:---:|:---:|:---:|:---:|:---:|
| 베이스라인 (Gate 1+2+3) | {base['sharpe']:+.3f} | {base['wr']:.1%} | {base['avg_ret']:+.2%} | {base['n_trades']} | {base['n_sym']} |
| **Gate 4 활성화** | **{gate4['sharpe']:+.3f}** | **{gate4['wr']:.1%}** | **{gate4['avg_ret']:+.2%}** | **{gate4['n_trades']}** | **{gate4['n_sym']}** |

ΔSharpe = {delta:+.3f}

### 판정
{verdict}

"""
    with open(hist, "a") as f:
        f.write(entry)


if __name__ == "__main__":
    main()
