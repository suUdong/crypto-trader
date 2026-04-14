#!/usr/bin/env python3
"""Cycle 214: Kelly/half-Kelly 비대칭 포지션 사이징 포트폴리오 시뮬레이션.

평가자 [explore] 방향: c179/c199 OOS 거래별 수익률 분포로 Kelly fraction 산출
→ half-Kelly 적용 시 포트폴리오 CAGR/MDD 변화 시뮬레이션.

방법:
1. daemon 14개 활성 지갑별 backtest → per-trade pnl_pct + exit_time 추출
2. Kelly fraction = WR - (1-WR)/payoff 산출
3. 7가지 사이징 비교: Fixed(1%/2%) / Kelly / half-Kelly / quarter-Kelly / MV최적 / MV+HalfKelly
4. 포트폴리오 레벨 equity curve → CAGR, MDD, Sharpe, Calmar 비교
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass

import numpy as np
import pandas as pd

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root.parent / "src"))

from historical_loader import load_historical
from crypto_trader.backtest.engine import BacktestEngine, BacktestConfig
from crypto_trader.risk.manager import RiskManager
from crypto_trader.models import Candle
from crypto_trader.config import load_config
from crypto_trader.wallet import create_strategy

FEE = 0.0005
SLIPPAGE = 0.0005
START = "2024-01-01"
END = "2026-04-05"
TOTAL_CAPITAL = 8_900_000.0  # excl rsi_mr_bear (��1M)


@dataclass
class WalletDef:
    name: str
    strategy: str
    symbol: str
    initial_capital: float
    strategy_overrides: dict
    risk_overrides: dict
    timeframe: str = "60m"


WALLETS = [
    WalletDef("vpin_eth", "vpin", "KRW-ETH", 2_000_000,
        dict(rsi_period=14, momentum_lookback=8, max_holding_bars=36,
             vpin_low_threshold=0.35, vpin_high_threshold=0.55,
             vpin_momentum_threshold=0.0005, vpin_rsi_ceiling=65.0,
             vpin_rsi_floor=20.0, rsi_overbought=75.0, bucket_count=24,
             ema_trend_period=20, ema_weight=0.5, adx_threshold=15.0,
             btc_stealth_gate=False, active_regimes=["bull", "sideways", "bear"]),
        dict(stop_loss_pct=0.008, take_profit_pct=0.07, risk_per_trade_pct=0.01,
             partial_tp_pct=0.5, cooldown_bars=4, atr_stop_multiplier=0.0,
             atr_tp_multiplier=3.0, atr_sl_multiplier=0.5,
             vol_regime_lookback=120, vol_regime_threshold=40,
             hv_size_mult=0.5, hv_hold_bars=24, lv_hold_bars=12,
             hv_tp_offset=1.0, hv_sl_offset=0.2, lv_tp_offset=-0.5, lv_sl_offset=-0.1,
             trail_activate_atr_mult=1.8, trail_sl_atr_mult=0.4)),
    WalletDef("momentum_sol", "momentum", "KRW-SOL", 1_200_000,
        dict(momentum_lookback=12, momentum_entry_threshold=0.005,
             rsi_period=14, rsi_overbought=75.0, max_holding_bars=48,
             adx_threshold=25.0, volume_filter_mult=2.0,
             fear_greed_block_threshold=30, btc_stealth_gate=True,
             active_regimes=["bull"]),
        dict(stop_loss_pct=0.04, take_profit_pct=0.12, risk_per_trade_pct=0.015,
             atr_stop_multiplier=1.5, partial_tp_pct=0.5,
             max_concurrent_positions=2, max_position_pct=0.10)),
    WalletDef("volspike_btc", "volume_spike", "KRW-BTC", 1_000_000,
        dict(spike_mult=2.0, volume_window=20, min_body_ratio=0.2,
             momentum_lookback=12, rsi_period=14, rsi_overbought=72.0,
             max_holding_bars=36, adx_threshold=20.0,
             btc_stealth_gate=True, active_regimes=["bull"]),
        dict(stop_loss_pct=0.02, take_profit_pct=0.06, risk_per_trade_pct=0.01,
             atr_stop_multiplier=1.5, partial_tp_pct=0.5)),
    WalletDef("bb_squeeze_eth", "bb_squeeze_independent", "KRW-ETH", 500_000,
        dict(squeeze_pctile_th=40.0, squeeze_lb=15, upper_ratio=0.97,
             adx_threshold=25.0, tp_atr=5.0, sl_atr=2.0, max_hold=20,
             btc_stealth_gate=True),
        dict(stop_loss_pct=0.04, take_profit_pct=0.15, risk_per_trade_pct=0.02),
        timeframe="240m"),
    WalletDef("bb_squeeze_doge", "bb_squeeze_independent", "KRW-DOGE", 500_000,
        dict(squeeze_pctile_th=40.0, squeeze_lb=15, upper_ratio=0.97,
             adx_threshold=25.0, tp_atr=5.0, sl_atr=2.0, max_hold=20,
             btc_stealth_gate=True),
        dict(stop_loss_pct=0.04, take_profit_pct=0.15, risk_per_trade_pct=0.02),
        timeframe="240m"),
    WalletDef("bb_squeeze_sol", "bb_squeeze_independent", "KRW-SOL", 500_000,
        dict(squeeze_pctile_th=40.0, squeeze_lb=15, upper_ratio=0.97,
             adx_threshold=25.0, tp_atr=5.0, sl_atr=2.0, max_hold=20,
             btc_stealth_gate=True),
        dict(stop_loss_pct=0.04, take_profit_pct=0.15, risk_per_trade_pct=0.02),
        timeframe="240m"),
    WalletDef("vpin_sol", "vpin", "KRW-SOL", 500_000,
        dict(rsi_period=14, momentum_lookback=8, max_holding_bars=20,
             vpin_low_threshold=0.35, vpin_high_threshold=0.55,
             vpin_momentum_threshold=0.0007, vpin_rsi_ceiling=65.0,
             vpin_rsi_floor=20.0, rsi_overbought=75.0, bucket_count=24,
             ema_trend_period=20, ema_weight=0.5, adx_threshold=15.0,
             btc_stealth_gate=True, active_regimes=["bull", "sideways", "bear"]),
        dict(stop_loss_pct=0.008, take_profit_pct=0.07, risk_per_trade_pct=0.01,
             partial_tp_pct=0.5, cooldown_bars=4, atr_stop_multiplier=0.0,
             atr_tp_multiplier=5.0, atr_sl_multiplier=0.3,
             trail_activate_atr_mult=1.5, trail_sl_atr_mult=0.4)),
    WalletDef("vpin_xrp", "vpin", "KRW-XRP", 500_000,
        dict(rsi_period=14, momentum_lookback=8, max_holding_bars=20,
             vpin_low_threshold=0.35, vpin_high_threshold=0.55,
             vpin_momentum_threshold=0.0007, vpin_rsi_ceiling=65.0,
             vpin_rsi_floor=20.0, rsi_overbought=75.0, bucket_count=24,
             ema_trend_period=20, ema_weight=0.5, adx_threshold=15.0,
             btc_stealth_gate=True, active_regimes=["bull", "sideways", "bear"]),
        dict(stop_loss_pct=0.008, take_profit_pct=0.07, risk_per_trade_pct=0.01,
             partial_tp_pct=0.5, cooldown_bars=4, atr_stop_multiplier=0.0,
             atr_tp_multiplier=5.0, atr_sl_multiplier=0.3,
             trail_activate_atr_mult=1.5, trail_sl_atr_mult=0.4,
             max_position_pct=0.05)),
    WalletDef("vpin_doge", "vpin", "KRW-DOGE", 500_000,
        dict(rsi_period=14, momentum_lookback=8, max_holding_bars=20,
             vpin_low_threshold=0.40, vpin_high_threshold=0.55,
             vpin_momentum_threshold=0.0005, vpin_rsi_ceiling=65.0,
             vpin_rsi_floor=20.0, rsi_overbought=75.0, bucket_count=24,
             ema_trend_period=20, ema_weight=0.5, adx_threshold=15.0,
             btc_stealth_gate=True, active_regimes=["bull", "sideways", "bear"]),
        dict(stop_loss_pct=0.008, take_profit_pct=0.07, risk_per_trade_pct=0.01,
             partial_tp_pct=0.5, cooldown_bars=4, atr_stop_multiplier=0.0,
             atr_tp_multiplier=5.0, atr_sl_multiplier=0.3,
             trail_activate_atr_mult=1.5, trail_sl_atr_mult=0.4)),
    WalletDef("vpin_avax", "vpin", "KRW-AVAX", 500_000,
        dict(rsi_period=14, momentum_lookback=8, max_holding_bars=20,
             vpin_low_threshold=0.30, vpin_high_threshold=0.55,
             vpin_momentum_threshold=0.0005, vpin_rsi_ceiling=65.0,
             vpin_rsi_floor=20.0, rsi_overbought=75.0, bucket_count=24,
             ema_trend_period=20, ema_weight=0.5, adx_threshold=15.0,
             btc_stealth_gate=True, active_regimes=["bull", "sideways", "bear"]),
        dict(stop_loss_pct=0.008, take_profit_pct=0.07, risk_per_trade_pct=0.01,
             partial_tp_pct=0.5, cooldown_bars=4, atr_stop_multiplier=0.0,
             atr_tp_multiplier=5.0, atr_sl_multiplier=0.3,
             trail_activate_atr_mult=1.5, trail_sl_atr_mult=0.4,
             max_position_pct=0.05)),
    WalletDef("vpin_ondo", "vpin", "KRW-ONDO", 500_000,
        dict(rsi_period=14, momentum_lookback=8, max_holding_bars=18,
             vpin_low_threshold=0.45, vpin_high_threshold=0.55,
             vpin_momentum_threshold=0.0005, vpin_rsi_ceiling=65.0,
             vpin_rsi_floor=20.0, rsi_overbought=75.0, bucket_count=24,
             ema_trend_period=20, ema_weight=0.5, adx_threshold=15.0,
             btc_stealth_gate=True, btc_30bar_gate=True),
        dict(stop_loss_pct=0.015, take_profit_pct=0.10, risk_per_trade_pct=0.01,
             partial_tp_pct=0.5, cooldown_bars=4, atr_stop_multiplier=1.5)),
    # rsi_mr_bear wallets excluded: not yet registered in config.py valid_strategies
    # Their capital (₩1M) is excluded from simulation
]

# c211 mean-variance optimal weights
MV_OPTIMAL = {
    "bb_squeeze_eth": 0.232, "vpin_sol": 0.129, "vpin_xrp": 0.116,
    "vpin_eth": 0.080, "momentum_sol": 0.034, "volspike_btc": 0.048,
    "bb_squeeze_doge": 0.05, "bb_squeeze_sol": 0.05,
    "vpin_doge": 0.05, "vpin_avax": 0.05, "vpin_ondo": 0.05,
    "rsi_mr_bear_eth": 0.05, "rsi_mr_bear_btc": 0.041,
}


def df_to_candles(df: pd.DataFrame) -> list[Candle]:
    """Convert historical_loader DataFrame to list of Candle."""
    candles = []
    for ts, row in df.iterrows():
        t = ts.to_pydatetime()
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        candles.append(Candle(
            timestamp=t,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        ))
    return candles


_base_config = None

def _get_base_config():
    global _base_config
    if _base_config is None:
        config_path = _root.parent / "config" / "example.toml"
        _base_config = load_config(config_path, allow_missing_live_credentials=True)
    return _base_config


def make_config_and_strategy(wallet: WalletDef):
    """Create strategy and config from wallet definition."""
    import copy
    config = copy.deepcopy(_get_base_config())

    # Override strategy params on the config dataclass
    for k, v in wallet.strategy_overrides.items():
        if hasattr(config.strategy, k):
            try:
                target_type = type(getattr(config.strategy, k))
                if target_type == bool:
                    object.__setattr__(config.strategy, k, bool(v))
                elif target_type == list:
                    object.__setattr__(config.strategy, k, v)
                else:
                    object.__setattr__(config.strategy, k, target_type(v))
            except (ValueError, TypeError):
                object.__setattr__(config.strategy, k, v)
    for k, v in wallet.risk_overrides.items():
        if hasattr(config.risk, k):
            try:
                target_type = type(getattr(config.risk, k))
                object.__setattr__(config.risk, k, target_type(v))
            except (ValueError, TypeError):
                object.__setattr__(config.risk, k, v)

    strat = create_strategy(
        wallet.strategy, config.strategy, config.regime,
        extra_params=wallet.strategy_overrides,
    )
    return strat, config


def compute_kelly(pnl_pcts: list[float]) -> float:
    """Kelly = WR - (1-WR)/payoff. Clamped [0, 1]."""
    if len(pnl_pcts) < 5:
        return 0.0
    wins = [p for p in pnl_pcts if p > 0]
    losses = [abs(p) for p in pnl_pcts if p <= 0]
    wr = len(wins) / len(pnl_pcts)
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 1e-9
    if avg_loss == 0:
        return min(wr, 1.0)
    payoff = avg_win / avg_loss
    kelly = wr - (1 - wr) / payoff
    return max(0.0, min(kelly, 1.0))


def simulate_portfolio(
    wallet_trades: dict[str, list[tuple[datetime, float]]],
    sizing_fractions: dict[str, float],
    wallet_capitals: dict[str, float],
    total_capital: float,
) -> tuple[float, float, float, float, float]:
    """Simulate portfolio equity with given sizing.

    Returns: (final_equity, CAGR, MDD, Sharpe, Calmar)
    """
    all_trades: list[tuple[datetime, str, float]] = []
    for name, trades in wallet_trades.items():
        for t_time, pnl_pct in trades:
            all_trades.append((t_time, name, pnl_pct))
    all_trades.sort(key=lambda x: x[0])

    if not all_trades:
        return total_capital, 0.0, 0.0, 0.0, 0.0

    equity = total_capital
    equity_curve = [equity]
    peak = equity

    for _, wallet_name, pnl_pct in all_trades:
        frac = sizing_fractions.get(wallet_name, 0.01)
        w_cap = wallet_capitals.get(wallet_name, 0)
        # Position size scales with portfolio equity
        scale = equity / total_capital
        position_size = w_cap * frac * scale
        trade_pnl = position_size * pnl_pct
        equity += trade_pnl
        equity = max(equity, 1.0)
        equity_curve.append(equity)

    years = 2.25  # 2024-01 to 2026-04
    final = equity_curve[-1]
    total_ret = (final - total_capital) / total_capital
    cagr = (final / total_capital) ** (1 / years) - 1 if final > 0 else -1.0

    # MDD
    max_dd = 0.0
    pk = equity_curve[0]
    for eq in equity_curve:
        pk = max(pk, eq)
        dd = (pk - eq) / pk
        max_dd = max(max_dd, dd)

    # Sharpe (annualized from trade returns)
    arr = np.array(equity_curve)
    if len(arr) > 1:
        rets = np.diff(arr) / arr[:-1]
        std = float(np.std(rets))
        sharpe = float(np.mean(rets)) / std * np.sqrt(252) if std > 0 else 0.0
    else:
        sharpe = 0.0

    calmar = cagr / max_dd if max_dd > 0 else 0.0

    return final, cagr, max_dd, sharpe, calmar


def main():
    print("=" * 80)
    print("=== c214: Kelly/half-Kelly 비대칭 포지션 사이징 포트폴리오 시뮬레이션 ===")
    print(f"=== 기간: {START} ~ {END} | 슬리피지 {SLIPPAGE*100:.2f}% | 수수료 {FEE*100:.2f}% ===")
    print("=" * 80)

    # ── Step 1: Run backtests ──
    print(f"\n[1/4] 지갑별 백테스트 실행...")

    wallet_pnls: dict[str, list[float]] = {}
    wallet_trades: dict[str, list[tuple[datetime, float]]] = {}
    wallet_details: dict[str, dict] = {}

    for w in WALLETS:
        print(f"  {w.name:25s} ({w.symbol}, {w.timeframe})...", end=" ", flush=True)
        try:
            df = load_historical(w.symbol, w.timeframe, START, END)
        except FileNotFoundError:
            print(f"⚠️ 데이터 없음, skip")
            wallet_pnls[w.name] = []
            wallet_trades[w.name] = []
            continue

        if len(df) < 50:
            print(f"⚠️ {len(df)} candles, skip")
            wallet_pnls[w.name] = []
            wallet_trades[w.name] = []
            continue

        candles = df_to_candles(df)
        strat, config = make_config_and_strategy(w)

        bt_config = BacktestConfig(
            initial_capital=w.initial_capital,
            fee_rate=FEE,
            slippage_pct=SLIPPAGE,
        )
        risk_mgr = RiskManager(
            config.risk,
            trailing_stop_pct=config.risk.trailing_stop_pct,
            atr_stop_multiplier=config.risk.atr_stop_multiplier,
            max_holding_bars=int(w.strategy_overrides.get(
                "max_holding_bars", config.strategy.max_holding_bars)),
        )
        engine = BacktestEngine(strat, risk_mgr, bt_config, symbol=w.symbol)
        result = engine.run(candles)

        pnl_pcts = [t.pnl_pct for t in result.trade_log]
        timed = [(t.exit_time, t.pnl_pct) for t in result.trade_log]

        wallet_pnls[w.name] = pnl_pcts
        wallet_trades[w.name] = timed

        n = len(pnl_pcts)
        wr = sum(1 for p in pnl_pcts if p > 0) / n if n > 0 else 0
        avg = float(np.mean(pnl_pcts)) if pnl_pcts else 0
        wins = [p for p in pnl_pcts if p > 0]
        losses = [abs(p) for p in pnl_pcts if p <= 0]
        avg_w = float(np.mean(wins)) if wins else 0
        avg_l = float(np.mean(losses)) if losses else 0
        wallet_details[w.name] = dict(n=n, wr=wr, avg=avg, avg_win=avg_w, avg_loss=avg_l,
                                       sharpe=result.sharpe_ratio, mdd=result.max_drawdown)
        print(f"n={n:4d} WR={wr:5.1%} avg={avg:+.3%} Sharpe={result.sharpe_ratio:+.2f}")

    total_trades = sum(len(v) for v in wallet_pnls.values())
    print(f"\n  총 거래 수: {total_trades}")

    # ── Step 2: Kelly fractions ──
    print(f"\n[2/4] Kelly fraction 산출...")
    print(f"{'Wallet':25s} {'n':>4s} {'WR':>6s} {'Payoff':>7s} {'Kelly':>7s} {'H-K':>7s} {'Curr':>6s}")
    print("-" * 70)

    kelly_fracs: dict[str, float] = {}
    for w in WALLETS:
        k = compute_kelly(wallet_pnls[w.name])
        kelly_fracs[w.name] = k
        pnls = wallet_pnls[w.name]
        d = wallet_details.get(w.name, {})
        n = d.get("n", 0)
        wr = d.get("wr", 0)
        avg_w = d.get("avg_win", 0)
        avg_l = d.get("avg_loss", 0)
        payoff = avg_w / avg_l if avg_l > 0 else 0
        curr = w.risk_overrides.get("risk_per_trade_pct", 0.01)
        print(f"  {w.name:23s} {n:4d} {wr:5.1%} {payoff:6.2f}  {k:6.1%} {k/2:6.1%} {curr:5.1%}")

    # ── Step 3: Simulate schemes ──
    print(f"\n[3/4] 7가지 사이징 시뮬레이션...")

    wallet_caps = {w.name: w.initial_capital for w in WALLETS}
    mv_caps = {w.name: TOTAL_CAPITAL * MV_OPTIMAL.get(w.name, 0.05) for w in WALLETS}

    schemes: list[tuple[str, dict[str, float], dict[str, float]]] = [
        ("Fixed 1%", {w.name: 0.01 for w in WALLETS}, wallet_caps),
        ("Fixed 2%", {w.name: 0.02 for w in WALLETS}, wallet_caps),
        ("Kelly", {w.name: kelly_fracs[w.name] for w in WALLETS}, wallet_caps),
        ("Half-Kelly", {w.name: kelly_fracs[w.name] / 2 for w in WALLETS}, wallet_caps),
        ("Quarter-Kelly", {w.name: kelly_fracs[w.name] / 4 for w in WALLETS}, wallet_caps),
        ("MV-Opt+Fixed1%", {w.name: 0.01 for w in WALLETS}, mv_caps),
        ("MV-Opt+HalfKelly", {w.name: kelly_fracs[w.name] / 2 for w in WALLETS}, mv_caps),
    ]

    print(f"\n{'Scheme':22s} {'CAGR':>8s} {'MDD':>8s} {'Sharpe':>8s} {'Calmar':>8s} "
          f"{'Final₩':>14s} {'Return':>8s}")
    print("-" * 85)

    results: dict[str, tuple] = {}
    for name, fracs, caps in schemes:
        final, cagr, mdd, sharpe, calmar = simulate_portfolio(
            wallet_trades, fracs, caps, TOTAL_CAPITAL)
        ret = (final - TOTAL_CAPITAL) / TOTAL_CAPITAL
        results[name] = (cagr, mdd, sharpe, calmar, final, ret)
        print(f"  {name:20s} {cagr:+7.2%} {mdd:7.2%} {sharpe:+7.2f} {calmar:+7.2f} "
              f"₩{final:>12,.0f} {ret:+7.2%}")

    # ── Step 4: Analysis ──
    print(f"\n[4/4] 분석...")

    best_sharpe = max(results.items(), key=lambda x: x[1][2])
    best_calmar = max(results.items(), key=lambda x: x[1][3])
    best_return = max(results.items(), key=lambda x: x[1][5])

    print(f"\n  ★ Best Sharpe:  {best_sharpe[0]} → {best_sharpe[1][2]:+.2f}")
    print(f"  ★ Best Calmar:  {best_calmar[0]} → {best_calmar[1][3]:+.2f}")
    print(f"  ★ Best Return:  {best_return[0]} → {best_return[1][5]:+.2%}")

    # Fixed vs Kelly comparison
    f1 = results["Fixed 1%"]
    hk = results["Half-Kelly"]
    fk = results["Kelly"]
    mvhk = results["MV-Opt+HalfKelly"]

    print(f"\n  Fixed 1% → Half-Kelly:     Return Δ={hk[5]-f1[5]:+.2%}, MDD Δ={hk[1]-f1[1]:+.2%}")
    print(f"  Fixed 1% → Full Kelly:     Return Δ={fk[5]-f1[5]:+.2%}, MDD Δ={fk[1]-f1[1]:+.2%}")
    print(f"  Fixed 1% → MV+HalfKelly:   Return Δ={mvhk[5]-f1[5]:+.2%}, MDD Δ={mvhk[1]-f1[1]:+.2%}")

    # Per-wallet recommendation
    print(f"\n{'='*80}")
    print(f"=== 지갑별 사이징 권고 ===")
    print(f"{'Wallet':25s} {'Kelly':>7s} {'H-K':>7s} {'Curr':>6s} {'판정':10s}")
    print("-" * 65)
    for w in WALLETS:
        k = kelly_fracs[w.name]
        hk = k / 2
        curr = w.risk_overrides.get("risk_per_trade_pct", 0.01)
        n = len(wallet_pnls[w.name])
        if n < 10:
            verdict = "⚠️ n부족"
        elif k <= 0:
            verdict = "🔴 Kelly≤0"
        elif hk > curr * 2:
            verdict = "⬆️ 증액"
        elif hk < curr * 0.5:
            verdict = "⬇️ 감액"
        else:
            verdict = "✅ 적정"
        print(f"  {w.name:23s} {k:6.1%} {hk:6.1%} {curr:5.1%}  {verdict}")

    # BH comparison
    print(f"\n{'='*80}")
    print(f"=== Buy & Hold 대비 비교 ===")
    try:
        btc_df = load_historical("KRW-BTC", "60m", START, END)
        if len(btc_df) > 0:
            bh_ret = (btc_df.iloc[-1]["close"] - btc_df.iloc[0]["open"]) / btc_df.iloc[0]["open"]
            print(f"  BTC BH:           {bh_ret:+.2%}")
            print(f"  Half-Kelly:       {hk[5]:+.2%} (Δ={hk[5]-bh_ret:+.2%})")
            print(f"  MV+HalfKelly:     {mvhk[5]:+.2%} (Δ={mvhk[5]-bh_ret:+.2%})")
    except Exception as e:
        print(f"  BH 비교 불가: {e}")

    # Summary
    print(f"\n{'='*80}")
    print(f"=== 최종 요약 ===")
    print(f"★슬리피지포함 ({SLIPPAGE*100:.2f}%) | 수수료 {FEE*100:.2f}% | 🔄다음봉시가진입(engine)")
    print(f"기간: {START} ~ {END} | {len(WALLETS)} 지갑 | 총 {total_trades}거래")
    for name in ["Fixed 1%", "Half-Kelly", "Kelly", "MV-Opt+HalfKelly"]:
        c, m, s, cal, fin, r = results[name]
        print(f"  {name:22s}: Sharpe={s:+.2f} CAGR={c:+.2%} MDD={m:.2%} Return={r:+.2%}")


if __name__ == "__main__":
    main()
