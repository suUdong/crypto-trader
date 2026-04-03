"""
Stealth Signal Deep Analysis — BTC + Alt Joint

Four-axis deep dive:
  1. BTC regime split      (bull=price>SMA20, bear=below)
  2. Threshold grid        RS_thresh × Acc_thresh (6×4 combos)
  3. Signal strength       top/mid/bottom quartile by stealth_score
  4. Joint BTC×Alt stealth 4-quadrant: who accumulates simultaneously?

BTC stealth definition (self-referenced):
  raw_return = close[-1]/close[0] < 1.0  (window net negative)
  AND acc > 1.0  AND cvd_slope > 0

Alt stealth: RS_vs_BTC < 1.0 AND acc > 1.0 AND cvd_slope > 0

GPU 3D unfold 벡터화 (n_symbols, n_windows, LOOKBACK)
Output: artifacts/stealth-deep-result.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import product

import numpy as np
import pandas as pd
import torch

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical, get_available_symbols

INTERVAL      = "240m"
START         = "2022-01-01"
END           = "2026-12-31"
LOOKBACK      = 24
RECENT_W      = 6
FWD           = 12            # primary horizon
FETCH_WORKERS = 6

RS_THRESHOLDS  = [0.7, 0.8, 0.9, 1.0]
ACC_THRESHOLDS = [1.0, 1.2, 1.5, 2.0]


# ── fetch ─────────────────────────────────────────────────────────────────────

def fetch_symbol(symbol: str) -> tuple[str, pd.DataFrame | None]:
    try:
        df = load_historical(symbol, INTERVAL, START, END)
        if df is None or len(df) < LOOKBACK + FWD + 30:
            return symbol, None
        return symbol, df
    except Exception:
        return symbol, None


# ── GPU tensor build ──────────────────────────────────────────────────────────

def build_tensors(all_data, btc_df):
    symbols    = list(all_data.keys())
    n          = len(symbols)
    common_len = min(min(len(df) for df in all_data.values()), len(btc_df))

    C = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)
    O = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)
    H = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)
    L = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)
    V = torch.zeros(n, common_len, device="cuda", dtype=torch.float32)

    for i, sym in enumerate(symbols):
        df   = all_data[sym].iloc[-common_len:]
        C[i] = torch.tensor(df["close"].values,  dtype=torch.float32)
        O[i] = torch.tensor(df["open"].values,   dtype=torch.float32)
        H[i] = torch.tensor(df["high"].values,   dtype=torch.float32)
        L[i] = torch.tensor(df["low"].values,    dtype=torch.float32)
        V[i] = torch.tensor(df["volume"].values, dtype=torch.float32)

    btc_c = torch.tensor(btc_df["close"].values[-common_len:], device="cuda", dtype=torch.float32)
    btc_o = torch.tensor(btc_df["open"].values[-common_len:],  device="cuda", dtype=torch.float32)
    btc_h = torch.tensor(btc_df["high"].values[-common_len:],  device="cuda", dtype=torch.float32)
    btc_l = torch.tensor(btc_df["low"].values[-common_len:],   device="cuda", dtype=torch.float32)
    btc_v = torch.tensor(btc_df["volume"].values[-common_len:],device="cuda", dtype=torch.float32)

    return C, O, H, L, V, btc_c, btc_o, btc_h, btc_l, btc_v, symbols, common_len


# ── core metrics ──────────────────────────────────────────────────────────────

def alt_metrics(C, O, H, L, V, btc_c, n_windows):
    """rs, acc, cvd_slope — all (n_alt, n_windows)."""
    cw = C.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    ow = O.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    hw = H.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    lw = L.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    vw = V.unfold(1, LOOKBACK, 1)[:, :n_windows, :]
    bw = btc_c.unfold(0, LOOKBACK, 1)[:n_windows, :]  # (n_win, LB)

    sym_norm = cw / cw[:, :, 0:1].clamp(min=1e-9)
    btc_norm = bw / bw[:, 0:1].clamp(min=1e-9)
    rs = (sym_norm / btc_norm.unsqueeze(0))[:, :, -1]

    rng  = (hw - lw).clamp(min=1e-9)
    vpin = (cw - ow).abs() / rng
    acc  = vpin[:, :, -RECENT_W:].mean(2) / vpin[:, :, :-RECENT_W].mean(2).clamp(min=1e-9)

    dirn     = torch.where(cw >= ow, torch.ones_like(vw), torch.full_like(vw, -1.0))
    cvd      = (vw * dirn).cumsum(dim=2)
    cvd_slope = (cvd[:, :, -1] - cvd[:, :, -RECENT_W]) / vw.mean(2).clamp(min=1e-9)

    return rs, acc, cvd_slope


def btc_metrics(btc_c, btc_o, btc_h, btc_l, btc_v, n_windows):
    """btc_raw_ret, btc_acc, btc_cvd — all (n_windows,)."""
    cw = btc_c.unfold(0, LOOKBACK, 1)[:n_windows, :]  # (n_win, LB)
    ow = btc_o.unfold(0, LOOKBACK, 1)[:n_windows, :]
    hw = btc_h.unfold(0, LOOKBACK, 1)[:n_windows, :]
    lw = btc_l.unfold(0, LOOKBACK, 1)[:n_windows, :]
    vw = btc_v.unfold(0, LOOKBACK, 1)[:n_windows, :]

    raw_ret = cw[:, -1] / cw[:, 0].clamp(min=1e-9) - 1.0   # window net return

    rng  = (hw - lw).clamp(min=1e-9)
    vpin = (cw - ow).abs() / rng
    acc  = vpin[:, -RECENT_W:].mean(1) / vpin[:, :-RECENT_W].mean(1).clamp(min=1e-9)

    dirn      = torch.where(cw >= ow, torch.ones_like(vw), torch.full_like(vw, -1.0))
    cvd       = (vw * dirn).cumsum(dim=1)
    cvd_slope = (cvd[:, -1] - cvd[:, -RECENT_W]) / vw.mean(1).clamp(min=1e-9)

    return raw_ret, acc, cvd_slope


# ── BTC regime via SMA20 ──────────────────────────────────────────────────────

def btc_sma_regime(btc_df, common_len, n_windows):
    c  = btc_df["close"].values[-common_len:]
    sma = np.convolve(c, np.ones(20) / 20, mode="valid")
    bull = np.zeros(n_windows, dtype=bool)
    for w in range(n_windows):
        ci = LOOKBACK - 1 + w
        si = ci - 19
        if 0 <= si < len(sma):
            bull[w] = c[ci] > sma[si]
    return bull


# ── forward returns ───────────────────────────────────────────────────────────

def fwd_returns(closes, n_windows):
    valid_w = n_windows - FWD
    cur = closes[:, LOOKBACK - 1: LOOKBACK - 1 + valid_w]
    fut = closes[:, LOOKBACK - 1 + FWD: LOOKBACK - 1 + FWD + valid_w]
    return fut / cur.clamp(min=1e-9) - 1.0, valid_w


def btc_fwd_returns(btc_c, n_windows):
    valid_w = n_windows - FWD
    cur = btc_c[LOOKBACK - 1: LOOKBACK - 1 + valid_w]
    fut = btc_c[LOOKBACK - 1 + FWD: LOOKBACK - 1 + FWD + valid_w]
    return (fut / cur.clamp(min=1e-9) - 1.0).cpu().numpy(), valid_w


# ── analysis helpers ──────────────────────────────────────────────────────────

def stats(vals):
    if len(vals) == 0:
        return {"n": 0, "mean_%": float("nan"), "win_rate": float("nan")}
    return {
        "n":        int(len(vals)),
        "mean_%":   round(float(vals.mean()) * 100, 3),
        "win_rate": round(float((vals > 0).mean()), 3),
    }


# ── analysis 1: BTC regime split ─────────────────────────────────────────────

def regime_analysis(rs, acc, cvd, fwd_np, bull_mask, valid_w):
    sm     = ((rs < 1.0) & (acc > 1.0) & (cvd > 0))[:, :valid_w].cpu().numpy()
    bull_b = bull_mask[:valid_w]
    bear_b = ~bull_b
    return {
        "stealth_bull": stats(fwd_np[sm & bull_b[np.newaxis, :]]),
        "stealth_bear": stats(fwd_np[sm & bear_b[np.newaxis, :]]),
        "non_stealth":  stats(fwd_np[~sm]),
        "all_stealth":  stats(fwd_np[sm]),
    }


# ── analysis 2: threshold grid ────────────────────────────────────────────────

def threshold_grid(rs, acc, cvd, fwd_np, valid_w):
    rs_np  = rs[:, :valid_w].cpu().numpy()
    acc_np = acc[:, :valid_w].cpu().numpy()
    cvd_np = cvd[:, :valid_w].cpu().numpy()
    rows = []
    for rs_t, acc_t in product(RS_THRESHOLDS, ACC_THRESHOLDS):
        mask = (rs_np < rs_t) & (acc_np > acc_t) & (cvd_np > 0)
        vals, ns = fwd_np[mask], fwd_np[~mask]
        if len(vals) < 10:
            continue
        rows.append({
            "rs_thresh":  rs_t, "acc_thresh": acc_t,
            "n":          len(vals),
            "mean_%":     round(float(vals.mean()) * 100, 3),
            "win_rate":   round(float((vals > 0).mean()), 3),
            "edge_%":     round((float(vals.mean()) - float(ns.mean())) * 100, 3) if len(ns) else float("nan"),
        })
    return sorted(rows, key=lambda r: r["edge_%"], reverse=True)


# ── analysis 3: signal strength quartiles ────────────────────────────────────

def strength_quartiles(rs, acc, cvd, fwd_np, valid_w):
    rs_np  = rs[:, :valid_w].cpu().numpy()
    acc_np = acc[:, :valid_w].cpu().numpy()
    cvd_np = cvd[:, :valid_w].cpu().numpy()
    sm     = (rs_np < 1.0) & (acc_np > 1.0) & (cvd_np > 0)
    if sm.sum() < 40:
        return []
    score = (1 - rs_np) * acc_np * np.clip(cvd_np, 0, None)
    ss, sf = score[sm], fwd_np[sm]
    q25, q50, q75 = np.percentile(ss, [25, 50, 75])
    rows = []
    for label, lo, hi in [
        ("Q4 (strongest)", q75, np.inf),
        ("Q3",             q50, q75),
        ("Q2",             q25, q50),
        ("Q1 (weakest)",  -np.inf, q25),
    ]:
        m    = (ss >= lo) & (ss < hi)
        vals = sf[m]
        rows.append({
            "quartile": label, "n": int(m.sum()),
            "mean_%":   round(float(vals.mean()) * 100, 3) if len(vals) else float("nan"),
            "win_rate": round(float((vals > 0).mean()), 3) if len(vals) else float("nan"),
        })
    return rows


# ── analysis 4: joint BTC × Alt stealth ──────────────────────────────────────

def joint_analysis(
    rs, acc, cvd,
    btc_raw_ret, btc_acc, btc_cvd,
    alt_fwd_np, btc_fwd_np, valid_w,
):
    """
    4 quadrants at each window:
      A: BTC stealth  AND alt stealth  → what happens to both?
      B: BTC stealth  only             → alts don't accumulate
      C: alt stealth  only             → alts accumulate but BTC doesn't
      D: neither
    """
    alt_sm = ((rs < 1.0) & (acc > 1.0) & (cvd > 0))[:, :valid_w].cpu().numpy()  # (n, valid_w)
    # any alt stealth at window w
    any_alt_sm = alt_sm.any(axis=0)   # (valid_w,)

    btc_sm = (
        (btc_raw_ret[:valid_w] < 0)
        & (btc_acc[:valid_w] > 1.0)
        & (btc_cvd[:valid_w] > 0)
    ).cpu().numpy()                   # (valid_w,)

    rows = []
    for label, wm in [
        ("BTC+Alt stealth",  btc_sm & any_alt_sm),
        ("BTC only stealth", btc_sm & ~any_alt_sm),
        ("Alt only stealth", ~btc_sm & any_alt_sm),
        ("No stealth",       ~btc_sm & ~any_alt_sm),
    ]:
        # alt returns: all alt×window pairs where window matches
        alt_vals_w = alt_fwd_np[:, wm]   # (n_alt, n_matched_windows)
        btc_vals   = btc_fwd_np[wm]

        rows.append({
            "quadrant":      label,
            "windows":       int(wm.sum()),
            "alt_mean_%":    round(float(alt_vals_w.mean()) * 100, 3) if alt_vals_w.size else float("nan"),
            "alt_wr":        round(float((alt_vals_w > 0).mean()), 3) if alt_vals_w.size else float("nan"),
            "btc_mean_%":    round(float(btc_vals.mean()) * 100, 3) if len(btc_vals) else float("nan"),
            "btc_wr":        round(float((btc_vals > 0).mean()), 3) if len(btc_vals) else float("nan"),
        })

    # BTC stealth self-performance (does BTC stealth predict BTC pump?)
    btc_self = [
        ("BTC stealth ON",  btc_sm,  btc_fwd_np[btc_sm]),
        ("BTC stealth OFF", ~btc_sm, btc_fwd_np[~btc_sm]),
    ]

    return rows, btc_self


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if not torch.cuda.is_available():
        print("ERROR: CUDA unavailable"); sys.exit(1)

    print("=" * 70)
    print("  Stealth Signal Deep Analysis — BTC + Alt Joint")
    print(f"  Interval: {INTERVAL} | Period: {START}~{END} | Lookback: {LOOKBACK}봉 | Fwd: {FWD}봉")
    print("=" * 70)

    t0      = time.time()
    syms    = get_available_symbols(INTERVAL)
    btc_df  = load_historical("KRW-BTC", INTERVAL, START, END)

    all_data: dict[str, pd.DataFrame] = {}
    print(f"Fetching {len(syms)} symbols (workers={FETCH_WORKERS})...")
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = {ex.submit(fetch_symbol, s): s for s in syms}
        for f in as_completed(futs):
            sym, df = f.result()
            if df is not None:
                all_data[sym] = df
    print(f"Fetched {len(all_data)} symbols in {time.time()-t0:.1f}s")

    (C, O, H, L, V,
     btc_c, btc_o, btc_h, btc_l, btc_v,
     sym_list, common_len) = build_tensors(all_data, btc_df)

    n_windows = common_len - LOOKBACK

    print("Computing metrics on GPU...")
    t1 = time.time()
    rs, acc, cvd                       = alt_metrics(C, O, H, L, V, btc_c, n_windows)
    btc_raw_ret, btc_acc_t, btc_cvd_t  = btc_metrics(btc_c, btc_o, btc_h, btc_l, btc_v, n_windows)
    alt_fwd, valid_w                   = fwd_returns(C, n_windows)
    btc_fwd_np, _                      = btc_fwd_returns(btc_c, n_windows)
    bull_mask                          = btc_sma_regime(btc_df, common_len, n_windows)
    print(f"GPU done in {time.time()-t1:.2f}s")

    alt_fwd_np = alt_fwd.cpu().numpy()
    bull_pct   = bull_mask[:valid_w].mean() * 100
    print(f"Bull windows: {bull_pct:.1f}% | Valid windows: {valid_w}")

    # -- run analyses
    reg       = regime_analysis(rs, acc, cvd, alt_fwd_np, bull_mask, valid_w)
    grid      = threshold_grid(rs, acc, cvd, alt_fwd_np, valid_w)
    quart     = strength_quartiles(rs, acc, cvd, alt_fwd_np, valid_w)
    joint_q, btc_self = joint_analysis(
        rs, acc, cvd,
        btc_raw_ret, btc_acc_t, btc_cvd_t,
        alt_fwd_np, btc_fwd_np, valid_w,
    )

    # ── console ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"  [1] BTC Regime Split  (alt fwd=T+{FWD}봉)")
    print("=" * 70)
    for k, r in reg.items():
        if r["n"]:
            print(f"  {k:<22} n={r['n']:>5}  mean={r['mean_%']:>+7.3f}%  wr={r['win_rate']:.1%}")

    print("\n" + "=" * 70)
    print(f"  [2] Threshold Grid  (top 10 by edge)")
    print("=" * 70)
    print(f"  {'RS<':>5}  {'Acc>':>5}  {'N':>6}  {'Mean':>8}  {'WR':>7}  {'Edge':>8}")
    for r in grid[:10]:
        print(f"  {r['rs_thresh']:>5.1f}  {r['acc_thresh']:>5.1f}  {r['n']:>6}  "
              f"{r['mean_%']:>+7.3f}%  {r['win_rate']:>6.1%}  {r['edge_%']:>+7.3f}%")

    print("\n" + "=" * 70)
    print(f"  [3] Signal Strength Quartiles")
    print("=" * 70)
    for r in quart:
        print(f"  {r['quartile']:<22}  n={r['n']:>5}  mean={r['mean_%']:>+7.3f}%  wr={r['win_rate']:.1%}")

    print("\n" + "=" * 70)
    print(f"  [4] Joint BTC × Alt Stealth Quadrants  (fwd=T+{FWD}봉)")
    print("=" * 70)
    print(f"  {'Quadrant':<24}  {'Win':>5}  {'AltMean':>9}  {'AltWR':>7}  {'BTCMean':>9}  {'BTCWR':>7}")
    for r in joint_q:
        print(f"  {r['quadrant']:<24}  {r['windows']:>5}  "
              f"{r['alt_mean_%']:>+8.3f}%  {r['alt_wr']:>6.1%}  "
              f"{r['btc_mean_%']:>+8.3f}%  {r['btc_wr']:>6.1%}")

    print("\n  [BTC Stealth Self-Performance]")
    for label, _, vals in btc_self:
        s = stats(vals)
        print(f"  {label:<22} n={s['n']:>5}  mean={s['mean_%']:>+7.3f}%  wr={s['win_rate']:.1%}")

    # ── markdown save ─────────────────────────────────────────────────────────
    out = Path("artifacts/stealth-deep-result.md")
    out.parent.mkdir(exist_ok=True)
    with out.open("w") as f:
        f.write("# Stealth Signal Deep Analysis — BTC + Alt\n\n")
        f.write(f"실행: {pd.Timestamp.now().isoformat()}\n")
        f.write(f"Interval: {INTERVAL} | LB: {LOOKBACK}봉 | Fwd: T+{FWD}봉 | Symbols: {len(sym_list)}\n")
        f.write(f"Bull windows: {bull_pct:.1f}% of {valid_w} valid windows\n\n")

        f.write("## 1. BTC Regime Split (Alt Forward Returns)\n\n")
        f.write("| Group | N | AltMean | AltWR |\n|-------|---|---------|-------|\n")
        for k, r in reg.items():
            if r["n"]:
                f.write(f"| {k} | {r['n']} | {r['mean_%']:+.3f}% | {r['win_rate']:.1%} |\n")

        f.write("\n## 2. Threshold Grid (Top 15 by Edge)\n\n")
        f.write("| RS< | Acc> | N | Mean | WR | Edge |\n|-----|------|---|------|----|------|\n")
        for r in grid[:15]:
            f.write(f"| {r['rs_thresh']} | {r['acc_thresh']} | {r['n']} | "
                    f"{r['mean_%']:+.3f}% | {r['win_rate']:.1%} | {r['edge_%']:+.3f}% |\n")

        f.write("\n## 3. Signal Strength Quartiles\n\n")
        f.write("| Quartile | N | Mean | WR |\n|----------|---|------|----|\n")
        for r in quart:
            f.write(f"| {r['quartile']} | {r['n']} | {r['mean_%']:+.3f}% | {r['win_rate']:.1%} |\n")

        f.write(f"\n## 4. Joint BTC × Alt Stealth (fwd=T+{FWD}봉)\n\n")
        f.write("| Quadrant | Windows | AltMean | AltWR | BTCMean | BTCWR |\n"
                "|----------|---------|---------|-------|---------|-------|\n")
        for r in joint_q:
            f.write(f"| {r['quadrant']} | {r['windows']} | "
                    f"{r['alt_mean_%']:+.3f}% | {r['alt_wr']:.1%} | "
                    f"{r['btc_mean_%']:+.3f}% | {r['btc_wr']:.1%} |\n")

        f.write("\n### BTC Stealth Self-Performance\n\n")
        f.write("| State | N | BTCMean | BTCWR |\n|-------|---|---------|-------|\n")
        for label, _, vals in btc_self:
            s = stats(vals)
            f.write(f"| {label} | {s['n']} | {s['mean_%']:+.3f}% | {s['win_rate']:.1%} |\n")

        f.write("\n---\nAuto-generated by backtest_stealth_deep.py\n")

    print(f"\nReport saved → {out}")


if __name__ == "__main__":
    main()
