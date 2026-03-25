from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from crypto_trader.config import AppConfig
from crypto_trader.models import BacktestBaseline, BacktestResult


class BacktestBaselineStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> BacktestBaseline | None:
        if not self._path.exists():
            return None
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return BacktestBaseline(**payload)

    def save(self, baseline: BacktestBaseline) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(baseline), indent=2), encoding="utf-8")


def build_baseline(
    *,
    config: AppConfig,
    result: BacktestResult,
) -> BacktestBaseline:
    trade_count = len(result.trade_log)
    average_trade_pnl_pct = (
        sum(trade.pnl_pct for trade in result.trade_log) / trade_count if trade_count else 0.0
    )
    return BacktestBaseline(
        generated_at=datetime.now(timezone.utc).isoformat(),
        symbol=config.trading.symbol,
        interval=config.trading.interval,
        candle_count=config.trading.candle_count,
        config_fingerprint=build_backtest_fingerprint(config),
        total_return_pct=result.total_return_pct,
        win_rate=result.win_rate,
        profit_factor=result.profit_factor,
        max_drawdown=result.max_drawdown,
        trade_count=trade_count,
        average_trade_pnl_pct=average_trade_pnl_pct,
    )


def build_backtest_fingerprint(config: AppConfig) -> str:
    payload = {
        "symbol": config.trading.symbol,
        "interval": config.trading.interval,
        "candle_count": config.trading.candle_count,
        "strategy": asdict(config.strategy),
        "regime": asdict(config.regime),
        "backtest": asdict(config.backtest),
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return sha256(raw).hexdigest()
