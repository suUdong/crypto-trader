"""
BTC Regime Rotation C — 3-gate Stealth 전략 (검증된 룰 적용)

Gate 1: BTC price > SMA20 (bull regime)
Gate 2: BTC stealth ON  → raw_ret < 0 AND acc ∈ [1.0, 1.5] AND cvd_slope > 0
Gate 3: Alt stealth     → RS ∈ [0.8, 1.0) AND acc ∈ [1.0, 1.5] AND cvd_slope > 0

근거: backtest_stealth_deep.py — BTC stealth 92.9% win rate (2026-04-02 검증)
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
MAX_HOLD_BARS = 24
TOP_N         = 60
FEE           = 0.0005
FETCH_SLEEP   = 0.5

# 3-gate 파라미터 (stealth-signal-rules.md 검증값)
ALT_RS_MIN  = 0.8
ALT_RS_MAX  = 1.0
ALT_ACC_MIN = 1.0
ALT_ACC_MAX = 1.5

# 청산: alt stealth 소멸 OR BTC bull 이탈 OR max_hold
EXIT_ACC_MIN = 1.0   # acc < 1.0이면 accumulation 종료


def fetch(symbol: str) -> tuple[str, pd.DataFrame | None]:
    try:
        import pyupbit
        time.sleep(FETCH_SLEEP)
        df = pyupbit.get_ohlcv(symbol, interval=INTERVAL, count=COUNT)
        if df is not None and len(df) >= LOOKBACK + MAX_HOLD_BARS + 10:
            return symbol, df
        return symbol, None
    except Exception:
        return symbol, None


def compute_stealth_gpu(
    df: pd.DataFrame,
    btc_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    각 봉마다 raw stealth 지표 계산.
    Returns DataFrame: rs, acc, cvd_slope (raw, not z-scored)
    """
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

    # RS: alt vs BTC (window return ratio)
    alt_ret = c_w[:, -1] / c_w[:, 0].clamp(1e-9)
    btc_ret = btc_w[:, -1] / btc_w[:, 0].clamp(1e-9)
    rs = alt_ret / btc_ret.clamp(1e-9)

    # raw_ret: window price return (for BTC stealth gate)
    raw_ret = alt_ret - 1.0

    # Acc: recent VPIN / prior VPIN
    rng  = (h_w - l_w).clamp(1e-9)
    vpin = (c_w - o_w).abs() / rng
    acc  = vpin[:, -RECENT_W:].mean(1) / vpin[:, :-RECENT_W].mean(1).clamp(1e-9)

    # CVD slope
    direction = torch.where(c_w >= o_w, torch.ones_like(v_w), -torch.ones_like(v_w))
    cvd = (v_w * direction).cumsum(1)
    cvd_slope = (cvd[:, -1] - cvd[:, -RECENT_W]) / v_w.mean(1).clamp(1e-9)

    return pd.DataFrame({
        "rs":        rs.cpu().numpy(),
        "raw_ret":   raw_ret.cpu().numpy(),
        "acc":       acc.cpu().numpy(),
        "cvd_slope": cvd_slope.cpu().numpy(),
    }, index=df.index[LOOKBACK:])


def compute_btc_stealth(btc_df: pd.DataFrame) -> pd.DataFrame:
    """BTC self-referenced stealth signal."""
    return compute_stealth_gpu(btc_df, btc_df)


def is_btc_bull(btc_df: pd.DataFrame) -> pd.Series:
    closes = btc_df["close"]
    sma = closes.rolling(SMA_PERIOD).mean()
    return (closes > sma).rename("btc_bull")


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
    if len(common) < 2:
        return []

    df2   = df.loc[common]
    alt2  = alt_sig.reindex(common)
    bull2 = btc_bull.reindex(common)
    bst2  = btc_stealth.reindex(common)

    trades, in_pos = [], False
    entry_price = entry_bar = 0
    entry_info: dict = {}

    for i, ts in enumerate(common):
        price = df2.loc[ts, "close"]
        ar    = alt2.loc[ts]
        bull  = bull2.loc[ts]
        bs    = bst2.loc[ts]

        # Gate 1: BTC bull
        g1 = bool(bull)
        # Gate 2: BTC stealth
        g2 = bool(bs["raw_ret"] < 0 and ALT_ACC_MIN <= bs["acc"] <= ALT_ACC_MAX and bs["cvd_slope"] > 0)
        # Gate 3: Alt stealth (RS range + acc range + cvd > 0)
        g3 = bool(ALT_RS_MIN <= ar["rs"] < ALT_RS_MAX and ALT_ACC_MIN <= ar["acc"] <= ALT_ACC_MAX and ar["cvd_slope"] > 0)

        if not in_pos:
            if g1 and g2 and g3:
                in_pos      = True
                entry_price = price * (1 + FEE)
                entry_bar   = i
                entry_info  = {"rs": ar["rs"], "acc": ar["acc"], "btc_acc": bs["acc"]}
        else:
            hold = i - entry_bar
            # 청산: BTC bull 이탈 OR alt acc 소멸 OR max_hold
            reason = None
            if not bull:
                reason = "btc_bear"
            elif ar["acc"] < EXIT_ACC_MIN:
                reason = "acc_exit"
            elif hold >= MAX_HOLD_BARS:
                reason = "max_hold"
            if reason:
                ret = (price * (1 - FEE) / entry_price - 1) * 100
                trades.append({
                    "symbol":     symbol,
                    "entry_ts":   common[entry_bar],
                    "exit_ts":    ts,
                    "hold_bars":  hold,
                    "return_pct": ret,
                    "rs_entry":   entry_info["rs"],
                    "acc_entry":  entry_info["acc"],
                    "btc_acc":    entry_info["btc_acc"],
                    "exit_reason": reason,
                })
                in_pos = False

    return trades


def main() -> None:
    import pyupbit

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Strategy C] 3-gate Stealth  [{device}]")
    print(f"Gate1: BTC>SMA20 | Gate2: BTC stealth | Gate3: Alt RS∈[{ALT_RS_MIN},{ALT_RS_MAX}) acc∈[{ALT_ACC_MIN},{ALT_ACC_MAX}]")
    print()

    print("Fetching BTC...", end=" ", flush=True)
    btc_df = pyupbit.get_ohlcv("KRW-BTC", interval=INTERVAL, count=COUNT)
    print(f"{len(btc_df)} bars")

    btc_bull   = is_btc_bull(btc_df)
    btc_st_raw = compute_btc_stealth(btc_df)
    btc_stealth = btc_st_raw.reindex(btc_df.index[LOOKBACK:])

    bull_pct  = btc_bull.mean() * 100
    # BTC stealth fires when all 3 conditions met
    btc_st_on = (
        (btc_st_raw["raw_ret"] < 0) &
        btc_st_raw["acc"].between(ALT_ACC_MIN, ALT_ACC_MAX) &
        (btc_st_raw["cvd_slope"] > 0)
    )
    print(f"BTC bull={bull_pct:.1f}%  BTC stealth ON={btc_st_on.mean()*100:.1f}%")
    print()

    tickers = [t for t in pyupbit.get_tickers("KRW") if t != "KRW-BTC"][:TOP_N]
    print(f"Fetching {len(tickers)} alts (sequential)...")
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
        trades = backtest_symbol(sym, df, alt_sig, btc_bull, btc_stealth)
        all_trades.extend(trades)

    if not all_trades:
        print("거래 없음 — BTC stealth 발동 구간에 alt 조건 동시 충족 없음")
        return

    r = pd.DataFrame(all_trades)
    n  = len(r)
    wins = (r["return_pct"] > 0).sum()
    avg = r["return_pct"].mean()
    std = r["return_pct"].std()
    sharpe = avg / std * np.sqrt(252) if std > 0 else 0

    print("=" * 54)
    print(f"  총 거래:    {n}건")
    print(f"  승률:       {wins/n*100:.1f}%  ({wins}승/{n-wins}패)")
    print(f"  평균수익:   {avg:+.2f}%")
    print(f"  최대수익:   {r['return_pct'].max():+.2f}%")
    print(f"  최대손실:   {r['return_pct'].min():+.2f}%")
    print(f"  Sharpe:     {sharpe:.2f}")
    print("=" * 54)

    print("\n[ 청산 사유 ]")
    print(r["exit_reason"].value_counts().to_string())

    print("\n[ 종목별 상위 10 ]")
    print(r.groupby("symbol")["return_pct"].agg(["mean","count"]).sort_values("mean", ascending=False).head(10).to_string())

    print("\n[ rs_entry vs 수익 상관 ]")
    corr_rs  = r[["rs_entry","return_pct"]].corr().iloc[0,1]
    corr_acc = r[["acc_entry","return_pct"]].corr().iloc[0,1]
    print(f"  rs_entry r={corr_rs:.3f}  acc_entry r={corr_acc:.3f}")

    print("\n[ 최근 거래 8건 ]")
    cols = ["symbol","entry_ts","hold_bars","rs_entry","acc_entry","return_pct","exit_reason"]
    print(r.sort_values("exit_ts").tail(8)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
