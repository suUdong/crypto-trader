"""
stealth_3gate 파라미터 그리드 탐색
- W: BTC stealth 룩백 윈도우 (4h 봉 수)
- RS 범위: alt relative strength 필터
- SMA: BTC 레짐 기준 (일봉 SMA)
데이터: data/historical/monthly (2022~2026)
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

# 그리드 파라미터
W_LIST      = [6, 9, 12, 18, 24]       # BTC stealth 룩백
SMA_LIST    = [20, 50]                  # BTC 레짐 SMA
RS_LOW_LIST = [0.5, 0.7, 0.8]          # alt RS 하한
RS_HI_LIST  = [1.0, 1.2]               # alt RS 상한 (1.0 = BTC 미만, 1.2 = 약간 강한 것도)
TP          = 0.15                      # 최적 TP (이전 백테스트 결과)
SL          = 0.03                      # 최적 SL


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def btc_signal(df4h: pd.DataFrame, dfday: pd.DataFrame, W: int, sma_n: int) -> pd.Series:
    day_sma = sma(dfday["close"], sma_n)
    regime  = dfday["close"] > day_sma
    idx     = df4h.index.union(regime.index)
    reg4h   = regime.reindex(idx).ffill().reindex(df4h.index).fillna(False)

    c = df4h["close"]
    v = df4h["volume"]
    ret_w    = c / c.shift(W)
    c_ma     = c.rolling(W, min_periods=W).mean()
    v_ma     = v.rolling(W, min_periods=W).mean()
    acc      = (c / c_ma.replace(0, np.nan)) * (v / v_ma.replace(0, np.nan))
    stealth  = (ret_w < 1.0) & (acc > 1.0)
    return reg4h & stealth


def alt_rs_acc(df_alt: pd.DataFrame, df_btc: pd.DataFrame, W: int) -> tuple[pd.Series, pd.Series]:
    idx    = df_alt.index.intersection(df_btc.index)
    ac, vc = df_alt["close"].reindex(idx), df_alt["volume"].reindex(idx)
    bc     = df_btc["close"].reindex(idx)
    rs     = (ac / ac.shift(W)) / (bc / bc.shift(W)).replace(0, np.nan)
    c_ma   = ac.rolling(W, min_periods=W).mean()
    v_ma   = vc.rolling(W, min_periods=W).mean()
    acc    = (ac / c_ma.replace(0, np.nan)) * (vc / v_ma.replace(0, np.nan))
    return rs.reindex(df_alt.index), acc.reindex(df_alt.index)


def run_symbol(closes, entry_arr, tp, sl):
    rets = []
    i = 0
    while i < len(closes) - 1:
        if entry_arr[i]:
            bp = closes[i + 1]
            for j in range(i + 1, min(i + 200, len(closes))):
                r = closes[j] / bp - 1
                if r >= tp:   rets.append(tp);  i = j; break
                if r <= -sl:  rets.append(-sl); i = j; break
            else:
                rets.append(closes[min(i+200, len(closes)-1)] / bp - 1)
                i += 200
        else:
            i += 1
    return rets


def sharpe(rets):
    if len(rets) < 3: return float("nan")
    a = np.array(rets)
    return float(a.mean() / (a.std() + 1e-9) * np.sqrt(252))


def main():
    print("=== stealth_3gate 파라미터 그리드 탐색 ===")
    print(f"기간: {START} ~ {END} | TP={TP:.0%} SL={SL:.0%}")

    print("\nBTC 데이터 로드...")
    df_btc4h  = load_historical("KRW-BTC", "240m", START, END)
    df_btcday = load_historical("KRW-BTC", "day",  START, END)
    print(f"  BTC 4h: {len(df_btc4h)}행 | BTC day: {len(df_btcday)}행")

    # 알트 목록 (94개 중 BTC 제외)
    alt_dir = Path(__file__).resolve().parent.parent / "data/historical/monthly/240m/2022"
    markets = sorted({p.name.split("_")[0] for p in alt_dir.glob("KRW-*.zip")
                      if not p.name.startswith("KRW-BTC")})
    print(f"대상 알트: {len(markets)}개\n")

    # 알트 데이터 미리 로드 (공통)
    print("알트 데이터 사전 로드...")
    alt_data = {}
    for mkt in markets:
        df = load_historical(mkt, "240m", START, END)
        if len(df) >= 200:
            alt_data[mkt] = df
    print(f"  유효 알트: {len(alt_data)}개\n")

    results = []
    total = len(W_LIST) * len(SMA_LIST) * len(RS_LOW_LIST) * len(RS_HI_LIST)
    n = 0
    for W in W_LIST:
        for sma_n in SMA_LIST:
            sig = btc_signal(df_btc4h, df_btcday, W, sma_n)
            sig_rate = sig.mean()
            for rs_lo in RS_LOW_LIST:
                for rs_hi in RS_HI_LIST:
                    if rs_lo >= rs_hi:
                        continue
                    n += 1
                    all_rets, n_sym = [], 0
                    for mkt, df_alt in alt_data.items():
                        try:
                            rs, acc = alt_rs_acc(df_alt, df_btc4h, W)
                            entry = (
                                sig.reindex(df_alt.index).fillna(False)
                                & (rs >= rs_lo) & (rs < rs_hi)
                                & (acc > 1.0)
                            )
                            rets = run_symbol(df_alt["close"].values, entry.values, TP, SL)
                            if rets:
                                all_rets.extend(rets)
                                n_sym += 1
                        except Exception:
                            continue
                    s  = sharpe(all_rets)
                    wr = float(np.mean([r > 0 for r in all_rets])) if all_rets else 0.0
                    ar = float(np.mean(all_rets)) if all_rets else 0.0
                    results.append({
                        "W": W, "sma": sma_n, "rs_lo": rs_lo, "rs_hi": rs_hi,
                        "sharpe": s, "wr": wr, "avg_ret": ar,
                        "n_trades": len(all_rets), "n_sym": n_sym, "sig_rate": sig_rate,
                    })
                    print(f"[{n:2d}/{total}] W={W:2d} SMA{sma_n} RS[{rs_lo},{rs_hi}) "
                          f"→ Sharpe={s:+.3f} WR={wr:.1%} avg={ar:+.2%} "
                          f"trades={len(all_rets)} sig={sig_rate:.1%}")

    # 결과 정렬
    results.sort(key=lambda x: x["sharpe"] if not np.isnan(x["sharpe"]) else -99, reverse=True)
    print("\n=== TOP 10 (Sharpe 기준) ===")
    print(f"{'W':>3} {'SMA':>4} {'RS범위':>12} {'Sharpe':>8} {'WR':>7} {'avg':>8} {'trades':>7} {'syms':>5}")
    for r in results[:10]:
        print(f"W={r['W']:2d} SMA{r['sma']:2d} [{r['rs_lo']:.1f},{r['rs_hi']:.1f}) "
              f"Sharpe={r['sharpe']:+.3f} WR={r['wr']:.1%} avg={r['avg_ret']:+.2%} "
              f"trades={r['n_trades']:5d} syms={r['n_sym']:3d}")

    # backtest_history.md 기록
    _record(results[:10])
    print("\n완료 → docs/backtest_history.md 업데이트됨")


def _record(top10):
    from datetime import datetime, timezone
    hist = Path(__file__).resolve().parent.parent / "docs/backtest_history.md"
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = "\n".join(
        f"| W={r['W']} SMA{r['sma']} RS[{r['rs_lo']:.1f},{r['rs_hi']:.1f}) | "
        f"{r['sharpe']:+.3f} | {r['wr']:.1%} | {r['avg_ret']:+.2%} | {r['n_trades']} | {r['n_sym']} |"
        for r in top10
    )
    entry = f"""
## {ts} — stealth_3gate 파라미터 그리드 탐색 (W/SMA/RS 전체 조합)

### 설정
- TP=15%, SL=3% (이전 최적 고정)
- W: {W_LIST} (4h 봉 룩백)
- SMA: {SMA_LIST} (BTC 레짐 일봉 SMA)
- RS lo: {RS_LOW_LIST}, RS hi: {RS_HI_LIST}
- 기간: 2022~2026, KRW 알트 전체 (히스토리 데이터)

### 결과 Top-10 (Sharpe 기준)

| 파라미터 | Sharpe | WinRate | AvgRet | Trades | Syms |
|---|:---:|:---:|:---:|:---:|:---:|
{rows}

"""
    with open(hist, "a") as f:
        f.write(entry)


if __name__ == "__main__":
    main()

# ── W=30, W=36 추가 탐색용 진입점 ─────────────────────────────────────────────
def main_extended():
    """W=30, W=36 탐색 (기존 최적 파라미터 고정: SMA20, RS[0.5,1.0), TP15% SL3%)"""
    import sys
    global W_LIST, SMA_LIST, RS_LOW_LIST, RS_HI_LIST
    W_LIST      = [24, 30, 36, 48]
    SMA_LIST    = [20]
    RS_LOW_LIST = [0.5]
    RS_HI_LIST  = [1.0]
    main()

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "extended":
    main_extended()
