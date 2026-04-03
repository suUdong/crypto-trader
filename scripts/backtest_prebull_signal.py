"""
Pre-Bull Signal Backtest — stealth accumulation 신호의 알트코인 예측력 검증

각 역사적 시점 T에서:
  1. stealth 버킷 구성: RS < 1.0 AND Acc > 1.0 AND CVD > 0
  2. T+6/12/24봉 수익률 측정 (vs BTC, vs non-stealth)
  3. 승률 / 평균 수익률 / BTC 대비 알파 리포트

GPU 3D unfold 벡터화: (n_symbols, n_windows, lookback) 동시 연산
Output: artifacts/prebull-backtest-result.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import torch

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

INTERVAL   = "minute240"   # 4h봉
COUNT      = 500           # ~83일
LOOKBACK   = 24            # 슬라이딩 윈도우 (96h = 4일)
RECENT_W   = 6             # Acc/CVD 최근 구간 (24h)
FORWARD_BARS = [6, 12, 24] # 검증 구간 (24h, 48h, 96h)
FETCH_WORKERS = 3


def fetch_symbol(symbol: str) -> tuple[str, pd.DataFrame | None]:
    try:
        import pyupbit
        time.sleep(0.3)
        df = pyupbit.get_ohlcv(symbol, interval=INTERVAL, count=COUNT)
        min_len = LOOKBACK + max(FORWARD_BARS) + 10
        if df is None or len(df) < min_len:
            return symbol, None
        return symbol, df
    except Exception:
        return symbol, None


def compute_stealth_and_returns(
    all_data: dict[str, pd.DataFrame],
    btc_df: pd.DataFrame,
) -> dict:
    """
    GPU 3D 벡터화로 모든 종목 × 모든 시점의 stealth 신호와 수익률을 동시 계산.

    Returns dict with per-forward-bar statistics.
    """
    symbols = list(all_data.keys())
    n = len(symbols)
    if n == 0:
        return {}

    common_len = min(min(len(df) for df in all_data.values()), len(btc_df))
    n_windows = common_len - LOOKBACK
    if n_windows <= 0:
        return {}

    # ── GPU 행렬 구성 (n_symbols, common_len) ───────────────────────────────
    closes_mat = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)
    opens_mat  = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)
    highs_mat  = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)
    lows_mat   = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)
    vols_mat   = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)

    for i, sym in enumerate(symbols):
        df = all_data[sym].iloc[-common_len:]
        closes_mat[i] = torch.tensor(df["close"].values,  dtype=torch.float32)
        opens_mat[i]  = torch.tensor(df["open"].values,   dtype=torch.float32)
        highs_mat[i]  = torch.tensor(df["high"].values,   dtype=torch.float32)
        lows_mat[i]   = torch.tensor(df["low"].values,    dtype=torch.float32)
        vols_mat[i]   = torch.tensor(df["volume"].values, dtype=torch.float32)

    btc_closes = torch.tensor(
        btc_df["close"].values[-common_len:], device="cuda", dtype=torch.float32
    )

    # ── 3D 슬라이딩 윈도우: (n_symbols, n_windows, LOOKBACK) ────────────────
    # unfold produces n_windows+1 windows; keep only n_windows to match loop semantics
    c_w   = closes_mat.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    o_w   = opens_mat.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    h_w   = highs_mat.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    l_w   = lows_mat.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    v_w   = vols_mat.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    btc_w = btc_closes.unfold(0, LOOKBACK, 1)[:n_windows, :]   # (n_windows, LOOKBACK)

    # ── RS (n, n_windows) ────────────────────────────────────────────────────
    sym_norm = c_w / c_w[:, :, 0:1].clamp(min=1e-9)
    btc_norm = btc_w / btc_w[:, 0:1].clamp(min=1e-9)           # (n_win, LOOKBACK)
    rs = (sym_norm / btc_norm.unsqueeze(0))[:, :, -1]           # (n, n_win)

    # ── Acc (n, n_windows) ───────────────────────────────────────────────────
    rng  = (h_w - l_w).clamp(min=1e-9)
    vpin = (c_w - o_w).abs() / rng
    acc  = (
        vpin[:, :, -RECENT_W:].mean(dim=2)
        / vpin[:, :, :-RECENT_W].mean(dim=2).clamp(min=1e-9)
    )

    # ── CVD slope (n, n_windows) ─────────────────────────────────────────────
    direction = torch.where(c_w >= o_w, torch.ones_like(v_w), torch.full_like(v_w, -1.0))
    cvd = (v_w * direction).cumsum(dim=2)
    vol_mean = v_w.mean(dim=2).clamp(min=1e-9)
    cvd_slope = (cvd[:, :, -1] - cvd[:, :, -RECENT_W]) / vol_mean

    # ── Stealth mask (n, n_windows) ──────────────────────────────────────────
    stealth = (rs < 1.0) & (acc > 1.0) & (cvd_slope > 0)       # (n, n_win)

    # ── Forward returns per horizon ──────────────────────────────────────────
    results = {}
    for fwd in FORWARD_BARS:
        valid_w = n_windows - fwd
        if valid_w <= 5:
            continue

        # current close = closes_mat[:, LOOKBACK-1 + w] for window w
        cur_idx_start = LOOKBACK - 1
        cur = closes_mat[:, cur_idx_start:cur_idx_start + valid_w]          # (n, valid_w)
        fut = closes_mat[:, cur_idx_start + fwd:cur_idx_start + fwd + valid_w]  # (n, valid_w)
        fwd_ret = fut / cur.clamp(min=1e-9) - 1.0                           # (n, valid_w)

        # BTC forward return (same windows)
        btc_cur = btc_closes[cur_idx_start:cur_idx_start + valid_w]
        btc_fut = btc_closes[cur_idx_start + fwd:cur_idx_start + fwd + valid_w]
        btc_ret = (btc_fut / btc_cur.clamp(min=1e-9) - 1.0).unsqueeze(0)   # (1, valid_w)

        stealth_v = stealth[:, :valid_w]

        # Stealth group vs non-stealth group (exclude BTC from non-stealth)
        s_ret  = fwd_ret[stealth_v].cpu().numpy()
        ns_ret = fwd_ret[~stealth_v].cpu().numpy()
        alpha_ret = (fwd_ret - btc_ret)[stealth_v].cpu().numpy()  # excess return vs BTC

        btc_arr = btc_ret.squeeze().cpu().numpy()

        results[fwd] = {
            "stealth_n":        int(stealth_v.sum().item()),
            "non_stealth_n":    int((~stealth_v).sum().item()),
            "stealth_mean_%":   round(float(s_ret.mean()) * 100, 3) if len(s_ret) else float("nan"),
            "non_stealth_mean_%": round(float(ns_ret.mean()) * 100, 3) if len(ns_ret) else float("nan"),
            "stealth_win_rate": round(float((s_ret > 0).mean()), 3) if len(s_ret) else float("nan"),
            "alpha_vs_btc_%":   round(float(alpha_ret.mean()) * 100, 3) if len(alpha_ret) else float("nan"),
            "btc_mean_%":       round(float(btc_arr.mean()) * 100, 3),
            "edge_%":           round(
                (float(s_ret.mean()) - float(ns_ret.mean())) * 100, 3
            ) if len(s_ret) and len(ns_ret) else float("nan"),
        }

    # ── 종목별 stealth 적중률 (자주 stealth에 들어간 코인이 잘 올랐는가) ─────
    top_coins = []
    stealth_cpu = stealth.cpu().numpy()
    for fwd in FORWARD_BARS:
        valid_w = n_windows - fwd
        if valid_w <= 5:
            continue
        cur = closes_mat[:, LOOKBACK-1:LOOKBACK-1+valid_w].cpu().numpy()
        fut = closes_mat[:, LOOKBACK-1+fwd:LOOKBACK-1+fwd+valid_w].cpu().numpy()
        fwd_ret_np = fut / np.clip(cur, 1e-9, None) - 1.0
        sv = stealth_cpu[:, :valid_w]
        for i, sym in enumerate(symbols):
            mask = sv[i]
            if mask.sum() < 3:
                continue
            avg_ret = float(fwd_ret_np[i][mask].mean()) * 100
            win_rate = float((fwd_ret_np[i][mask] > 0).mean())
            top_coins.append({
                "symbol": sym, "fwd": fwd, "count": int(mask.sum()),
                "avg_ret_%": round(avg_ret, 3), "win_rate": round(win_rate, 3),
            })

    return {"by_horizon": results, "top_coins": top_coins, "stealth_matrix": stealth.cpu().numpy()}


def main() -> None:
    import pyupbit
    if not torch.cuda.is_available():
        print("ERROR: CUDA unavailable")
        sys.exit(1)

    print("=" * 70)
    print("  Pre-Bull Stealth Signal Backtest (RTX 3080)")
    print(f"  Interval: {INTERVAL} | Count: {COUNT} | Lookback: {LOOKBACK}봉")
    print(f"  Forward: {FORWARD_BARS} | Recent window: {RECENT_W}봉")
    print("=" * 70)

    t0 = time.time()
    symbols = pyupbit.get_tickers(fiat="KRW")
    btc_df  = pyupbit.get_ohlcv("KRW-BTC", interval=INTERVAL, count=COUNT)

    print(f"Fetching {len(symbols)} symbols (workers={FETCH_WORKERS})...")
    all_data: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures = {ex.submit(fetch_symbol, s): s for s in symbols}
        for future in as_completed(futures):
            sym, df = future.result()
            if df is not None:
                all_data[sym] = df

    print(f"Fetched {len(all_data)} symbols in {time.time()-t0:.1f}s")

    print("Computing stealth signal + forward returns on GPU...")
    t1 = time.time()
    result = compute_stealth_and_returns(all_data, btc_df)
    print(f"GPU done in {time.time()-t1:.2f}s")

    if not result:
        print("No results.")
        return

    by_horizon = result["by_horizon"]
    top_coins  = result["top_coins"]

    # ── 콘솔 출력 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  [Stealth Signal vs Forward Returns]")
    print("=" * 70)
    print(f"{'Horizon':>10} {'Stealth N':>10} {'Stealth Ret':>12} {'Non-Stealth':>12} {'Edge':>8} {'WinRate':>8} {'AlphavsBTC':>12}")
    for fwd, r in sorted(by_horizon.items()):
        print(
            f"  T+{fwd:<4}봉  {r['stealth_n']:>9}  "
            f"{r['stealth_mean_%']:>+10.3f}%  {r['non_stealth_mean_%']:>+10.3f}%  "
            f"{r['edge_%']:>+6.3f}%  {r['stealth_win_rate']:>7.1%}  "
            f"{r['alpha_vs_btc_%']:>+10.3f}%"
        )

    # ── 종목별 Top 스테이지 ────────────────────────────────────────────────────
    print("\n[Top Stealth Coins by Avg Return (fwd=12봉)]")
    df_coins = pd.DataFrame(top_coins)
    if not df_coins.empty:
        df_12 = df_coins[df_coins["fwd"] == 12].sort_values("avg_ret_%", ascending=False)
        print(df_12.head(15).to_string(index=False))

    # ── 마크다운 리포트 저장 ─────────────────────────────────────────────────
    out_path = Path("artifacts/prebull-backtest-result.md")
    out_path.parent.mkdir(exist_ok=True)
    with out_path.open("w") as f:
        f.write("# Pre-Bull Stealth Signal Backtest\n\n")
        f.write(f"실행: {pd.Timestamp.now().isoformat()}\n")
        f.write(f"Lookback: {LOOKBACK}봉 ({LOOKBACK*4}h) | Recent window: {RECENT_W}봉\n\n")

        f.write("## Stealth Signal 예측력 (stealth vs non-stealth)\n\n")
        f.write("| Horizon | Stealth N | Stealth Ret | Non-Stealth | Edge | WinRate | Alpha vs BTC |\n")
        f.write("|---------|-----------|-------------|-------------|------|---------|---------------|\n")
        for fwd, r in sorted(by_horizon.items()):
            f.write(
                f"| T+{fwd}봉 | {r['stealth_n']} | {r['stealth_mean_%']:+.3f}% "
                f"| {r['non_stealth_mean_%']:+.3f}% | {r['edge_%']:+.3f}% "
                f"| {r['stealth_win_rate']:.1%} | {r['alpha_vs_btc_%']:+.3f}% |\n"
            )

        f.write("\n## 종목별 Stealth 적중률 (fwd=12봉 Top 20)\n\n")
        if not df_coins.empty:
            df_12_top = df_coins[df_coins["fwd"] == 12].sort_values("avg_ret_%", ascending=False).head(20)
            f.write(df_12_top.to_csv(index=False))
        f.write("\n\n---\nAuto-generated by backtest_prebull_signal.py\n")

    print(f"\nReport saved → {out_path}")


if __name__ == "__main__":
    main()
