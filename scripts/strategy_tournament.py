#!/usr/bin/env python3
"""
Strategy Tournament — continuous multi-strategy evaluation

모든 전략을 동일 데이터로 백테스트하여 Sharpe 기준 리더보드 생성.
결과 → docs/strategy_leaderboard.md (누적)

Usage:
    python scripts/strategy_tournament.py            # 전체 (20 symbols)
    python scripts/strategy_tournament.py --quick    # 빠른 테스트 (5 symbols)
    python scripts/strategy_tournament.py --days 60  # 기간 조정
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

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root))

# ── 설정 ─────────────────────────────────────────────────────────────────────

INTERVAL = "minute240"  # 4h 봉 — 30일 데이터, 단일 API 호출
COUNT    = 180          # ~30일 (4h × 180)
FEE_RATE = 0.0005       # 0.05% 수수료
MIN_TRADES = 5          # 최소 거래수 (미달 시 제외)

SYMBOLS_QUICK = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE",
]

SYMBOLS_FULL = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-SHIB",
    "KRW-TRX", "KRW-ALGO", "KRW-ICP",  "KRW-OP",  "KRW-INJ",
    "KRW-ATOM", "KRW-NEAR", "KRW-HBAR", "KRW-ARB", "KRW-ZIL",
]

# BacktestEngine을 사용하는 기존 전략들
ENGINE_STRATEGIES = [
    "momentum",
    "momentum_pullback",
    "volume_spike",
    "vpin",
    "bollinger_rsi",
    "ema_crossover",
    "volatility_breakout",
    "mean_reversion",
    "consensus",
]

# ── 데이터 fetch ──────────────────────────────────────────────────────────────

def _fetch_one(symbol: str, interval: str, count: int):
    try:
        import pyupbit
        time.sleep(0.5)
        df = pyupbit.get_ohlcv(symbol, interval=interval, count=count)
        if df is None or len(df) < 30:
            return symbol, None
        return symbol, df
    except Exception as e:
        print(f"  FETCH ERR {symbol}: {e}")
        return symbol, None


def fetch_all(symbols: list[str], interval: str = INTERVAL, count: int = COUNT) -> dict:
    data: dict = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_fetch_one, s, interval, count): s for s in symbols}
        for f in as_completed(futures):
            sym, df = f.result()
            if df is not None:
                data[sym] = df
    return data


# ── BacktestEngine 전략 실행 ──────────────────────────────────────────────────

def _df_to_candles(df):
    from crypto_trader.models import Candle
    return [
        Candle(
            timestamp=int(idx.timestamp() * 1000),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for idx, row in df.iterrows()
    ]


def run_engine_strategy(strategy_type: str, df, symbol: str) -> dict | None:
    from crypto_trader.backtest.engine import BacktestEngine
    from crypto_trader.config import BacktestConfig, RegimeConfig, RiskConfig, StrategyConfig
    from crypto_trader.risk.manager import RiskManager
    from scripts.grid_search import _create_strategy_for_grid

    try:
        candles = _df_to_candles(df)
        strategy = _create_strategy_for_grid(
            strategy_type, {}, StrategyConfig(), RegimeConfig()
        )
        engine = BacktestEngine(
            strategy=strategy,
            risk_manager=RiskManager(RiskConfig()),
            config=BacktestConfig(initial_capital=1_000_000.0, fee_rate=FEE_RATE, slippage_pct=FEE_RATE),
            symbol=symbol,
        )
        r = engine.run(candles)
        if r.trade_count == 0:
            return None
        return {
            "strategy":    strategy_type,
            "symbol":      symbol,
            "return_pct":  r.total_return_pct * 100,
            "win_rate":    r.win_rate * 100,
            "sharpe":      r.sharpe_ratio,
            "max_dd":      r.max_drawdown * 100,
            "trade_count": r.trade_count,
        }
    except Exception:
        return None


# ── 커스텀 전략 (numpy 벡터화) ────────────────────────────────────────────────

def _simple_backtest(entry: np.ndarray, closes: np.ndarray, hold_bars: int = 12) -> dict | None:
    """진입 마스크 기반 단순 백테스트. hold_bars 후 청산."""
    trades: list[float] = []
    in_trade = False
    entry_price = 0.0
    entry_i = 0

    for i in range(len(closes) - hold_bars):
        if not in_trade and entry[i]:
            in_trade    = True
            entry_price = closes[i] * (1 + FEE_RATE)
            entry_i     = i
        elif in_trade and (i - entry_i >= hold_bars):
            exit_price = closes[i] * (1 - FEE_RATE)
            trades.append((exit_price / entry_price - 1) * 100)
            in_trade   = False

    if len(trades) < MIN_TRADES:
        return None

    rets   = np.array(trades)
    mu     = rets.mean()
    sigma  = rets.std()
    # Sharpe: std가 너무 작으면 (0에 가까운 변동성) 신뢰할 수 없는 신호
    if sigma < 0.01:
        return None
    sharpe = mu / sigma * math.sqrt(len(rets))

    equity = np.cumprod(1 + rets / 100)
    peak   = np.maximum.accumulate(equity)
    max_dd = float(((equity - peak) / peak).min() * 100)

    return {
        "return_pct":  float((equity[-1] - 1) * 100),
        "win_rate":    float((rets > 0).mean() * 100),
        "sharpe":      float(sharpe),
        "max_dd":      abs(max_dd),
        "trade_count": len(trades),
    }


def _btc_regime(btc_c: np.ndarray, period: int = 20) -> np.ndarray:
    regime = np.zeros(len(btc_c))
    for i in range(period, len(btc_c)):
        regime[i] = 1 if btc_c[i] > btc_c[i - period:i].mean() else 0
    return regime


def _accumulation(closes: np.ndarray, volumes: np.ndarray, window: int = 12) -> np.ndarray:
    acc = np.ones(len(closes))
    for i in range(window, len(closes)):
        vol_avg = volumes[i - window:i].mean() + 1e-9
        acc[i]  = (closes[i] / closes[i - window:i].mean()) * (volumes[i] / vol_avg)
    return acc


def _rs_vs_btc(sym_c: np.ndarray, btc_c: np.ndarray, window: int = 12) -> np.ndarray:
    rs = np.ones(len(sym_c))
    for i in range(window, len(sym_c)):
        rs[i] = (sym_c[i] / sym_c[i - window]) / (btc_c[i] / btc_c[i - window] + 1e-9)
    return rs


# ── 커스텀 전략 정의 ──────────────────────────────────────────────────────────

def strat_stealth_3gate(sym_df, btc_df) -> dict | None:
    """
    3-gate Stealth: BTC>SMA20 + BTC stealth (net<0, acc>1) + Alt (RS∈[0.7,1.0), acc>1)
    Memory: 검증된 신호 (50.3% WR, 2026-04-02 기록)
    """
    n     = min(len(sym_df), len(btc_df))
    sym_c = sym_df["close"].values[-n:].astype(float)
    sym_v = sym_df["volume"].values[-n:].astype(float)
    btc_c = btc_df["close"].values[-n:].astype(float)
    btc_v = btc_df["volume"].values[-n:].astype(float)

    regime    = _btc_regime(btc_c)
    btc_ret12 = np.array([btc_c[i] / btc_c[max(0, i - 12)] for i in range(n)])
    btc_acc   = _accumulation(btc_c, btc_v)
    alt_rs    = _rs_vs_btc(sym_c, btc_c)
    alt_acc   = _accumulation(sym_c, sym_v)

    entry = (
        regime.astype(bool)
        & (btc_ret12 < 1.0)
        & (btc_acc > 1.0)
        & (alt_rs >= 0.7)
        & (alt_rs < 1.0)
        & (alt_acc > 1.0)
    )
    return _simple_backtest(entry, sym_c, hold_bars=12)


def strat_volume_breakout(sym_df, _btc_df) -> dict | None:
    """볼륨 2배 + 가격 상승 모멘텀"""
    closes  = sym_df["close"].values.astype(float)
    volumes = sym_df["volume"].values.astype(float)
    n       = len(closes)

    entry = np.zeros(n, dtype=bool)
    for i in range(20, n):
        vol_avg = volumes[i - 20:i].mean()
        if volumes[i] > vol_avg * 2.0 and closes[i] > closes[i - 5]:
            entry[i] = True
    return _simple_backtest(entry, closes, hold_bars=6)


def strat_rsi_oversold(sym_df, _btc_df) -> dict | None:
    """RSI < 30 반등"""
    closes = sym_df["close"].values.astype(float)
    n      = len(closes)
    period = 14

    rsi_vals = np.zeros(n)
    for i in range(period + 1, n):
        deltas = np.diff(closes[i - period - 1:i + 1])
        gain   = deltas[deltas > 0].mean() if (deltas > 0).any() else 0.0
        loss   = -deltas[deltas < 0].mean() if (deltas < 0).any() else 1e-9
        rsi_vals[i] = 100 - 100 / (1 + gain / loss)

    entry = (rsi_vals > 0) & (rsi_vals < 30)
    return _simple_backtest(entry, closes, hold_bars=6)


def strat_btc_bull_momentum(sym_df, btc_df) -> dict | None:
    """BTC bull 레짐 + 알트 5봉 상승"""
    n      = min(len(sym_df), len(btc_df))
    sym_c  = sym_df["close"].values[-n:].astype(float)
    btc_c  = btc_df["close"].values[-n:].astype(float)
    regime = _btc_regime(btc_c)

    entry = np.zeros(n, dtype=bool)
    for i in range(20, n):
        if regime[i] and sym_c[i] > sym_c[i - 5]:
            entry[i] = True
    return _simple_backtest(entry, sym_c, hold_bars=6)


def strat_dip_in_uptrend(sym_df, _btc_df) -> dict | None:
    """상승 추세 (SMA50 위) + 단기 눌림 (현가 < SMA20)"""
    closes = sym_df["close"].values.astype(float)
    n      = len(closes)

    entry = np.zeros(n, dtype=bool)
    for i in range(50, n):
        sma20 = closes[i - 20:i].mean()
        sma50 = closes[i - 50:i].mean()
        if closes[i] > sma50 and closes[i] < sma20:
            entry[i] = True
    return _simple_backtest(entry, closes, hold_bars=8)


def strat_accumulation_only(sym_df, _btc_df) -> dict | None:
    """acc > 1.5 — 강한 accumulation 신호만"""
    closes  = sym_df["close"].values.astype(float)
    volumes = sym_df["volume"].values.astype(float)
    acc     = _accumulation(closes, volumes)
    entry   = acc > 1.5
    return _simple_backtest(entry, closes, hold_bars=12)


def strat_low_rs_high_acc(sym_df, btc_df) -> dict | None:
    """아직 안 오른 (RS < 1.0) + 강한 acc > 1.2 — pre-breakout 포착"""
    n     = min(len(sym_df), len(btc_df))
    sym_c = sym_df["close"].values[-n:].astype(float)
    sym_v = sym_df["volume"].values[-n:].astype(float)
    btc_c = btc_df["close"].values[-n:].astype(float)

    rs  = _rs_vs_btc(sym_c, btc_c)
    acc = _accumulation(sym_c, sym_v)
    entry = (rs < 1.0) & (rs > 0.5) & (acc > 1.2)
    return _simple_backtest(entry, sym_c, hold_bars=12)


# 커스텀 전략 레지스트리 (이름 → 함수)
CUSTOM_STRATEGIES: dict[str, object] = {
    "stealth_3gate":      strat_stealth_3gate,
    "volume_breakout":    strat_volume_breakout,
    "rsi_oversold":       strat_rsi_oversold,
    "btc_bull_momentum":  strat_btc_bull_momentum,
    "dip_in_uptrend":     strat_dip_in_uptrend,
    "accumulation_only":  strat_accumulation_only,
    "low_rs_high_acc":    strat_low_rs_high_acc,
}

# ── 토너먼트 실행 ─────────────────────────────────────────────────────────────

def run_tournament(symbols: list[str], quick: bool = False) -> list[dict]:
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*64}")
    print(f"  Strategy Tournament  |  {now_str}")
    print(f"  Symbols: {len(symbols)}  |  Mode: {'quick' if quick else 'full'}")
    print(f"{'='*64}")

    # 1. 데이터 fetch (단일 1h 봉 — engine + custom 공용)
    print(f"\n[1/3] Fetching {len(symbols)} symbols ({INTERVAL}, count={COUNT})...")
    t0 = time.time()
    all_data = fetch_all(symbols)
    btc_df   = all_data.get("KRW-BTC")
    print(f"  OK: {len(all_data)}/{len(symbols)} symbols in {time.time()-t0:.1f}s")

    if btc_df is None:
        print("ERROR: BTC 데이터 없음 — 종료")
        return []

    # 2. 전략별 결과 수집
    results_by_strategy: dict[str, list[dict]] = {}

    # 2a. Engine 전략
    print(f"\n[2/3] Engine strategies ({len(ENGINE_STRATEGIES)})...")
    for strat in ENGINE_STRATEGIES:
        rows = []
        for sym, df in all_data.items():
            r = run_engine_strategy(strat, df, sym)
            if r:
                rows.append(r)
        if rows:
            results_by_strategy[strat] = rows
        status = f"OK ({len(rows)})" if rows else "no trades"
        print(f"  {strat:<22} {status}")

    # 2b. 커스텀 전략
    print(f"\n[2/3] Custom strategies ({len(CUSTOM_STRATEGIES)})...")
    for name, fn in CUSTOM_STRATEGIES.items():
        rows = []
        for sym, df in all_data.items():
            if sym == "KRW-BTC" and name in ("stealth_3gate", "btc_bull_momentum", "low_rs_high_acc"):
                continue  # BTC vs BTC 비교 무의미
            r = fn(df, btc_df)  # type: ignore[call-arg]
            if r:
                r["strategy"]    = name
                r["symbol"]      = sym
                rows.append(r)
        if rows:
            results_by_strategy[name] = rows
        status = f"OK ({len(rows)})" if rows else "no trades"
        print(f"  {name:<22} {status}")

    # 3. 집계 & 리더보드 생성
    print(f"\n[3/3] Aggregating...")
    leaderboard: list[dict] = []
    for strat_name, rows in results_by_strategy.items():
        if not rows:
            continue
        leaderboard.append({
            "strategy":    strat_name,
            "avg_return":  float(np.mean([r["return_pct"]  for r in rows])),
            "avg_wr":      float(np.mean([r["win_rate"]     for r in rows])),
            "avg_sharpe":  float(np.mean([r["sharpe"]       for r in rows])),
            "avg_dd":      float(np.mean([r["max_dd"]       for r in rows])),
            "total_trades":int(sum(r["trade_count"] for r in rows)),
            "n_symbols":   len(rows),
        })

    leaderboard.sort(key=lambda x: x["avg_sharpe"], reverse=True)

    # 출력
    print(f"\n{'─'*72}")
    print(f"{'#':<3} {'Strategy':<22} {'Sharpe':>7} {'WinRate':>8} {'Ret%':>7} {'DD%':>6} {'Trades':>7}")
    print(f"{'─'*72}")
    medals = ["1st", "2nd", "3rd"]
    for i, r in enumerate(leaderboard):
        tag = medals[i] if i < 3 else f" {i+1}."
        print(
            f"{tag:<3} {r['strategy']:<22} {r['avg_sharpe']:>7.3f}"
            f" {r['avg_wr']:>7.1f}% {r['avg_return']:>6.2f}% {r['avg_dd']:>5.1f}%"
            f" {r['total_trades']:>7}"
        )

    _save_leaderboard(leaderboard, symbols, quick, now_str)
    return leaderboard


# ── 리더보드 저장 ─────────────────────────────────────────────────────────────

def _save_leaderboard(leaderboard: list[dict], symbols: list[str], quick: bool, now_str: str) -> None:
    lb_path = _root / "docs" / "strategy_leaderboard.md"

    rows_md = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(leaderboard):
        tag = medals[i] if i < 3 else f"{i+1}."
        rows_md += (
            f"| {tag} | `{r['strategy']}` "
            f"| {r['avg_sharpe']:+.3f} | {r['avg_wr']:.1f}% "
            f"| {r['avg_return']:+.2f}% | {r['avg_dd']:.1f}% "
            f"| {r['total_trades']} | {r['n_symbols']} |\n"
        )

    mode_tag = "quick" if quick else "full"
    section = (
        f"\n## {now_str}  `{mode_tag}`  {len(symbols)} symbols\n\n"
        "| # | Strategy | Sharpe | WinRate | AvgRet% | MaxDD% | Trades | Syms |\n"
        "|---|---|:---:|:---:|:---:|:---:|:---:|:---:|\n"
        + rows_md
    )

    if lb_path.exists():
        existing = lb_path.read_text()
        # 최근 15 세션만 보관
        parts = existing.split("\n## ")
        if len(parts) > 16:
            parts = parts[:1] + parts[-15:]
        lb_path.write_text("\n## ".join(parts) + section)
    else:
        lb_path.parent.mkdir(exist_ok=True)
        lb_path.write_text(
            "# Strategy Leaderboard\n\n"
            "자동 생성 — `scripts/strategy_tournament.py`  \n"
            "Sharpe 기준 정렬. 매 실행마다 누적 기록.\n"
            + section
        )

    print(f"\nLeaderboard → {lb_path.relative_to(_root)}")


# ── 새 전략 등록 도우미 ───────────────────────────────────────────────────────

def register_custom_strategy(name: str, fn) -> None:
    """외부에서 커스텀 전략 추가할 때 사용."""
    CUSTOM_STRATEGIES[name] = fn


# ── entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Strategy Tournament")
    ap.add_argument("--quick", action="store_true", help="5 symbols only (fast)")
    ap.add_argument("--days",  type=int, default=30, help="Backtest period in days")
    args = ap.parse_args()

    syms = SYMBOLS_QUICK if args.quick else SYMBOLS_FULL
    run_tournament(syms, quick=args.quick)
