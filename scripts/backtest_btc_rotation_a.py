"""
BTC Regime Rotation A — pre_bull 진입 전략

진입: BTC pre_bull regime + alt acc_z > 0.5 AND rs_z < 1.0 (아직 안 오른 종목)
청산: BTC bear OR alpha 급락(< -1.0) OR max_hold_bars 초과
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
ACC_THRESH    = 0.5    # acc_z 진입 기준 (가속 중)
RS_MAX        = 1.0    # rs_z 상한 (이미 너무 오른 종목 제외)
EXIT_ALPHA    = -1.0   # alpha_z 이하면 청산
MAX_HOLD_BARS = 24
TOP_N         = 40
FEE           = 0.0005
FETCH_SLEEP   = 0.5


def detect_btc_regime(btc_df: pd.DataFrame, sma_period: int = 20) -> pd.Series:
    closes = btc_df["close"]
    sma = closes.rolling(sma_period).mean()
    sma_slope = sma.pct_change(5).fillna(0)
    slope_std = sma_slope.std() or 1e-9
    above = closes > sma
    slope_pos = sma_slope > 0
    slope_recovering = sma_slope > -0.5 * slope_std
    regime = pd.Series("bear", index=closes.index)
    regime[above & slope_pos] = "bull"
    regime[above & ~slope_pos] = "post_bull"
    regime[~above & slope_recovering] = "pre_bull"
    return regime


def compute_alpha_gpu(df: pd.DataFrame, btc_df: pd.DataFrame) -> pd.DataFrame:
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

    rs = (c_w / c_w[:, 0:1].clamp(1e-9))[:, -1] / (btc_w / btc_w[:, 0:1].clamp(1e-9))[:, -1]
    rng  = (h_w - l_w).clamp(1e-9)
    vpin = (c_w - o_w).abs() / rng
    acc  = vpin[:, -RECENT_W:].mean(1) / vpin[:, :-RECENT_W].mean(1).clamp(1e-9)
    direction = torch.where(c_w >= o_w, torch.ones_like(v_w), -torch.ones_like(v_w))
    cvd = (v_w * direction).cumsum(1)
    cvd_slope = (cvd[:, -1] - cvd[:, -RECENT_W]) / v_w.mean(1).clamp(1e-9)

    def zs(t: torch.Tensor) -> torch.Tensor:
        return (t - t.mean()) / (t.std() + 1e-9)

    rs_z, acc_z, cvd_z = zs(rs), zs(acc), zs(cvd_slope)
    alpha = rs_z * 0.4 + acc_z * 0.3 + cvd_z * 0.3

    return pd.DataFrame({
        "rs_z":  rs_z.cpu().numpy(),
        "acc_z": acc_z.cpu().numpy(),
        "cvd_z": cvd_z.cpu().numpy(),
        "alpha": alpha.cpu().numpy(),
    }, index=df.index[LOOKBACK:])


def backtest_symbol(symbol, df, regime, alpha_df) -> list[dict]:
    common = df.index.intersection(regime.index).intersection(alpha_df.index)
    if len(common) < 2:
        return []
    df2  = df.loc[common]
    reg2 = regime.reindex(common)
    alp2 = alpha_df.reindex(common)

    trades, in_pos = [], False
    entry_price = entry_bar = 0

    for i, ts in enumerate(common):
        reg = reg2.loc[ts]
        row = alp2.loc[ts]
        price = df2.loc[ts, "close"]

        if not in_pos:
            # pre_bull 진입: acc_z 높고 rs_z 낮음 (아직 안 오른 종목)
            if reg == "pre_bull" and row["acc_z"] >= ACC_THRESH and row["rs_z"] <= RS_MAX:
                in_pos = True
                entry_price = price * (1 + FEE)
                entry_bar = i
                entry_row = row.copy()
        else:
            hold = i - entry_bar
            reason = None
            if reg == "bear":
                reason = "bear"
            elif row["alpha"] < EXIT_ALPHA:
                reason = "alpha_low"
            elif hold >= MAX_HOLD_BARS:
                reason = "max_hold"
            if reason:
                ret = (price * (1 - FEE) / entry_price - 1) * 100
                trades.append({
                    "symbol":      symbol,
                    "entry_ts":    common[entry_bar],
                    "exit_ts":     ts,
                    "hold_bars":   hold,
                    "return_pct":  ret,
                    "acc_z_entry": entry_row["acc_z"],
                    "rs_z_entry":  entry_row["rs_z"],
                    "exit_reason": reason,
                })
                in_pos = False
    return trades


def main():
    import pyupbit
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Strategy A] pre_bull + acc_z>{ACC_THRESH} + rs_z<{RS_MAX}  [{device}]")
    print()

    btc_df = pyupbit.get_ohlcv("KRW-BTC", interval=INTERVAL, count=COUNT)
    regime = detect_btc_regime(btc_df)
    print(f"BTC: bull={( regime=='bull').mean()*100:.1f}%  pre_bull={(regime=='pre_bull').mean()*100:.1f}%  bear={(regime=='bear').mean()*100:.1f}%")

    tickers = [t for t in pyupbit.get_tickers("KRW") if t != "KRW-BTC"][:TOP_N]
    print(f"Fetching {len(tickers)} alts...")
    data = {}
    for sym in tickers:
        try:
            time.sleep(FETCH_SLEEP)
            df = pyupbit.get_ohlcv(sym, interval=INTERVAL, count=COUNT)
            if df is not None and len(df) >= LOOKBACK + MAX_HOLD_BARS + 10:
                data[sym] = df
        except Exception:
            pass
    print(f"  {len(data)} loaded\n")

    all_trades = []
    for sym, df in data.items():
        adf = compute_alpha_gpu(df, btc_df)
        if adf.empty:
            continue
        all_trades.extend(backtest_symbol(sym, df, regime, adf))

    if not all_trades:
        print("거래 없음")
        return

    r = pd.DataFrame(all_trades)
    n  = len(r); wins = (r["return_pct"] > 0).sum()
    avg = r["return_pct"].mean()
    std = r["return_pct"].std()
    sharpe = avg / std * np.sqrt(252) if std > 0 else 0

    print("=" * 52)
    print(f"  총 거래:   {n}건")
    print(f"  승률:      {wins/n*100:.1f}%  ({wins}승/{n-wins}패)")
    print(f"  평균수익:  {avg:+.2f}%")
    print(f"  최대수익:  {r['return_pct'].max():+.2f}%")
    print(f"  최대손실:  {r['return_pct'].min():+.2f}%")
    print(f"  Sharpe:    {sharpe:.2f}")
    print("=" * 52)
    print("\n[ 청산 사유 ]")
    print(r["exit_reason"].value_counts().to_string())
    print("\n[ 종목별 상위 10 ]")
    print(r.groupby("symbol")["return_pct"].agg(["mean","count"]).sort_values("mean", ascending=False).head(10).to_string())
    print("\n[ acc_z_entry vs 수익 상관 ]")
    print(f"  r = {r[['acc_z_entry','return_pct']].corr().iloc[0,1]:.3f}")


if __name__ == "__main__":
    main()
