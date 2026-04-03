#!/usr/bin/env python3
"""
불장 필터 백테스트 — 전체 기간 vs 불장 구간 전략 성과 비교

artifacts/bull_periods.json 의 일봉 자동 감지 구간을 사용해
GPU tournament 전략들의 불장 vs 전체 성과를 비교합니다.

Usage:
    .venv/bin/python3 scripts/backtest_bull_filter.py
"""
from __future__ import annotations

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, UTC
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root / "scripts"))
from historical_loader import load_historical

ARTIFACTS  = _root / "artifacts"
BULL_JSON  = ARTIFACTS / "bull_periods.json"
OUTPUT_MD  = _root / "docs" / "backtest_history.md"

INTERVAL   = "240m"        # 4h 봉
START      = "2022-01-01"
END        = "2026-12-31"
HOLD_BARS  = 12            # 48h hold
FEE_PCT    = 0.05
MIN_TRADES = 5
DEVICE     = "cuda" if torch.cuda.is_available() else "cpu"

SYMBOLS = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-SHIB",
    "KRW-TRX", "KRW-ALGO", "KRW-ICP",  "KRW-OP",  "KRW-INJ",
    "KRW-ATOM", "KRW-NEAR", "KRW-HBAR", "KRW-ARB", "KRW-ZIL",
    "KRW-MON",  "KRW-DEEP", "KRW-POKT", "KRW-AWE", "KRW-SYRUP",
]

# ── 불장 기간 로드 ────────────────────────────────────────────────────────────

def load_bull_periods() -> list[dict]:
    if not BULL_JSON.exists():
        print("  WARNING: bull_periods.json 없음 — identify_bull_periods.py 먼저 실행하세요")
        return []
    with open(BULL_JSON) as f:
        data = json.load(f)
    return data.get("phase2_daily_auto", [])


def build_bull_mask_4h(df_index: pd.DatetimeIndex, bull_periods: list[dict]) -> np.ndarray:
    """4h 캔들 인덱스에 불장 구간을 bool 마스크로 변환."""
    mask = np.zeros(len(df_index), dtype=bool)
    for p in bull_periods:
        if p.get("end") == "ongoing":
            end_dt = pd.Timestamp.now(tz="UTC")
        else:
            end_dt = pd.Timestamp(p["end"], tz="UTC")
        start_dt = pd.Timestamp(p["start"], tz="UTC")

        # 인덱스가 tz-naive인 경우 처리
        if df_index.tz is None:
            start_dt = start_dt.tz_localize(None)
            end_dt   = end_dt.tz_localize(None)

        mask |= (df_index >= start_dt) & (df_index <= end_dt)
    return mask


# ── 데이터 fetch ──────────────────────────────────────────────────────────────

def _fetch_one(sym: str) -> tuple[str, object]:
    try:
        df = load_historical(sym, INTERVAL, START, END)
        if df is None or df.empty:
            return sym, None
        return sym, df
    except Exception as e:
        return sym, None




def fetch_all(symbols: list[str]) -> dict:
    data = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(_fetch_one, s): s for s in symbols}
        for f in as_completed(futs):
            sym, df = f.result()
            if df is not None:
                data[sym] = df
    return data


# ── GPU 피처 계산 (gpu_tournament.py 동일) ───────────────────────────────────

def rolling_mean(x: torch.Tensor, w: int) -> torch.Tensor:
    rm = x.unfold(1, w, 1).mean(dim=2)
    pad = rm[:, :1].expand(-1, w - 1)
    return torch.cat([pad, rm], dim=1)


def rolling_mean_1d(x: torch.Tensor, w: int) -> torch.Tensor:
    rm = x.unfold(0, w, 1).mean(dim=1)
    pad = rm[:1].expand(w - 1)
    return torch.cat([pad, rm])


def build_tensors_and_features(all_data: dict):
    # 충분한 데이터만 사용 (최소 300봉)
    all_data = {s: df for s, df in all_data.items() if len(df) >= 300}
    if "KRW-BTC" not in all_data:
        return None

    symbols = list(all_data.keys())
    btc_idx = symbols.index("KRW-BTC")
    lengths = sorted(len(df) for df in all_data.values())
    T = lengths[len(lengths) // 2]  # 중앙값으로 통일
    all_data = {s: df for s, df in all_data.items() if len(df) >= int(T * 0.7)}
    symbols = list(all_data.keys())
    btc_idx = symbols.index("KRW-BTC") if "KRW-BTC" in symbols else 0
    T = min(len(df) for df in all_data.values())

    n = len(symbols)
    C = torch.zeros(n, T, device=DEVICE, dtype=torch.float32)
    V = torch.zeros(n, T, device=DEVICE, dtype=torch.float32)
    O = torch.zeros(n, T, device=DEVICE, dtype=torch.float32)
    dates = None

    for i, sym in enumerate(symbols):
        df = all_data[sym].iloc[-T:]
        if i == btc_idx:
            dates = df.index
        C[i] = torch.tensor(df["close"].values,  dtype=torch.float32)
        V[i] = torch.tensor(df["volume"].values, dtype=torch.float32)
        O[i] = torch.tensor(df["open"].values,   dtype=torch.float32)

    btc_c = C[btc_idx]
    btc_v = V[btc_idx]

    # Features
    sma20     = rolling_mean(C, 20)
    sma50     = rolling_mean(C, 50)
    btc_sma20 = rolling_mean_1d(btc_c, 20)
    btc_regime = (btc_c > btc_sma20)

    W = 12
    ret_sym = C[:, W:] / C[:, :-W].clamp(min=1e-9)
    ret_btc = btc_c[W:] / btc_c[:-W].clamp(min=1e-9)
    rs = ret_sym / ret_btc.unsqueeze(0).clamp(min=1e-9)
    rs_full = F.pad(rs, (W, 0), value=1.0)

    close_ma12 = rolling_mean(C, W).clamp(min=1e-9)
    vol_ma12   = rolling_mean(V, W).clamp(min=1e-9)
    acc = (C / close_ma12) * (V / vol_ma12)

    btc_close_ma = rolling_mean_1d(btc_c, W).clamp(min=1e-9)
    btc_vol_ma   = rolling_mean_1d(btc_v, W).clamp(min=1e-9)
    btc_ret12    = btc_c / torch.roll(btc_c, W)
    btc_ret12[:W] = 1.0
    btc_acc = (btc_c / btc_close_ma) * (btc_v / btc_vol_ma)
    btc_stealth = (btc_ret12 < 1.0) & (btc_acc > 1.0)

    delta   = C[:, 1:] - C[:, :-1]
    gain    = delta.clamp(min=0)
    loss    = (-delta).clamp(min=0)
    gain_ma = rolling_mean(gain, 14)
    loss_ma = rolling_mean(loss, 14).clamp(min=1e-9)
    rsi     = F.pad(100 - 100 / (1 + gain_ma / loss_ma), (1, 0), value=50.0)

    vol_ma20  = rolling_mean(V, 20).clamp(min=1e-9)
    price_up5 = C > torch.roll(C, 5, dims=1)
    price_up5[:, :5] = False

    not_btc = torch.ones(n, dtype=torch.bool, device=DEVICE)
    not_btc[btc_idx] = False

    regime  = btc_regime.unsqueeze(0)
    stealth = btc_stealth.unsqueeze(0)

    masks = {
        "stealth_3gate":   regime & stealth & (rs_full >= 0.7) & (rs_full < 1.0) & (acc > 1.0) & not_btc.unsqueeze(1),
        "rsi_oversold":    (rsi < 30) & (rsi > 0),
        "low_rs_high_acc": (rs_full < 1.0) & (rs_full > 0.5) & (acc > 1.2) & not_btc.unsqueeze(1),
        "volume_breakout": (V > vol_ma20 * 2.0) & price_up5,
        "btc_bull_momentum": regime & price_up5 & not_btc.unsqueeze(1),
        "accumulation_only": acc > 1.5,
    }

    return C, masks, symbols, btc_idx, T, dates


# ── 백테스트 평가 ─────────────────────────────────────────────────────────────

def evaluate(entry: torch.Tensor, C: torch.Tensor,
             time_filter: torch.Tensor | None = None,
             hold: int = HOLD_BARS) -> dict | None:
    """
    entry (n, T), C (n, T), time_filter (T,) bool
    time_filter=None → 전체 기간
    time_filter=mask → 해당 시점만 진입 허용
    """
    T = C.shape[1]
    if T <= hold:
        return None

    fwd = (C[:, hold:] / C[:, :-hold].clamp(min=1e-9) - 1.0) * 100 - FEE_PCT
    entry_trim = entry[:, :T - hold].clone()

    if time_filter is not None:
        tf = time_filter[:T - hold]  # (T-hold,)
        entry_trim = entry_trim & tf.unsqueeze(0)

    trades = fwd[entry_trim]
    if len(trades) < MIN_TRADES:
        return None

    mu     = trades.mean().item()
    sigma  = trades.std().item()
    if sigma < 0.01:
        return None

    n_t    = len(trades)
    sharpe = mu / sigma * math.sqrt(n_t)
    wr     = (trades > 0).float().mean().item() * 100
    n_sym  = int(entry_trim.any(dim=1).sum().item())

    return {"sharpe": sharpe, "wr": wr, "avg_ret": mu, "n_trades": n_t, "n_syms": n_sym}


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*64}")
    print(f"  불장 필터 백테스트  |  {now_str}")
    print(f"  전체 기간 vs 불장 구간 비교")
    print(f"{'='*64}")

    # 불장 구간 로드
    bull_periods = load_bull_periods()
    if not bull_periods:
        print("bull_periods.json 없음 — identify_bull_periods.py 먼저 실행")
        return
    print(f"\n불장 구간 {len(bull_periods)}개 로드:")
    for p in bull_periods:
        print(f"  {p['start']} ~ {p['end']} ({p['duration_days']}일, +{p['gain_pct']:.1f}%)")

    # 데이터 fetch
    print(f"\n[1/3] Fetching {len(SYMBOLS)} symbols (4h × ~2500봉)...")
    t0 = time.time()
    all_data = fetch_all(SYMBOLS)
    print(f"  OK: {len(all_data)}/{len(SYMBOLS)} in {time.time()-t0:.1f}s")

    # GPU 텐서 + 피처
    print("\n[2/3] GPU 텐서 구성 및 전략 신호 계산...")
    result = build_tensors_and_features(all_data)
    if result is None:
        print("ERROR: BTC 데이터 없음")
        return
    C, masks, symbols, btc_idx, T, dates = result
    print(f"  Tensor: {C.shape} | Device: {DEVICE}")

    # 불장 마스크 (4h 인덱스 기준)
    bull_mask_np = build_bull_mask_4h(dates, bull_periods)
    bull_mask    = torch.tensor(bull_mask_np[-T:], device=DEVICE, dtype=torch.bool)
    bull_ratio   = bull_mask.float().mean().item() * 100
    print(f"  불장 비율: {bull_ratio:.1f}% ({bull_mask.sum().item()}/{T}봉)")

    # 전략별 평가
    print("\n[3/3] 전략 평가 — 전체 vs 불장...")

    rows = []
    for name, entry in masks.items():
        full = evaluate(entry, C, time_filter=None)
        bull = evaluate(entry, C, time_filter=bull_mask)

        rows.append((name, full, bull))

    # 출력 (Sharpe 기준 정렬)
    rows.sort(key=lambda x: (x[2]["sharpe"] if x[2] else -99), reverse=True)

    header = f"\n{'Strategy':<22} {'── 전체 기간 ──':^32}   {'── 불장 기간만 ──':^32}"
    sub    = f"{'':22} {'Sharpe':>7} {'WR':>7} {'AvgRet':>7} {'Trades':>7}   {'Sharpe':>7} {'WR':>7} {'AvgRet':>7} {'Trades':>7}"
    print(header)
    print(sub)
    print("─" * 82)

    for name, full, bull in rows:
        def fmt(r):
            if r is None:
                return f"{'N/A':>7} {'N/A':>7} {'N/A':>7} {'N/A':>7}"
            return (f"{r['sharpe']:>7.3f} {r['wr']:>6.1f}% {r['avg_ret']:>6.2f}% {r['n_trades']:>7}")

        # 불장이 더 좋으면 표시
        imp = ""
        if full and bull:
            diff = bull["sharpe"] - full["sharpe"]
            imp  = f"  {'↑' if diff > 0 else '↓'}{abs(diff):.2f}"

        print(f"  {name:<22} {fmt(full)}   {fmt(bull)}{imp}")

    # 결과 저장 (backtest_history.md 추가)
    _append_to_history(rows, bull_periods, bull_ratio, now_str)


def _append_to_history(rows, bull_periods, bull_ratio, now_str):
    hist_path = OUTPUT_MD
    bull_list = ", ".join(f"{p['start']}~{p['end']}" for p in bull_periods)

    lines = [
        f"\n## {now_str} — 불장 필터 비교 백테스트\n",
        f"**불장 구간**: {bull_list}  \n",
        f"**불장 비율**: {bull_ratio:.1f}%  \n",
        f"**데이터**: 4h봉 ~400일, {len(SYMBOLS)} symbols\n\n",
        "| 전략 | 전체Sharpe | 불장Sharpe | 전체WR | 불장WR | 전체Trades | 불장Trades | 개선 |\n",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n",
    ]
    for name, full, bull in rows:
        fs = f"{full['sharpe']:+.3f}" if full else "N/A"
        bs = f"{bull['sharpe']:+.3f}" if bull else "N/A"
        fw = f"{full['wr']:.1f}%" if full else "N/A"
        bw = f"{bull['wr']:.1f}%" if bull else "N/A"
        ft = str(full['n_trades']) if full else "N/A"
        bt = str(bull['n_trades']) if bull else "N/A"
        if full and bull:
            diff = bull['sharpe'] - full['sharpe']
            imp  = f"{'↑' if diff > 0 else '↓'}{abs(diff):.2f}"
        else:
            imp = "—"
        lines.append(f"| `{name}` | {fs} | {bs} | {fw} | {bw} | {ft} | {bt} | {imp} |\n")

    lines.append("\n**결론**: 불장 Sharpe > 전체 Sharpe 인 전략이 불장 로테이션에 적합.\n")

    if hist_path.exists():
        with open(hist_path, "a") as f:
            f.writelines(lines)
    print(f"\nbacktest_history.md 추가 완료")


if __name__ == "__main__":
    main()
