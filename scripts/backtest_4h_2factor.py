"""
2-Factor 백테스트: BTC 레짐(SMA20) + 알트 4h stealth_3gate
- Gate 1: BTC close > SMA20 (regime)
- Gate 2: BTC stealth (12봉 수익 < 0 AND btc_acc > 1.0)
- Alt filter: RS ∈ [0.7, 1.0) AND alt_acc > 1.0

데이터: data/historical/monthly/240m/ + day/
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

START = "2022-01-01"
END   = "2026-12-31"
W     = 12  # 12봉 룩백

TP_LIST = [0.05, 0.10, 0.15, 0.20]
SL_LIST = [0.03, 0.05, 0.08]


# ── 지표 계산 ─────────────────────────────────────────────────────────────────

def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def rolling_mean(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def compute_btc_features(df_btc_4h: pd.DataFrame, df_btc_day: pd.DataFrame) -> pd.Series:
    """BTC regime + stealth 신호 (4h index 기준)."""
    # ── BTC day regime: close > SMA20(일봉) ──────────────────────────────────
    day_sma20 = sma(df_btc_day["close"], 20).rename("sma20")
    regime_day = (df_btc_day["close"] > day_sma20).rename("regime")

    # 4h index에 맞춰 forward-fill (일봉 → 4h)
    combined_idx = df_btc_4h.index.union(regime_day.index)
    regime_4h = regime_day.reindex(combined_idx).ffill().reindex(df_btc_4h.index).fillna(False)

    # ── BTC stealth (4h): 12봉 수익 < 0 AND acc > 1.0 ────────────────────────
    btc_c = df_btc_4h["close"]
    btc_v = df_btc_4h["volume"]
    btc_ret12 = btc_c / btc_c.shift(W)
    btc_close_ma = rolling_mean(btc_c, W)
    btc_vol_ma   = rolling_mean(btc_v, W)
    btc_acc = (btc_c / btc_close_ma.replace(0, np.nan)) * (btc_v / btc_vol_ma.replace(0, np.nan))
    btc_stealth = (btc_ret12 < 1.0) & (btc_acc > 1.0)

    # regime AND stealth 둘 다 on
    signal = regime_4h & btc_stealth
    return signal


def compute_alt_features(df_alt: pd.DataFrame, df_btc: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Alt RS + acc 계산."""
    # 공통 인덱스
    idx = df_alt.index.intersection(df_btc.index)
    alt_c = df_alt["close"].reindex(idx)
    alt_v = df_alt["volume"].reindex(idx)
    btc_c = df_btc["close"].reindex(idx)

    ret_alt = alt_c / alt_c.shift(W)
    ret_btc = btc_c / btc_c.shift(W)
    rs = (ret_alt / ret_btc.replace(0, np.nan)).reindex(df_alt.index)

    close_ma = rolling_mean(alt_c, W)
    vol_ma   = rolling_mean(alt_v, W)
    acc = ((alt_c / close_ma.replace(0, np.nan)) * (alt_v / vol_ma.replace(0, np.nan))).reindex(df_alt.index)

    return rs, acc


def backtest_symbol(
    market: str,
    df_alt: pd.DataFrame,
    btc_signal: pd.Series,
    df_btc_4h: pd.DataFrame,
    tp: float,
    sl: float,
) -> list[float]:
    """단일 심볼 백테스트. 수익률 리스트 반환."""
    rs, acc = compute_alt_features(df_alt, df_btc_4h)

    # stealth_3gate: btc_signal + alt RS/acc 필터
    entry = (
        btc_signal.reindex(df_alt.index).fillna(False)
        & (rs >= 0.7) & (rs < 1.0)
        & (acc > 1.0)
    )

    closes = df_alt["close"].values
    entry_arr = entry.values
    returns: list[float] = []

    i = 0
    while i < len(closes) - 1:
        if entry_arr[i]:
            buy_price = closes[i + 1]  # 다음봉 시가 대신 종가로 진입
            for j in range(i + 1, min(i + 200, len(closes))):
                ret = closes[j] / buy_price - 1
                if ret >= tp:
                    returns.append(tp)
                    i = j
                    break
                if ret <= -sl:
                    returns.append(-sl)
                    i = j
                    break
            else:
                returns.append(closes[min(i + 200, len(closes) - 1)] / buy_price - 1)
                i += 200
        else:
            i += 1

    return returns


def sharpe(rets: list[float]) -> float:
    if len(rets) < 3:
        return float("nan")
    arr = np.array(rets)
    return float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252))


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=== 4h 2-Factor 백테스트 ===")
    print(f"기간: {START} ~ {END}")

    # BTC 로드
    print("\nBTC 데이터 로드 중...")
    df_btc_4h  = load_historical("KRW-BTC", "240m", START, END)
    df_btc_day = load_historical("KRW-BTC", "day",  START, END)
    print(f"  BTC 4h: {len(df_btc_4h)}행  |  BTC day: {len(df_btc_day)}행")

    if df_btc_4h.empty or df_btc_day.empty:
        print("BTC 데이터 없음. 다운로드 완료 후 재실행하세요.")
        return

    # BTC signal 한 번만 계산
    btc_signal = compute_btc_features(df_btc_4h, df_btc_day)
    signal_rate = btc_signal.mean()
    print(f"  BTC signal 발동률: {signal_rate:.1%}")

    # 알트 목록: 240m 데이터 있는 KRW 마켓
    alt_dir = Path(__file__).resolve().parent.parent / "data/historical/monthly/240m/2024"
    markets = sorted({p.name.split("_")[0] for p in alt_dir.glob("KRW-*.zip")
                      if not p.name.startswith("KRW-BTC")})
    print(f"\n대상 알트: {len(markets)}개")

    results: list[dict] = []
    for tp in TP_LIST:
        for sl in SL_LIST:
            all_rets: list[float] = []
            n_sym = 0
            for mkt in markets:
                try:
                    df_alt = load_historical(mkt, "240m", START, END)
                    if len(df_alt) < 100:
                        continue
                    rets = backtest_symbol(mkt, df_alt, btc_signal, df_btc_4h, tp, sl)
                    if rets:
                        all_rets.extend(rets)
                        n_sym += 1
                except Exception:
                    continue

            s = sharpe(all_rets)
            wr = float(np.mean([r > 0 for r in all_rets])) if all_rets else 0.0
            avg_r = float(np.mean(all_rets)) if all_rets else 0.0
            results.append({"tp": tp, "sl": sl, "sharpe": s, "wr": wr, "avg_ret": avg_r,
                             "n_trades": len(all_rets), "n_sym": n_sym})
            print(f"  TP={tp:.0%} SL={sl:.0%}  Sharpe={s:+.3f}  WR={wr:.1%}  "
                  f"avg={avg_r:+.2%}  trades={len(all_rets)}  syms={n_sym}")

    # 정렬 및 결론
    results.sort(key=lambda x: x["sharpe"] if not np.isnan(x["sharpe"]) else -99, reverse=True)
    best = results[0]
    print(f"\n최적: TP={best['tp']:.0%} / SL={best['sl']:.0%}  "
          f"Sharpe={best['sharpe']:+.3f}  WR={best['wr']:.1%}  avg={best['avg_ret']:+.2%}")

    # backtest_history.md 기록
    _record_history(results[:5], best)


def _record_history(top5: list[dict], best: dict) -> None:
    from datetime import datetime, timezone
    hist = Path(__file__).resolve().parent.parent / "docs/backtest_history.md"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = "\n".join(
        f"| {r['tp']:.0%} | {r['sl']:.0%} | {r['sharpe']:+.3f} | {r['wr']:.1%} | "
        f"{r['avg_ret']:+.2%} | {r['n_trades']} | {r['n_sym']} |"
        for r in top5
    )
    entry = f"""
## {ts} — BTC 레짐(SMA20) + 알트 4h stealth_3gate 2-Factor 백테스트

### 설정
- BTC 레짐: 4h close, day SMA20 (forward-fill)
- BTC stealth: 12봉 수익 < 0 AND btc_acc > 1.0
- Alt 필터: RS ∈ [0.7, 1.0) AND acc > 1.0
- 기간: 2022~2026, KRW 전체 알트

### 결과 Top-5 (Sharpe 기준)

| TP | SL | Sharpe | WinRate | AvgRet | Trades | Syms |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
{rows}

### 결론
- **최적**: TP={best['tp']:.0%} / SL={best['sl']:.0%}  Sharpe={best['sharpe']:+.3f}  WR={best['wr']:.1%}
"""
    with open(hist, "a") as f:
        f.write(entry)
    print(f"\ndocs/backtest_history.md 기록 완료")


if __name__ == "__main__":
    main()
