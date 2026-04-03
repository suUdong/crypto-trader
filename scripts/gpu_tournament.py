#!/usr/bin/env python3
"""
GPU Tournament — RTX 3080 전략 토너먼트

전체 KRW 심볼 (~244개) × 9개 전략을 GPU 텐서 연산으로 동시 처리.
CPU tournament 대비 ~100x 속도. 매 6h 자동 실행 (lab_loop 연동).

원리:
  entry[strategy, symbol, t] = 전략 조건 만족 여부  (n_strat, n_sym, T) bool tensor
  fwd_ret[symbol, t]         = t 시점 진입 후 hold_bars 뒤의 수익률
  edge = fwd_ret where entry=True  → 평균/분산/승률/Sharpe 계산

Usage:
    .venv/bin/python3 scripts/gpu_tournament.py          # 전체 실행
    .venv/bin/python3 scripts/gpu_tournament.py --quick  # 상위 50 symbols
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

# ── 설정 ─────────────────────────────────────────────────────────────────────

INTERVAL  = "minute240"  # 4h 봉
COUNT     = 180          # ~30일
HOLD_BARS = 12           # 진입 후 청산까지 봉 수 (48h)
FEE_PCT   = 0.05         # 수수료 0.05% × 2 (왕복)
MIN_TRADES = 10          # 최소 거래수
DEVICE    = "cuda" if torch.cuda.is_available() else "cpu"

# ── fetch ─────────────────────────────────────────────────────────────────────

def get_all_krw_symbols() -> list[str]:
    import pyupbit
    return pyupbit.get_tickers("KRW")


def _fetch_one(sym: str) -> tuple[str, object]:
    try:
        import pyupbit
        time.sleep(0.4)
        df = pyupbit.get_ohlcv(sym, interval=INTERVAL, count=COUNT)
        if df is None or len(df) < 60:
            return sym, None
        return sym, df
    except Exception as e:
        return sym, None


def fetch_all(symbols: list[str], workers: int = 3) -> dict:
    data: dict = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_one, s): s for s in symbols}
        for f in as_completed(futs):
            sym, df = f.result()
            if df is not None:
                data[sym] = df
    return data


# ── GPU 텐서 구성 ─────────────────────────────────────────────────────────────

def build_tensors(all_data: dict, btc_sym: str = "KRW-BTC"):
    # 데이터가 충분한 심볼만 사용 (중앙값 기준 70% 이상)
    lengths  = sorted(len(df) for df in all_data.values())
    median_T = lengths[len(lengths) // 2]
    min_T    = int(median_T * 0.7)
    all_data = {s: df for s, df in all_data.items() if len(df) >= min_T}
    # BTC는 항상 포함
    if btc_sym not in all_data:
        pass  # BTC 없으면 진행 불가 (상위에서 체크됨)

    symbols = list(all_data.keys())
    btc_idx = symbols.index(btc_sym) if btc_sym in symbols else 0

    T = min(len(df) for df in all_data.values())
    n = len(symbols)

    C = torch.zeros(n, T, device=DEVICE, dtype=torch.float32)
    V = torch.zeros(n, T, device=DEVICE, dtype=torch.float32)
    O = torch.zeros(n, T, device=DEVICE, dtype=torch.float32)

    for i, sym in enumerate(symbols):
        df = all_data[sym].iloc[-T:]
        C[i] = torch.tensor(df["close"].values,  dtype=torch.float32)
        V[i] = torch.tensor(df["volume"].values, dtype=torch.float32)
        O[i] = torch.tensor(df["open"].values,   dtype=torch.float32)

    return C, V, O, symbols, btc_idx, T


# ── GPU 피처 계산 ─────────────────────────────────────────────────────────────

def rolling_mean(x: torch.Tensor, w: int) -> torch.Tensor:
    """(n, T) → (n, T) rolling mean, 초반은 첫 값으로 패딩."""
    rm = x.unfold(1, w, 1).mean(dim=2)           # (n, T-w+1)
    pad = rm[:, :1].expand(-1, w - 1)             # (n, w-1)
    return torch.cat([pad, rm], dim=1)             # (n, T)


def rolling_mean_1d(x: torch.Tensor, w: int) -> torch.Tensor:
    """(T,) → (T,) rolling mean."""
    rm = x.unfold(0, w, 1).mean(dim=1)            # (T-w+1,)
    pad = rm[:1].expand(w - 1)
    return torch.cat([pad, rm])                    # (T,)


def compute_features(C: torch.Tensor, V: torch.Tensor, O: torch.Tensor,
                     btc_idx: int, T: int):
    """모든 피처를 GPU에서 한 번에 계산. (n, T) 텐서 반환."""
    btc_c = C[btc_idx]  # (T,)
    btc_v = V[btc_idx]

    # ── SMA ──────────────────────────────────────────────────────────────────
    sma20 = rolling_mean(C, 20)          # (n, T)
    sma50 = rolling_mean(C, 50)          # (n, T)
    btc_sma20 = rolling_mean_1d(btc_c, 20)  # (T,)

    # ── BTC 레짐 (SMA20 기준) ─────────────────────────────────────────────────
    btc_regime = (btc_c > btc_sma20)     # (T,) bool

    # ── 12봉 RS vs BTC ────────────────────────────────────────────────────────
    W = 12
    ret_sym = C[:, W:] / C[:, :-W].clamp(min=1e-9)   # (n, T-W)
    ret_btc = btc_c[W:] / btc_c[:-W].clamp(min=1e-9)  # (T-W,)
    rs = ret_sym / ret_btc.unsqueeze(0).clamp(min=1e-9) # (n, T-W)
    rs_full = F.pad(rs, (W, 0), value=1.0)              # (n, T)

    # ── Accumulation ─────────────────────────────────────────────────────────
    close_ma12 = rolling_mean(C, W).clamp(min=1e-9)
    vol_ma12   = rolling_mean(V, W).clamp(min=1e-9)
    acc = (C / close_ma12) * (V / vol_ma12)            # (n, T)

    # BTC stealth: 12봉 BTC 수익 < 0 AND btc_acc > 1.0
    btc_close_ma = rolling_mean_1d(btc_c, W).clamp(min=1e-9)
    btc_vol_ma   = rolling_mean_1d(btc_v, W).clamp(min=1e-9)
    btc_ret12    = btc_c / torch.roll(btc_c, W)
    btc_ret12[:W] = 1.0
    btc_acc = (btc_c / btc_close_ma) * (btc_v / btc_vol_ma)
    btc_stealth = (btc_ret12 < 1.0) & (btc_acc > 1.0)  # (T,)

    # ── RSI 14 ───────────────────────────────────────────────────────────────
    delta = C[:, 1:] - C[:, :-1]                       # (n, T-1)
    gain  = delta.clamp(min=0)
    loss  = (-delta).clamp(min=0)
    gain_ma = rolling_mean(gain, 14)                    # (n, T-1)
    loss_ma = rolling_mean(loss, 14).clamp(min=1e-9)
    rsi_raw = 100 - 100 / (1 + gain_ma / loss_ma)      # (n, T-1)
    rsi = F.pad(rsi_raw, (1, 0), value=50.0)            # (n, T)

    # ── 볼륨 MA20 ────────────────────────────────────────────────────────────
    vol_ma20 = rolling_mean(V, 20).clamp(min=1e-9)     # (n, T)

    # ── 5봉 가격 변화 ─────────────────────────────────────────────────────────
    price_up5 = C > torch.roll(C, 5, dims=1)           # (n, T) — 최근 5봉 대비 상승
    price_up5[:, :5] = False

    return {
        "btc_regime":  btc_regime,
        "btc_stealth": btc_stealth,
        "sma20":       sma20,
        "sma50":       sma50,
        "rs":          rs_full,
        "acc":         acc,
        "rsi":         rsi,
        "vol_ma20":    vol_ma20,
        "price_up5":   price_up5,
    }


# ── 전략 진입 신호 정의 ───────────────────────────────────────────────────────

def compute_entry_masks(C, V, feats, btc_idx) -> dict[str, torch.Tensor]:
    """각 전략의 진입 마스크 (n_sym, T) bool tensor."""
    regime    = feats["btc_regime"].unsqueeze(0)   # (1, T)
    stealth   = feats["btc_stealth"].unsqueeze(0)  # (1, T)
    rs        = feats["rs"]
    acc       = feats["acc"]
    rsi       = feats["rsi"]
    vol_ma20  = feats["vol_ma20"]
    price_up5 = feats["price_up5"]
    sma20     = feats["sma20"]
    sma50     = feats["sma50"]

    # BTC 자신 제외용 마스크
    n = C.shape[0]
    not_btc = torch.ones(n, dtype=torch.bool, device=DEVICE)
    not_btc[btc_idx] = False

    masks: dict[str, torch.Tensor] = {}

    # 1. 🔥 Stealth 3-gate: BTC>SMA20 + BTC stealth + Alt RS∈[0.7,1) acc>1
    m = regime & stealth & (rs >= 0.7) & (rs < 1.0) & (acc > 1.0)
    masks["stealth_3gate"] = m & not_btc.unsqueeze(1)

    # 2. Volume Breakout: 볼륨 2배 + 5봉 상승
    masks["volume_breakout"] = (V > vol_ma20 * 2.0) & price_up5

    # 3. RSI Oversold: RSI < 30 반등
    masks["rsi_oversold"] = (rsi < 30) & (rsi > 0)

    # 4. BTC Bull Momentum: BTC 불장 + 5봉 상승
    masks["btc_bull_momentum"] = regime & price_up5 & not_btc.unsqueeze(1)

    # 5. Dip in Uptrend: SMA50 위 + SMA20 아래 (눌림목)
    masks["dip_in_uptrend"] = (C > sma50) & (C < sma20)

    # 6. Accumulation Only: 강한 acc > 1.5
    masks["accumulation_only"] = acc > 1.5

    # 7. Low RS High Acc: 아직 안 오른 (RS<1) + 강한 acc>1.2
    masks["low_rs_high_acc"] = (rs < 1.0) & (rs > 0.5) & (acc > 1.2) & not_btc.unsqueeze(1)

    # 8. EMA Breakout: EMA12 > EMA26 (golden cross 대용)
    def ema(x, span):
        alpha = 2.0 / (span + 1)
        result = x.clone()
        for t in range(1, x.shape[1]):
            result[:, t] = alpha * x[:, t] + (1 - alpha) * result[:, t - 1]
        return result
    ema12 = ema(C, 12)
    ema26 = ema(C, 26)
    ema12_prev = torch.roll(ema12, 1, dims=1)
    ema26_prev = torch.roll(ema26, 1, dims=1)
    masks["ema_cross_bull"] = (ema12 > ema26) & (ema12_prev <= ema26_prev)

    # 9. High Volatility Contraction: ATR 수축 후 볼륨 급등 (변동성 눌림 포착)
    hi_lo = (C - torch.roll(C, 1, dims=1)).abs()   # 근사 ATR
    hi_lo[:, 0] = 0
    atr5  = rolling_mean(hi_lo, 5)
    atr20 = rolling_mean(hi_lo, 20).clamp(min=1e-9)
    vol_spike = V > vol_ma20 * 1.5
    masks["volatility_squeeze"] = (atr5 / atr20 < 0.7) & vol_spike

    return masks


# ── GPU 백테스트 평가 ─────────────────────────────────────────────────────────

def evaluate_strategy(entry: torch.Tensor, C: torch.Tensor,
                      hold: int = HOLD_BARS) -> dict | None:
    """
    entry (n_sym, T) bool → forward return 통계.
    주의: 간략화된 독립 거래 가정 (스크리닝 목적).
    """
    T = C.shape[1]
    if T <= hold:
        return None

    # forward return: (n_sym, T-hold)
    fwd = (C[:, hold:] / C[:, :-hold].clamp(min=1e-9) - 1.0) * 100
    fwd -= FEE_PCT  # 수수료 차감

    entry_trim = entry[:, :T - hold]  # (n_sym, T-hold)

    # 유효한 진입 시점만 선택
    trade_rets = fwd[entry_trim]   # 1D: 모든 (symbol, time) 진입의 수익률
    if len(trade_rets) < MIN_TRADES:
        return None

    mu     = trade_rets.mean().item()
    sigma  = trade_rets.std().item()
    if sigma < 0.01:
        return None

    n_trades = len(trade_rets)
    sharpe   = mu / sigma * math.sqrt(n_trades)
    win_rate = (trade_rets > 0).float().mean().item() * 100

    # avg return per trade (신뢰할 수 있는 edge 지표)
    avg_trade_ret = mu  # 거래당 평균 수익률 %

    # Max drawdown: 50개 샘플링 → 추정 (전체 sequential은 과장됨)
    sample_size = min(n_trades, 200)
    idx = torch.randperm(n_trades, device=DEVICE)[:sample_size]
    sample = trade_rets[idx]
    eq_sample = (1 + sample / 100).cumprod(dim=0)
    pk_sample = torch.cummax(eq_sample, dim=0).values
    max_dd = float(((eq_sample - pk_sample) / pk_sample.clamp(min=1e-9)).min().item() * 100)

    n_symbols = int(entry_trim.any(dim=1).sum().item())

    return {
        "avg_return":   avg_trade_ret,        # 거래당 평균 수익%
        "avg_wr":       win_rate,
        "avg_sharpe":   sharpe,
        "avg_dd":       abs(max_dd),
        "total_trades": n_trades,
        "n_symbols":    n_symbols,
    }


# ── 메인 실행 ─────────────────────────────────────────────────────────────────

def run_gpu_tournament(quick: bool = False) -> list[dict]:
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*64}")
    print(f"  GPU Strategy Tournament  |  {now_str}")
    print(f"  Device: {DEVICE.upper()}  |  Mode: {'quick (50)' if quick else 'full (all KRW)'}")
    print(f"{'='*64}")

    # 1. 심볼 목록
    print("\n[1/4] Getting KRW symbols...")
    all_syms = get_all_krw_symbols()
    symbols  = all_syms[:50] if quick else all_syms
    # BTC를 항상 포함
    if "KRW-BTC" not in symbols:
        symbols = ["KRW-BTC"] + list(symbols)
    print(f"  Target: {len(symbols)} symbols")

    # 2. 데이터 fetch
    print(f"\n[2/4] Fetching {len(symbols)} symbols (4h × {COUNT})...")
    t0 = time.time()
    all_data = fetch_all(symbols)
    # BTC 반드시 있어야 함
    if "KRW-BTC" not in all_data:
        print("ERROR: BTC 데이터 없음")
        return []
    print(f"  OK: {len(all_data)}/{len(symbols)} in {time.time()-t0:.1f}s")

    # 3. GPU 텐서 구성
    print(f"\n[3/4] Building GPU tensors...")
    t1 = time.time()
    C, V, O, sym_list, btc_idx, T = build_tensors(all_data)
    feats  = compute_features(C, V, O, btc_idx, T)
    masks  = compute_entry_masks(C, V, feats, btc_idx)
    print(f"  Tensor shape: {C.shape} | GPU time: {time.time()-t1:.2f}s")

    # 4. 전략별 평가
    print(f"\n[4/4] Evaluating {len(masks)} strategies...")
    leaderboard: list[dict] = []
    for name, entry in masks.items():
        r = evaluate_strategy(entry, C)
        if r:
            r["strategy"] = name
            leaderboard.append(r)
            n_sig = int(entry.sum().item())
            print(f"  {name:<22} signals={n_sig:<6} trades={r['total_trades']:<5} Sharpe={r['avg_sharpe']:+.3f}")
        else:
            n_sig = int(entry.sum().item()) if entry is not None else 0
            print(f"  {name:<22} signals={n_sig:<6} (insufficient trades)")

    leaderboard.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    # 출력
    print(f"\n{'─'*72}")
    print(f"{'#':<3} {'Strategy':<22} {'Sharpe':>7} {'WinRate':>8} {'Ret%':>7} {'DD%':>6} {'Trades':>7} {'Syms':>5}")
    print(f"{'─'*72}")
    medals = ["1st", "2nd", "3rd"]
    for i, r in enumerate(leaderboard):
        tag = medals[i] if i < 3 else f" {i+1}."
        print(
            f"{tag:<3} {r['strategy']:<22} {r['avg_sharpe']:>7.3f}"
            f" {r['avg_wr']:>7.1f}% {r['avg_return']:>6.2f}%"
            f" {r['avg_dd']:>5.1f}% {r['total_trades']:>7} {r['n_symbols']:>5}"
        )

    _save_leaderboard(leaderboard, len(all_data), quick, now_str)
    return leaderboard


def _save_leaderboard(leaderboard: list[dict], n_symbols: int, quick: bool, now_str: str) -> None:
    lb_path = _root / "docs" / "strategy_leaderboard.md"

    medals = ["🥇", "🥈", "🥉"]
    rows_md = ""
    for i, r in enumerate(leaderboard):
        tag = medals[i] if i < 3 else f"{i+1}."
        rows_md += (
            f"| {tag} | `{r['strategy']}` "
            f"| {r['avg_sharpe']:+.3f} | {r['avg_wr']:.1f}% "
            f"| {r['avg_return']:+.2f}% | {r['avg_dd']:.1f}% "
            f"| {r['total_trades']} | {r['n_symbols']} |\n"
        )

    mode_tag = f"GPU {'quick' if quick else 'full'}"
    section = (
        f"\n## {now_str}  `{mode_tag}`  {n_symbols} symbols\n\n"
        "| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |\n"
        "|---|---|:---:|:---:|:---:|:---:|:---:|:---:|\n"
        + rows_md
    )

    if lb_path.exists():
        existing = lb_path.read_text()
        parts = existing.split("\n## ")
        if len(parts) > 16:
            parts = parts[:1] + parts[-15:]
        lb_path.write_text("\n## ".join(parts) + section)
    else:
        lb_path.parent.mkdir(exist_ok=True)
        lb_path.write_text(
            "# Strategy Leaderboard\n\n자동 생성 — `gpu_tournament.py`\n" + section
        )

    print(f"\nLeaderboard → {lb_path.relative_to(_root)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="GPU Strategy Tournament")
    ap.add_argument("--quick", action="store_true", help="상위 50 symbols만 (빠른 테스트)")
    args = ap.parse_args()
    run_gpu_tournament(quick=args.quick)
