"""
BTC Regime Rotation 백테스트 (v2)

- Alpha: backtest_alpha_filter.py와 동일한 GPU 벡터화 z-score 방식
- 진입: BTC bull regime + alt alpha > threshold
- 청산: BTC 레짐이 bull 아님 OR alpha < exit_alpha OR max_hold_bars 초과
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

# ── 파라미터 ──────────────────────────────────────────────────────────────────
INTERVAL      = "minute240"  # 4시간봉
COUNT         = 500          # ~83일
LOOKBACK      = 30
RECENT_W      = 6
ALPHA_THRESH  = 1.0          # 진입 기준 (z-score 기반)
EXIT_ALPHA    = 0.0          # 청산 기준 (z-score 0 이하)
MAX_HOLD_BARS = 24           # 최대 보유 봉 (4h * 24 = 4일)
TOP_N         = 40           # 스캔 종목 수
FEE           = 0.0005       # 수수료 0.05% 왕복
FETCH_SLEEP   = 0.5          # rate limit 대응
# ─────────────────────────────────────────────────────────────────────────────


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


def compute_alpha_gpu(df: pd.DataFrame, btc_df: pd.DataFrame) -> pd.Series:
    """GPU-vectorized z-score alpha (same as backtest_alpha_filter.py)."""
    common_len = min(len(df), len(btc_df))
    df     = df.iloc[-common_len:]
    btc_df = btc_df.iloc[-common_len:]
    n_windows = common_len - LOOKBACK
    if n_windows <= 0:
        return pd.Series(dtype=float)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    closes  = torch.tensor(df["close"].values,     device=device, dtype=torch.float32)
    opens   = torch.tensor(df["open"].values,      device=device, dtype=torch.float32)
    highs   = torch.tensor(df["high"].values,      device=device, dtype=torch.float32)
    lows    = torch.tensor(df["low"].values,       device=device, dtype=torch.float32)
    vols    = torch.tensor(df["volume"].values,    device=device, dtype=torch.float32)
    btc_c   = torch.tensor(btc_df["close"].values, device=device, dtype=torch.float32)

    c_w   = closes.unfold(0, LOOKBACK, 1)[:n_windows]
    o_w   = opens.unfold(0, LOOKBACK, 1)[:n_windows]
    h_w   = highs.unfold(0, LOOKBACK, 1)[:n_windows]
    l_w   = lows.unfold(0, LOOKBACK, 1)[:n_windows]
    v_w   = vols.unfold(0, LOOKBACK, 1)[:n_windows]
    btc_w = btc_c.unfold(0, LOOKBACK, 1)[:n_windows]

    # RS
    sym_norm = c_w / c_w[:, 0:1].clamp(min=1e-9)
    btc_norm = btc_w / btc_w[:, 0:1].clamp(min=1e-9)
    rs = (sym_norm / btc_norm)[:, -1]

    # Acc
    rng  = (h_w - l_w).clamp(min=1e-9)
    vpin = (c_w - o_w).abs() / rng
    acc  = vpin[:, -RECENT_W:].mean(dim=1) / vpin[:, :-RECENT_W].mean(dim=1).clamp(min=1e-9)

    # CVD slope
    direction = torch.where(c_w >= o_w, torch.ones_like(v_w), torch.full_like(v_w, -1.0))
    cvd = (v_w * direction).cumsum(dim=1)
    vol_mean = v_w.mean(dim=1).clamp(min=1e-9)
    cvd_slope = (cvd[:, -1] - cvd[:, -RECENT_W]) / vol_mean

    def zs(t: torch.Tensor) -> torch.Tensor:
        return (t - t.mean()) / (t.std() + 1e-9)

    alpha = zs(rs) * 0.4 + zs(acc) * 0.3 + zs(cvd_slope) * 0.3
    return pd.Series(alpha.cpu().numpy(), index=df.index[LOOKBACK:])


def backtest_symbol(
    symbol: str,
    df: pd.DataFrame,
    regime: pd.Series,
    alpha: pd.Series,
) -> list[dict]:
    common = df.index.intersection(regime.index).intersection(alpha.index)
    if len(common) < 2:
        return []
    df2  = df.loc[common]
    reg2 = regime.reindex(common)
    alp2 = alpha.reindex(common)

    trades: list[dict] = []
    in_pos = False
    entry_price = entry_bar = entry_alpha = 0.0

    for i, ts in enumerate(common):
        btc_bull  = reg2.loc[ts] == "bull"
        alpha_val = alp2.loc[ts]
        price     = df2.loc[ts, "close"]

        if not in_pos:
            if btc_bull and alpha_val >= ALPHA_THRESH:
                in_pos      = True
                entry_price = price * (1 + FEE)
                entry_bar   = i
                entry_alpha = alpha_val
        else:
            hold_bars = i - entry_bar
            reason = None
            if not btc_bull:
                reason = "bear"
            elif alpha_val < EXIT_ALPHA:
                reason = "alpha_low"
            elif hold_bars >= MAX_HOLD_BARS:
                reason = "max_hold"

            if reason:
                exit_price = price * (1 - FEE)
                ret = (exit_price / entry_price - 1) * 100
                trades.append({
                    "symbol":       symbol,
                    "entry_ts":     common[entry_bar],
                    "exit_ts":      ts,
                    "hold_bars":    hold_bars,
                    "return_pct":   ret,
                    "alpha_entry":  entry_alpha,
                    "alpha_exit":   alpha_val,
                    "exit_reason":  reason,
                })
                in_pos = False

    return trades


def main() -> None:
    import pyupbit

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"BTC Regime Rotation Backtest v2  [{device}]")
    print(f"interval={INTERVAL}  count={COUNT}  alpha_thresh={ALPHA_THRESH}  max_hold={MAX_HOLD_BARS}bars")
    print()

    print("Fetching BTC...", end=" ", flush=True)
    btc_df = pyupbit.get_ohlcv("KRW-BTC", interval=INTERVAL, count=COUNT)
    print(f"{len(btc_df)} bars")
    regime = detect_btc_regime(btc_df)
    print(f"BTC regime: bull={( regime=='bull').mean()*100:.1f}%  pre_bull={(regime=='pre_bull').mean()*100:.1f}%  bear={(regime=='bear').mean()*100:.1f}%")
    print()

    tickers = [t for t in pyupbit.get_tickers("KRW") if t != "KRW-BTC"][:TOP_N]
    print(f"Fetching {len(tickers)} alts (sequential, sleep={FETCH_SLEEP}s)...")
    data: dict[str, pd.DataFrame] = {}
    for sym in tickers:
        try:
            time.sleep(FETCH_SLEEP)
            df = pyupbit.get_ohlcv(sym, interval=INTERVAL, count=COUNT)
            if df is not None and len(df) >= LOOKBACK + MAX_HOLD_BARS + 10:
                data[sym] = df
        except Exception:
            pass
    print(f"  {len(data)} symbols loaded")
    print()

    all_trades: list[dict] = []
    for sym, df in data.items():
        alpha = compute_alpha_gpu(df, btc_df)
        if alpha.empty:
            continue
        trades = backtest_symbol(sym, df, regime, alpha)
        all_trades.extend(trades)

    if not all_trades:
        print("거래 없음 — alpha_thresh 낮춰보세요")
        return

    results = pd.DataFrame(all_trades)
    n       = len(results)
    wins    = (results["return_pct"] > 0).sum()
    wr      = wins / n * 100
    avg_ret = results["return_pct"].mean()
    std_ret = results["return_pct"].std()
    sharpe  = avg_ret / std_ret * np.sqrt(252) if std_ret > 0 else 0
    max_loss = results["return_pct"].min()
    best     = results["return_pct"].max()

    print("=" * 56)
    print(f"  총 거래:     {n}건")
    print(f"  승률:        {wr:.1f}%  ({int(wins)}승 / {n - int(wins)}패)")
    print(f"  평균 수익:   {avg_ret:+.2f}%")
    print(f"  최대 수익:   {best:+.2f}%")
    print(f"  최대 손실:   {max_loss:+.2f}%")
    print(f"  Sharpe:      {sharpe:.2f}")
    print("=" * 56)

    print("\n[ 청산 사유 분포 ]")
    print(results["exit_reason"].value_counts().to_string())

    print("\n[ 종목별 성과 상위 10 (평균 수익률) ]")
    sym_perf = (
        results.groupby("symbol")["return_pct"]
        .agg(["mean", "count", "sum"])
        .sort_values("mean", ascending=False)
    )
    print(sym_perf.head(10).to_string())

    print("\n[ Alpha 진입값 vs 수익률 상관 ]")
    corr = results[["alpha_entry", "return_pct"]].corr().iloc[0, 1]
    print(f"  Pearson r = {corr:.3f}")

    print("\n[ 최근 거래 8건 ]")
    cols = ["symbol", "entry_ts", "hold_bars", "alpha_entry", "return_pct", "exit_reason"]
    print(results.sort_values("exit_ts").tail(8)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
