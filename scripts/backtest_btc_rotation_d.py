"""
BTC Regime Rotation D — 3-gate Stealth + 고정 12봉 hold

원래 검증 조건(backtest_stealth_deep.py)과 동일:
  - 진입: 3-gate (BTC bull + BTC stealth + Alt stealth)
  - 청산: 12봉 고정 hold (48h) — acc_exit 없음
  - 예상: 승률 ~50.3% (stealth-signal-rules.md 검증값)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

INTERVAL      = "minute240"
COUNT         = 500
LOOKBACK      = 30
RECENT_W      = 6
SMA_PERIOD    = 20
HOLD_BARS     = 12   # 고정 48h hold (검증 조건과 동일)
TOP_N         = 60
FEE           = 0.0005
FETCH_SLEEP   = 0.5

ALT_RS_MIN  = 0.8
ALT_RS_MAX  = 1.0
ALT_ACC_MIN = 1.0
ALT_ACC_MAX = 1.5


def fetch(symbol: str) -> tuple[str, pd.DataFrame | None]:
    try:
        import pyupbit
        time.sleep(FETCH_SLEEP)
        df = pyupbit.get_ohlcv(symbol, interval=INTERVAL, count=COUNT)
        if df is not None and len(df) >= LOOKBACK + HOLD_BARS + 10:
            return symbol, df
        return symbol, None
    except Exception:
        return symbol, None


def compute_stealth_gpu(df: pd.DataFrame, btc_df: pd.DataFrame) -> pd.DataFrame:
    common_len = min(len(df), len(btc_df))
    df     = df.iloc[-common_len:]
    btc_df = btc_df.iloc[-common_len:]
    n = common_len - LOOKBACK
    if n <= 0:
        return pd.DataFrame()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    closes = torch.tensor(df["close"].values,     device=device, dtype=torch.float32)
    opens  = torch.tensor(df["open"].values,      device=device, dtype=torch.float32)
    highs  = torch.tensor(df["high"].values,      device=device, dtype=torch.float32)
    lows   = torch.tensor(df["low"].values,       device=device, dtype=torch.float32)
    vols   = torch.tensor(df["volume"].values,    device=device, dtype=torch.float32)
    btc_c  = torch.tensor(btc_df["close"].values, device=device, dtype=torch.float32)

    c_w   = closes.unfold(0, LOOKBACK, 1)[:n]
    o_w   = opens.unfold(0, LOOKBACK, 1)[:n]
    h_w   = highs.unfold(0, LOOKBACK, 1)[:n]
    l_w   = lows.unfold(0, LOOKBACK, 1)[:n]
    v_w   = vols.unfold(0, LOOKBACK, 1)[:n]
    btc_w = btc_c.unfold(0, LOOKBACK, 1)[:n]

    alt_ret = c_w[:, -1] / c_w[:, 0].clamp(1e-9)
    btc_ret = btc_w[:, -1] / btc_w[:, 0].clamp(1e-9)
    rs      = alt_ret / btc_ret.clamp(1e-9)
    raw_ret = alt_ret - 1.0

    rng  = (h_w - l_w).clamp(1e-9)
    vpin = (c_w - o_w).abs() / rng
    acc  = vpin[:, -RECENT_W:].mean(1) / vpin[:, :-RECENT_W].mean(1).clamp(1e-9)

    direction = torch.where(c_w >= o_w, torch.ones_like(v_w), -torch.ones_like(v_w))
    cvd = (v_w * direction).cumsum(1)
    cvd_slope = (cvd[:, -1] - cvd[:, -RECENT_W]) / v_w.mean(1).clamp(1e-9)

    return pd.DataFrame({
        "rs":        rs.cpu().numpy(),
        "raw_ret":   raw_ret.cpu().numpy(),
        "acc":       acc.cpu().numpy(),
        "cvd_slope": cvd_slope.cpu().numpy(),
    }, index=df.index[LOOKBACK:])


def is_btc_bull(btc_df: pd.DataFrame) -> pd.Series:
    closes = btc_df["close"]
    return (closes > closes.rolling(SMA_PERIOD).mean()).rename("btc_bull")


def backtest_symbol(
    symbol: str,
    df: pd.DataFrame,
    alt_sig: pd.DataFrame,
    btc_bull: pd.Series,
    btc_stealth: pd.DataFrame,
) -> list[dict]:
    common = (
        df.index
        .intersection(alt_sig.index)
        .intersection(btc_bull.index)
        .intersection(btc_stealth.index)
    )
    if len(common) < HOLD_BARS + 2:
        return []

    df2   = df.loc[common]
    alt2  = alt_sig.reindex(common)
    bull2 = btc_bull.reindex(common)
    bst2  = btc_stealth.reindex(common)

    trades = []
    # No overlapping positions: after entry, skip until exit
    skip_until = -1

    for i, ts in enumerate(common):
        if i <= skip_until:
            continue
        if i + HOLD_BARS >= len(common):
            break  # 충분한 미래 봉 없음

        ar   = alt2.loc[ts]
        bull = bull2.loc[ts]
        bs   = bst2.loc[ts]

        g1 = bool(bull)
        g2 = bool(bs["raw_ret"] < 0 and ALT_ACC_MIN <= bs["acc"] <= ALT_ACC_MAX and bs["cvd_slope"] > 0)
        g3 = bool(ALT_RS_MIN <= ar["rs"] < ALT_RS_MAX and ALT_ACC_MIN <= ar["acc"] <= ALT_ACC_MAX and ar["cvd_slope"] > 0)

        if g1 and g2 and g3:
            exit_ts    = common[i + HOLD_BARS]
            entry_price = df2.loc[ts, "close"] * (1 + FEE)
            exit_price  = df2.loc[exit_ts, "close"] * (1 - FEE)
            ret = (exit_price / entry_price - 1) * 100
            trades.append({
                "symbol":     symbol,
                "entry_ts":   ts,
                "exit_ts":    exit_ts,
                "hold_bars":  HOLD_BARS,
                "return_pct": ret,
                "rs_entry":   ar["rs"],
                "acc_entry":  ar["acc"],
                "btc_acc":    bs["acc"],
            })
            skip_until = i + HOLD_BARS  # no overlap

    return trades


def main() -> None:
    import pyupbit

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Strategy D] 3-gate Stealth + 고정 {HOLD_BARS}봉 hold (={HOLD_BARS*4}h)  [{device}]")
    print(f"Gate3: RS∈[{ALT_RS_MIN},{ALT_RS_MAX}) acc∈[{ALT_ACC_MIN},{ALT_ACC_MAX}]")
    print()

    print("Fetching BTC...", end=" ", flush=True)
    btc_df = pyupbit.get_ohlcv("KRW-BTC", interval=INTERVAL, count=COUNT)
    print(f"{len(btc_df)} bars")

    btc_bull    = is_btc_bull(btc_df)
    btc_st_raw  = compute_stealth_gpu(btc_df, btc_df)
    btc_stealth = btc_st_raw

    btc_st_on = (
        (btc_st_raw["raw_ret"] < 0) &
        btc_st_raw["acc"].between(ALT_ACC_MIN, ALT_ACC_MAX) &
        (btc_st_raw["cvd_slope"] > 0)
    )
    print(f"BTC bull={btc_bull.mean()*100:.1f}%  BTC stealth ON={btc_st_on.mean()*100:.1f}%")
    print()

    tickers = [t for t in pyupbit.get_tickers("KRW") if t != "KRW-BTC"][:TOP_N]
    print(f"Fetching {len(tickers)} alts...")
    data: dict[str, pd.DataFrame] = {}
    for sym in tickers:
        _, df = fetch(sym)
        if df is not None:
            data[sym] = df
    print(f"  {len(data)} loaded\n")

    all_trades: list[dict] = []
    for sym, df in data.items():
        alt_sig = compute_stealth_gpu(df, btc_df)
        if alt_sig.empty:
            continue
        all_trades.extend(backtest_symbol(sym, df, alt_sig, btc_bull, btc_stealth))

    if not all_trades:
        print("거래 없음")
        return

    r  = pd.DataFrame(all_trades)
    n  = len(r)
    wins = (r["return_pct"] > 0).sum()
    avg  = r["return_pct"].mean()
    std  = r["return_pct"].std()
    sharpe = avg / std * np.sqrt(252) if std > 0 else 0

    print("=" * 54)
    print(f"  총 거래:    {n}건")
    print(f"  승률:       {wins/n*100:.1f}%  ({wins}승/{n-wins}패)")
    print(f"  평균수익:   {avg:+.2f}%")
    print(f"  최대수익:   {r['return_pct'].max():+.2f}%")
    print(f"  최대손실:   {r['return_pct'].min():+.2f}%")
    print(f"  Sharpe:     {sharpe:.2f}")
    print("=" * 54)

    print("\n[ 종목별 상위 10 ]")
    print(r.groupby("symbol")["return_pct"].agg(["mean","count"]).sort_values("mean", ascending=False).head(10).to_string())

    print("\n[ rs_entry vs 수익 상관 ]")
    print(f"  rs r={r[['rs_entry','return_pct']].corr().iloc[0,1]:.3f}  acc r={r[['acc_entry','return_pct']].corr().iloc[0,1]:.3f}")

    print("\n[ 최근 거래 8건 ]")
    cols = ["symbol","entry_ts","hold_bars","rs_entry","acc_entry","return_pct"]
    print(r.sort_values("exit_ts").tail(8)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
