"""
사이클 211 — Daemon 포트폴리오 상관관계 분석

평가자 방향: 단일 전략 최적화는 구조적 한계. 포트폴리오 레벨 분석 실행.
목적:
  1. daemon 9개 지갑 각각의 일별 수익률 시계열 추출 (240m 백테스트)
  2. 상관행렬 계산 — 상관 > 0.7 인 쌍 식별
  3. 동시 MDD 분석 — 포트폴리오 드로다운 vs 개별 전략 드로다운
  4. mean-variance 최적 가중치 산출 — 현 자본 배분 vs 최적 비교
  5. Kelly/half-Kelly fraction 참고 산출

기간: 2024-01-01 ~ 2026-04-05 (공통 OOS 기간)
★슬리피지포함 | 🔄다음봉시가진입 (engine 기본)
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Project imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from historical_loader import load_historical

from crypto_trader.config import (
    AppConfig,
    BacktestConfig,
    RiskConfig,
    WalletConfig,
    load_config,
)
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.models import Candle
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import create_strategy

# ── Config ──
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "daemon.toml"
START = "2024-01-01"
END = "2026-04-05"
CTYPE = "240m"  # 4h candles — main daemon timeframe

# Wallets that need 60m data (accumulation_breakout uses 15m but we only have 60m/240m)
# accumulation_breakout wallets are on minute60 per daemon config comments
WALLET_CTYPE_OVERRIDE: dict[str, str] = {
    "accumulation_dood_wallet": "60m",
    "accumulation_tree_wallet": "60m",
}


def _df_to_candles(df: pd.DataFrame, symbol: str) -> list[Candle]:
    """Convert DataFrame to list of Candle objects."""
    candles: list[Candle] = []
    for ts, row in df.iterrows():
        candles.append(
            Candle(
                timestamp=ts.to_pydatetime(),  # type: ignore[union-attr]
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return candles


def _apply_strategy_overrides(base_cfg: Any, overrides: dict[str, Any]) -> Any:
    """Apply wallet strategy_overrides to StrategyConfig."""
    fields = set(type(base_cfg).__dataclass_fields__)
    valid = {k: v for k, v in overrides.items() if k in fields}
    return replace(base_cfg, **valid)


def _apply_risk_overrides(base_cfg: RiskConfig, overrides: dict[str, Any]) -> RiskConfig:
    """Apply wallet risk_overrides to RiskConfig."""
    fields = set(type(base_cfg).__dataclass_fields__)
    valid = {k: v for k, v in overrides.items() if k in fields}
    return replace(base_cfg, **valid)


def run_wallet_backtest(
    app_config: AppConfig,
    wallet: WalletConfig,
) -> dict[str, Any]:
    """Run backtest for a single wallet, return trade log + equity curve."""
    symbol = wallet.symbols[0] if wallet.symbols else "KRW-BTC"
    ctype = WALLET_CTYPE_OVERRIDE.get(wallet.name, CTYPE)

    print(f"  [{wallet.name}] Loading {symbol} {ctype} data...")
    df = load_historical(symbol, ctype, START, END)
    if df.empty:
        print(f"  [{wallet.name}] ⚠ No data for {symbol} {ctype}")
        return {"name": wallet.name, "trades": [], "equity_curve": [], "symbol": symbol}

    candles = _df_to_candles(df, symbol)
    print(f"  [{wallet.name}] {len(candles)} candles loaded")

    # Apply overrides
    strat_cfg = _apply_strategy_overrides(app_config.strategy, wallet.strategy_overrides)
    risk_cfg = _apply_risk_overrides(app_config.risk, wallet.risk_overrides)

    # Create strategy
    strategy = create_strategy(
        wallet.strategy,
        strat_cfg,
        app_config.regime,
        extra_params=wallet.strategy_overrides,
    )

    # Create risk manager + backtest config
    bt_config = BacktestConfig(
        initial_capital=wallet.initial_capital,
        fee_rate=0.0005,
        slippage_pct=0.0005,
    )
    max_hold = int(wallet.strategy_overrides.get(
        "max_holding_bars", strat_cfg.max_holding_bars
    ))
    risk_manager = RiskManager(
        risk_cfg,
        trailing_stop_pct=risk_cfg.trailing_stop_pct,
        atr_stop_multiplier=risk_cfg.atr_stop_multiplier,
        max_holding_bars=max_hold,
    )

    # Run backtest
    engine = BacktestEngine(
        strategy=strategy,
        risk_manager=risk_manager,
        config=bt_config,
        symbol=symbol,
        regime_aware=True,
    )
    result = engine.run(candles)

    trades = []
    for t in result.trade_log:
        trades.append({
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "pnl_pct": t.pnl_pct,
            "pnl": t.pnl,
        })

    return {
        "name": wallet.name,
        "symbol": symbol,
        "strategy": wallet.strategy,
        "trades": trades,
        "n_trades": len(trades),
        "total_return_pct": result.total_return_pct,
        "sharpe": result.sharpe_ratio,
        "win_rate": result.win_rate,
        "max_drawdown": result.max_drawdown,
        "equity_curve": list(result.equity_curve),
    }


def trades_to_daily_returns(
    trades: list[dict[str, Any]],
    initial_capital: float,
) -> pd.Series:
    """Convert trade log to daily return series.

    Allocate each trade's P&L proportionally across its holding days,
    then sum up daily P&L and divide by capital for daily return.
    """
    if not trades:
        return pd.Series(dtype=float)

    daily_pnl: dict[str, float] = {}
    for t in trades:
        entry = pd.Timestamp(t["entry_time"])
        exit_ = pd.Timestamp(t["exit_time"])
        pnl = t["pnl"]

        # Spread P&L across holding days
        days = pd.date_range(entry.normalize(), exit_.normalize(), freq="D")
        if len(days) == 0:
            day_str = entry.strftime("%Y-%m-%d")
            daily_pnl[day_str] = daily_pnl.get(day_str, 0.0) + pnl
        else:
            per_day = pnl / len(days)
            for d in days:
                day_str = d.strftime("%Y-%m-%d")
                daily_pnl[day_str] = daily_pnl.get(day_str, 0.0) + per_day

    if not daily_pnl:
        return pd.Series(dtype=float)

    series = pd.Series(daily_pnl).sort_index()
    series.index = pd.to_datetime(series.index)
    # Convert P&L to return %
    return series / initial_capital


def compute_correlation_matrix(
    daily_returns: dict[str, pd.Series],
) -> pd.DataFrame:
    """Compute pairwise correlation of daily returns."""
    # Align all series to common date range, fill missing with 0 (no trade = 0 return)
    df = pd.DataFrame(daily_returns)
    df = df.fillna(0.0)
    return df.corr()


def compute_simultaneous_mdd(
    equity_curves: dict[str, list[float]],
    wallet_capitals: dict[str, float],
) -> dict[str, Any]:
    """Compute portfolio-level MDD vs individual MDDs."""
    # Build portfolio equity curve (sum of all wallets)
    max_len = max(len(v) for v in equity_curves.values())
    portfolio_equity = np.zeros(max_len)

    individual_mdds: dict[str, float] = {}
    for name, curve in equity_curves.items():
        arr = np.array(curve)
        # Pad shorter curves with last value
        if len(arr) < max_len:
            arr = np.pad(arr, (0, max_len - len(arr)), constant_values=arr[-1])
        portfolio_equity += arr

        # Individual MDD
        peak = np.maximum.accumulate(arr)
        dd = (arr - peak) / np.where(peak > 0, peak, 1.0)
        individual_mdds[name] = float(dd.min())

    # Portfolio MDD
    port_peak = np.maximum.accumulate(portfolio_equity)
    port_dd = (portfolio_equity - port_peak) / np.where(port_peak > 0, port_peak, 1.0)
    portfolio_mdd = float(port_dd.min())

    # Sum of individual MDDs (worst case if perfectly correlated)
    total_capital = sum(wallet_capitals.values())
    weighted_mdd_sum = sum(
        individual_mdds[n] * wallet_capitals[n] / total_capital
        for n in individual_mdds
    )

    return {
        "portfolio_mdd": portfolio_mdd,
        "individual_mdds": individual_mdds,
        "weighted_mdd_sum": weighted_mdd_sum,
        "diversification_benefit": weighted_mdd_sum - portfolio_mdd,
    }


def mean_variance_optimize(
    daily_returns: dict[str, pd.Series],
    n_portfolios: int = 50000,
) -> dict[str, Any]:
    """Monte Carlo mean-variance optimization."""
    df = pd.DataFrame(daily_returns).fillna(0.0)
    if df.shape[1] < 2:
        return {"error": "Need at least 2 assets"}

    mean_returns = df.mean() * 365  # annualize
    cov_matrix = df.cov() * 365

    n_assets = len(df.columns)
    names = list(df.columns)

    best_sharpe = -np.inf
    best_weights: np.ndarray | None = None
    best_ret = 0.0
    best_vol = 0.0

    min_vol = np.inf
    min_vol_weights: np.ndarray | None = None

    rng = np.random.default_rng(42)
    for _ in range(n_portfolios):
        w = rng.random(n_assets)
        w /= w.sum()

        port_ret = float(np.dot(w, mean_returns))
        port_vol = float(np.sqrt(np.dot(w, np.dot(cov_matrix, w))))

        if port_vol > 0:
            sharpe = port_ret / port_vol
        else:
            sharpe = 0.0

        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_weights = w.copy()
            best_ret = port_ret
            best_vol = port_vol

        if port_vol < min_vol:
            min_vol = port_vol
            min_vol_weights = w.copy()

    return {
        "max_sharpe": {
            "sharpe": float(best_sharpe),
            "return": best_ret,
            "volatility": best_vol,
            "weights": {n: float(w) for n, w in zip(names, best_weights)}  # type: ignore[arg-type]
            if best_weights is not None
            else {},
        },
        "min_vol": {
            "volatility": float(min_vol),
            "weights": {n: float(w) for n, w in zip(names, min_vol_weights)}  # type: ignore[arg-type]
            if min_vol_weights is not None
            else {},
        },
    }


def kelly_fraction(trades: list[dict[str, Any]]) -> dict[str, float]:
    """Compute Kelly and half-Kelly fraction from trade P&L distribution."""
    if len(trades) < 5:
        return {"kelly": 0.0, "half_kelly": 0.0, "n": len(trades)}

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    if not wins or not losses:
        return {"kelly": 0.0, "half_kelly": 0.0, "n": len(trades)}

    win_rate = len(wins) / len(pnls)
    avg_win = np.mean(wins)
    avg_loss = abs(np.mean(losses))

    if avg_loss == 0:
        return {"kelly": 1.0, "half_kelly": 0.5, "n": len(trades)}

    # Kelly criterion: f = W/L - (1-W)/L... simplified: f = W - (1-W)/(avg_win/avg_loss)
    win_loss_ratio = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / win_loss_ratio
    kelly = max(0.0, min(kelly, 1.0))

    return {
        "kelly": round(kelly, 4),
        "half_kelly": round(kelly / 2, 4),
        "n": len(trades),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
    }


def main() -> None:
    print("=" * 80)
    print("포트폴리오 상관관계 분석 — Daemon 9지갑")
    print(f"기간: {START} ~ {END} | 슬리피지: 0.05% | 수수료: 0.05%")
    print("=" * 80)

    # Load daemon config — filter out experimental unregistered strategies
    import tomllib as _tomllib
    with open(CONFIG_PATH, "rb") as f:
        raw_toml = _tomllib.load(f)

    VALID_STRATEGIES = {
        "accumulation_breakout", "volatility_breakout", "momentum", "bollinger_mr",
        "etf_flow_admission", "vpin", "consensus", "volume_spike", "mean_reversion",
        "truth_seeker", "stealth_3gate", "kimchi_premium", "truth_seeker_v2",
        "bollinger_rsi", "obi", "ema_crossover", "funding_rate",
        "bb_squeeze_independent", "composite", "momentum_pullback",
    }
    # Remove invalid wallets from raw TOML before writing temp file
    valid_wallets_raw = [
        w for w in raw_toml.get("wallets", [])
        if w.get("strategy", "") in VALID_STRATEGIES
    ]
    skipped = len(raw_toml.get("wallets", [])) - len(valid_wallets_raw)
    if skipped:
        print(f"  ⚠ {skipped}개 실험 전략 지갑 스킵 (미등록 전략)")

    # Build a patched TOML string
    import tempfile, shutil, copy
    raw_patched = copy.deepcopy(raw_toml)
    raw_patched["wallets"] = valid_wallets_raw

    # Write patched TOML
    tmp_path = Path(tempfile.mktemp(suffix=".toml"))
    lines = []
    with open(CONFIG_PATH) as orig:
        in_wallet = False
        skip_wallet = False
        for line in orig:
            stripped = line.strip()
            if stripped == "[[wallets]]":
                in_wallet = True
                skip_wallet = False
                # Peek ahead — we'll check when we see name=
                lines.append(line)
                continue
            if in_wallet and stripped.startswith("name ="):
                name_val = stripped.split("=", 1)[1].strip().strip('"')
                # Check if this wallet's strategy is valid
                wallet_raw = next(
                    (w for w in raw_toml.get("wallets", []) if w.get("name") == name_val),
                    None,
                )
                if wallet_raw and wallet_raw.get("strategy", "") not in VALID_STRATEGIES:
                    skip_wallet = True
                    lines.pop()  # Remove the [[wallets]] line
                    continue
            if skip_wallet:
                if stripped == "[[wallets]]" or (stripped.startswith("[") and not stripped.startswith("[wallets")):
                    skip_wallet = False
                    in_wallet = stripped == "[[wallets]]"
                    lines.append(line)
                continue
            lines.append(line)

    tmp_path.write_text("".join(lines))
    app_config = load_config(tmp_path)
    tmp_path.unlink()

    wallets = app_config.wallets

    print(f"\n총 {len(wallets)}개 지갑 발견:")
    for w in wallets:
        sym = w.symbols[0] if w.symbols else "?"
        print(f"  {w.name}: {w.strategy} / {sym} / ₩{w.initial_capital:,.0f}")

    # Run backtests
    print("\n" + "=" * 80)
    print("1단계: 개별 지갑 백테스트 실행")
    print("=" * 80)

    results: dict[str, dict[str, Any]] = {}
    for w in wallets:
        try:
            r = run_wallet_backtest(app_config, w)
            results[w.name] = r
            print(
                f"  ✓ {w.name}: {r['n_trades']} trades, "
                f"Sharpe={r['sharpe']:.3f}, WR={r['win_rate']:.1%}, "
                f"MDD={r['max_drawdown']:.2%}, Return={r['total_return_pct']:.2%}"
            )
        except Exception as e:
            print(f"  ✗ {w.name}: ERROR — {e}")
            results[w.name] = {
                "name": w.name,
                "trades": [],
                "n_trades": 0,
                "equity_curve": [],
                "symbol": w.symbols[0] if w.symbols else "?",
            }

    # Convert to daily returns
    print("\n" + "=" * 80)
    print("2단계: 일별 수익률 시계열 변환")
    print("=" * 80)

    daily_returns: dict[str, pd.Series] = {}
    wallet_capitals: dict[str, float] = {}
    for w in wallets:
        r = results[w.name]
        if r["n_trades"] > 0:
            dr = trades_to_daily_returns(r["trades"], w.initial_capital)
            if not dr.empty:
                daily_returns[w.name] = dr
                wallet_capitals[w.name] = w.initial_capital
                print(f"  {w.name}: {len(dr)} trading days, avg daily return={dr.mean():.4%}")

    if len(daily_returns) < 2:
        print("\n⚠ 2개 미만 지갑에 거래 존재 — 상관관계 분석 불가")
        return

    # Correlation matrix
    print("\n" + "=" * 80)
    print("3단계: 상관행렬 분석")
    print("=" * 80)

    corr = compute_correlation_matrix(daily_returns)
    print("\n상관행렬:")
    # Shorter names for display
    short_names = {n: n.replace("_wallet", "")[:15] for n in corr.columns}
    display_corr = corr.rename(columns=short_names, index=short_names)
    print(display_corr.round(3).to_string())

    # High correlation pairs
    print("\n상관 > 0.3 인 쌍 (0은 무상관, 1은 완전 동행):")
    names = list(corr.columns)
    high_corr_pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c = corr.iloc[i, j]
            if abs(c) > 0.3:
                high_corr_pairs.append((names[i], names[j], c))
                print(f"  {names[i]} ↔ {names[j]}: {c:.3f}")
    if not high_corr_pairs:
        print("  없음 — 모든 쌍의 상관이 0.3 이하 (좋은 분산)")

    # Simultaneous MDD
    print("\n" + "=" * 80)
    print("4단계: 동시 MDD 분석")
    print("=" * 80)

    equity_curves = {
        n: r["equity_curve"]
        for n, r in results.items()
        if r["equity_curve"] and n in daily_returns
    }
    if equity_curves:
        mdd_result = compute_simultaneous_mdd(equity_curves, wallet_capitals)
        print(f"\n포트폴리오 MDD: {mdd_result['portfolio_mdd']:.2%}")
        print(f"가중 개별 MDD 합: {mdd_result['weighted_mdd_sum']:.2%}")
        print(f"분산 효과 (개별합 - 포트폴리오): {mdd_result['diversification_benefit']:.2%}")
        print("\n개별 MDD:")
        for n, mdd in sorted(mdd_result["individual_mdds"].items(), key=lambda x: x[1]):
            print(f"  {n}: {mdd:.2%}")

    # Mean-variance optimization
    print("\n" + "=" * 80)
    print("5단계: Mean-Variance 최적 가중치")
    print("=" * 80)

    mv_result = mean_variance_optimize(daily_returns)
    if "error" not in mv_result:
        ms = mv_result["max_sharpe"]
        print(f"\n최대 Sharpe 포트폴리오: Sharpe={ms['sharpe']:.3f}, "
              f"Return={ms['return']:.2%}, Vol={ms['volatility']:.2%}")
        print("최적 가중치:")
        for n, w in sorted(ms["weights"].items(), key=lambda x: -x[1]):
            current_pct = wallet_capitals.get(n, 0) / sum(wallet_capitals.values()) * 100
            print(f"  {n}: {w:.1%} (현재: {current_pct:.1f}%)")

        mv = mv_result["min_vol"]
        print(f"\n최소 변동성 포트폴리오: Vol={mv['volatility']:.2%}")
        print("가중치:")
        for n, w in sorted(mv["weights"].items(), key=lambda x: -x[1]):
            print(f"  {n}: {w:.1%}")

    # Current vs optimal allocation
    print("\n" + "=" * 80)
    print("6단계: 현재 vs 최적 자본 배분")
    print("=" * 80)

    total_cap = sum(wallet_capitals.values())
    print(f"\n총 자본: ₩{total_cap:,.0f}")
    print(f"\n{'지갑':<30} {'현재':>8} {'최적(Sharpe)':>12} {'Δ':>8}")
    print("-" * 60)
    if "error" not in mv_result:
        for n in sorted(wallet_capitals.keys()):
            current = wallet_capitals[n] / total_cap
            optimal = mv_result["max_sharpe"]["weights"].get(n, 0)
            delta = optimal - current
            print(f"  {n:<28} {current:>7.1%} {optimal:>11.1%} {delta:>+7.1%}")

    # Kelly fractions
    print("\n" + "=" * 80)
    print("7단계: Kelly/Half-Kelly Fraction")
    print("=" * 80)

    for w in wallets:
        r = results.get(w.name, {})
        trades = r.get("trades", [])
        if trades:
            kf = kelly_fraction(trades)
            print(
                f"  {w.name}: Kelly={kf['kelly']:.2%}, "
                f"Half-Kelly={kf['half_kelly']:.2%}, "
                f"n={kf['n']}, WR={kf.get('win_rate', 0):.1%}"
            )

    # Buy & Hold comparison per symbol
    print("\n" + "=" * 80)
    print("8단계: Buy & Hold 대비 수익률")
    print("=" * 80)

    for w in wallets:
        r = results.get(w.name, {})
        sym = r.get("symbol", "?")
        ctype = WALLET_CTYPE_OVERRIDE.get(w.name, CTYPE)
        try:
            df = load_historical(sym, ctype, START, END)
            if not df.empty:
                bh_return = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
                strat_return = r.get("total_return_pct", 0) * 100
                print(
                    f"  {w.name} ({sym}): "
                    f"전략={strat_return:+.1f}% vs BH={bh_return:+.1f}% "
                    f"(Δ={strat_return - bh_return:+.1f}%)"
                )
        except Exception:
            pass

    print("\n" + "=" * 80)
    print("분석 완료")
    print("=" * 80)


if __name__ == "__main__":
    main()
