#!/usr/bin/env python3
"""Replay accumulation wallet logic with live-like runtime semantics.

Compares three modes:
1. baseline_60m_local_rs   : old daemon mismatch (60m candles, local RS fallback)
2. tf_aligned_240m_local   : 240m candles, still local RS fallback
3. aligned_240m_scan_rs    : 240m candles + market-scan RS snapshot injection

This is not the generic backtest engine. It intentionally exercises
`StrategyWallet.run_once()` so wallet-level gates (`btc_stealth_gate`,
execution costs, risk sizing) stay in the loop.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, pstdev

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
os.sys.path.insert(0, str(_ROOT / "src"))
os.sys.path.insert(0, str(_ROOT / "scripts"))

from historical_loader import load_historical  # noqa: E402

from crypto_trader.config import AppConfig, load_config  # noqa: E402
from crypto_trader.macro.client import MacroSnapshot  # noqa: E402
from crypto_trader.models import Candle  # noqa: E402
from crypto_trader.wallet import build_wallets  # noqa: E402

BENIGN_MACRO = MacroSnapshot(
    overall_regime="expansionary",
    overall_confidence=0.6,
    us_regime="expansionary",
    us_confidence=0.6,
    kr_regime="expansionary",
    kr_confidence=0.6,
    crypto_regime="expansionary",
    crypto_confidence=0.6,
    crypto_signals={},
    btc_dominance=55.0,
    kimchi_premium=2.0,
    fear_greed_index=50,
)


def _to_candles(df: pd.DataFrame) -> list[Candle]:
    return [
        Candle(
            timestamp=index.to_pydatetime().replace(tzinfo=UTC)
            if index.tzinfo is None
            else index.to_pydatetime().astimezone(UTC),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for index, row in df.iterrows()
    ]


def _btc_bull_regime(btc_df_240m: pd.DataFrame) -> bool:
    if len(btc_df_240m) < 20:
        return False
    closes = btc_df_240m["close"]
    return bool(closes.iloc[-1] > closes.iloc[-20:].mean())


def _scan_candidate(
    symbol_df_240m: pd.DataFrame,
    btc_df_240m: pd.DataFrame,
    lookback: int,
    symbol: str,
) -> dict[str, float | str] | None:
    if len(symbol_df_240m) <= lookback or len(btc_df_240m) <= lookback:
        return None
    alt_close = symbol_df_240m["close"]
    alt_volume = symbol_df_240m["volume"]
    btc_close = btc_df_240m["close"]

    alt_ret = float(alt_close.iloc[-1] / alt_close.iloc[-1 - lookback])
    btc_ret = float(btc_close.iloc[-1] / btc_close.iloc[-1 - lookback])
    if abs(btc_ret) <= 1e-9:
        return None
    rs = alt_ret / btc_ret

    alt_close_ma = alt_close.iloc[-lookback:].mean()
    alt_volume_ma = alt_volume.iloc[-lookback:].mean()
    if alt_close_ma <= 0 or alt_volume_ma <= 0:
        return None
    acc = float((alt_close.iloc[-1] / alt_close_ma) * (alt_volume.iloc[-1] / alt_volume_ma))

    alpha = rs * 0.6 + acc * 0.4
    return {
        "symbol": symbol,
        "rs": round(rs, 4),
        "acc": round(acc, 4),
        "alpha": round(alpha, 4),
    }


def _build_wallet_config(
    app_config: AppConfig,
    symbol: str,
    *,
    interval: str,
    use_scan_rs: bool,
    closed_only: bool,
) -> AppConfig:
    template = next(
        wallet
        for wallet in app_config.wallets
        if wallet.name == "accumulation_dood_wallet"
    )
    overrides = dict(template.strategy_overrides)
    overrides["market_data_interval"] = interval
    overrides["market_data_count"] = 180 if interval == "minute240" else 200
    overrides["market_data_closed_only"] = closed_only
    overrides["use_scan_rs"] = use_scan_rs
    wallet = replace(template, symbols=[symbol], strategy_overrides=overrides)
    return replace(app_config, wallets=[wallet])


def _write_runtime_artifacts(
    artifacts_dir: Path,
    btc_df_240m: pd.DataFrame,
    candidate: dict[str, float | str] | None,
    *,
    write_scan_rs: bool,
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    fresh_iso = datetime.now(UTC).isoformat()
    (artifacts_dir / "stealth-watchlist.json").write_text(
        json.dumps(
            {
                "updated_at": fresh_iso,
                "btc_bull_regime": _btc_bull_regime(btc_df_240m),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    watchlist_path = artifacts_dir / "alpha-watchlist.json"
    if write_scan_rs and candidate is not None:
        watchlist_path.write_text(
            json.dumps(
                {
                    "updated_at": fresh_iso,
                    "accumulation_candidates": [candidate],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    elif watchlist_path.exists():
        watchlist_path.unlink()


def _simulate_symbol(
    base_config: AppConfig,
    symbol: str,
    *,
    interval: str,
    use_scan_rs: bool,
    closed_only: bool,
    start: str,
    end: str,
) -> dict[str, float | int | str]:
    symbol_ctype = "240m" if interval == "minute240" else "60m"
    symbol_df = load_historical(symbol, symbol_ctype, start, end)
    symbol_df_240m = load_historical(symbol, "240m", start, end)
    btc_df_240m = load_historical("KRW-BTC", "240m", start, end)
    if symbol_df.empty or symbol_df_240m.empty or btc_df_240m.empty:
        raise RuntimeError(f"missing historical data for {symbol} ({interval})")

    config = _build_wallet_config(
        base_config,
        symbol,
        interval=interval,
        use_scan_rs=use_scan_rs,
        closed_only=closed_only,
    )
    wallet = build_wallets(config)[0]
    wallet.set_macro_snapshot(BENIGN_MACRO)
    wallet.set_market_regime("bull")

    candles = _to_candles(symbol_df)
    lookback = int(config.wallets[0].strategy_overrides.get("stealth_lookback", 36))
    previous_cwd = Path.cwd()

    with tempfile.TemporaryDirectory(prefix="accum-runtime-") as temp_dir:
        temp_path = Path(temp_dir)
        os.chdir(temp_path)
        try:
            for index in range(len(candles)):
                window = candles[: index + 1]
                timestamp = window[-1].timestamp
                btc_window = btc_df_240m[btc_df_240m.index <= timestamp.replace(tzinfo=None)]
                if btc_window.empty:
                    continue
                symbol_240m_window = (
                    symbol_df[symbol_df.index <= timestamp.replace(tzinfo=None)]
                    if symbol_ctype == "240m"
                    else symbol_df_240m[symbol_df_240m.index <= timestamp.replace(tzinfo=None)]
                )
                candidate = _scan_candidate(symbol_240m_window, btc_window, lookback, symbol)
                _write_runtime_artifacts(
                    temp_path / "artifacts",
                    btc_window,
                    candidate,
                    write_scan_rs=use_scan_rs,
                )
                wallet.run_once(symbol, window)
        finally:
            os.chdir(previous_cwd)

    last_price = float(symbol_df["close"].iloc[-1])
    final_equity = wallet.broker.equity({symbol: last_price})
    trade_pcts = [float(trade.pnl_pct) for trade in wallet.broker.closed_trades]
    sharpe = float("nan")
    if len(trade_pcts) >= 3:
        std = pstdev(trade_pcts)
        if std > 1e-9:
            sharpe = mean(trade_pcts) / std * math.sqrt(252)
    wins = sum(1 for value in trade_pcts if value > 0)
    return {
        "symbol": symbol,
        "interval": interval,
        "scan_rs": "on" if use_scan_rs else "off",
        "return_pct": round((final_equity / config.wallets[0].initial_capital - 1.0) * 100, 3),
        "trade_count": len(trade_pcts),
        "win_rate": round((wins / len(trade_pcts) * 100) if trade_pcts else 0.0, 2),
        "avg_trade_pct": round(mean(trade_pcts) * 100, 3) if trade_pcts else 0.0,
        "sharpe": round(sharpe, 3) if not math.isnan(sharpe) else float("nan"),
        "final_equity": round(final_equity, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/daemon.toml")
    parser.add_argument("--symbols", default="KRW-ONT,KRW-RAY")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-04-04")
    args = parser.parse_args()

    app_config = load_config(args.config, {})
    symbols = [symbol.strip() for symbol in args.symbols.split(",") if symbol.strip()]
    modes = [
        ("baseline_60m_local_rs", "minute60", False, False),
        ("tf_aligned_240m_local", "minute240", False, True),
        ("aligned_240m_scan_rs", "minute240", True, True),
    ]

    results: list[dict[str, float | int | str]] = []
    for symbol in symbols:
        print(f"\n=== {symbol} ===")
        for name, interval, use_scan_rs, closed_only in modes:
            row = _simulate_symbol(
                app_config,
                symbol,
                interval=interval,
                use_scan_rs=use_scan_rs,
                closed_only=closed_only,
                start=args.start,
                end=args.end,
            )
            row["mode"] = name
            results.append(row)
            print(
                f"{name:24s} "
                f"ret={row['return_pct']:+7.3f}% "
                f"sh={row['sharpe']:+7.3f} "
                f"n={int(row['trade_count']):3d} "
                f"wr={float(row['win_rate']):5.1f}% "
                f"avg={float(row['avg_trade_pct']):+6.3f}%"
            )

    output = {
        "config": args.config,
        "start": args.start,
        "end": args.end,
        "results": results,
    }
    out_path = Path("artifacts/accumulation-runtime-alignment-report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
