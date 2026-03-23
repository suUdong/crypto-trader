from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TradingConfig:
    exchange: str = "upbit"
    symbol: str = "KRW-BTC"
    interval: str = "minute60"
    candle_count: int = 200
    paper_trading: bool = True


@dataclass(slots=True)
class StrategyConfig:
    momentum_lookback: int = 20
    momentum_entry_threshold: float = 0.02
    momentum_exit_threshold: float = -0.01
    bollinger_window: int = 20
    bollinger_stddev: float = 2.0
    rsi_period: int = 14
    rsi_oversold_floor: float = 25.0
    rsi_recovery_ceiling: float = 45.0
    rsi_overbought: float = 70.0
    max_holding_bars: int = 24


@dataclass(slots=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.01
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    max_daily_loss_pct: float = 0.05
    max_concurrent_positions: int = 1


@dataclass(slots=True)
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    fee_rate: float = 0.0005
    slippage_pct: float = 0.0005


@dataclass(slots=True)
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass(slots=True)
class RuntimeConfig:
    log_level: str = "INFO"
    poll_interval_seconds: int = 60
    max_iterations: int = 0
    healthcheck_path: str = "artifacts/health.json"
    strategy_run_journal_path: str = "artifacts/strategy-runs.jsonl"


@dataclass(slots=True)
class CredentialsConfig:
    upbit_access_key: str = ""
    upbit_secret_key: str = ""

    @property
    def has_upbit_credentials(self) -> bool:
        return bool(self.upbit_access_key and self.upbit_secret_key)


@dataclass(slots=True)
class AppConfig:
    trading: TradingConfig
    strategy: StrategyConfig
    risk: RiskConfig
    backtest: BacktestConfig
    telegram: TelegramConfig
    runtime: RuntimeConfig
    credentials: CredentialsConfig


def load_config(path: str | Path | None = None, environ: dict[str, str] | None = None) -> AppConfig:
    env = environ or dict(os.environ)
    config_path = Path(path or env.get("CT_CONFIG", "config/example.toml"))
    raw = _read_toml(config_path) if config_path.exists() else {}

    trading = TradingConfig(
        exchange=_read_value(raw, env, "trading", "exchange", "CT_EXCHANGE", "upbit"),
        symbol=_read_value(raw, env, "trading", "symbol", "CT_SYMBOL", "KRW-BTC"),
        interval=_read_value(raw, env, "trading", "interval", "CT_INTERVAL", "minute60"),
        candle_count=int(_read_value(raw, env, "trading", "candle_count", "CT_CANDLE_COUNT", 200)),
        paper_trading=_read_bool(raw, env, "trading", "paper_trading", "CT_PAPER_TRADING", True),
    )
    strategy = StrategyConfig(
        momentum_lookback=int(
            _read_value(raw, env, "strategy", "momentum_lookback", "CT_MOMENTUM_LOOKBACK", 20)
        ),
        momentum_entry_threshold=float(
            _read_value(
                raw,
                env,
                "strategy",
                "momentum_entry_threshold",
                "CT_MOMENTUM_ENTRY_THRESHOLD",
                0.02,
            )
        ),
        momentum_exit_threshold=float(
            _read_value(
                raw, env, "strategy", "momentum_exit_threshold", "CT_MOMENTUM_EXIT_THRESHOLD", -0.01
            )
        ),
        bollinger_window=int(
            _read_value(raw, env, "strategy", "bollinger_window", "CT_BOLLINGER_WINDOW", 20)
        ),
        bollinger_stddev=float(
            _read_value(raw, env, "strategy", "bollinger_stddev", "CT_BOLLINGER_STDDEV", 2.0)
        ),
        rsi_period=int(_read_value(raw, env, "strategy", "rsi_period", "CT_RSI_PERIOD", 14)),
        rsi_oversold_floor=float(
            _read_value(raw, env, "strategy", "rsi_oversold_floor", "CT_RSI_OVERSOLD_FLOOR", 25.0)
        ),
        rsi_recovery_ceiling=float(
            _read_value(
                raw, env, "strategy", "rsi_recovery_ceiling", "CT_RSI_RECOVERY_CEILING", 45.0
            )
        ),
        rsi_overbought=float(
            _read_value(raw, env, "strategy", "rsi_overbought", "CT_RSI_OVERBOUGHT", 70.0)
        ),
        max_holding_bars=int(
            _read_value(raw, env, "strategy", "max_holding_bars", "CT_MAX_HOLDING_BARS", 24)
        ),
    )
    risk = RiskConfig(
        risk_per_trade_pct=float(
            _read_value(raw, env, "risk", "risk_per_trade_pct", "CT_RISK_PER_TRADE_PCT", 0.01)
        ),
        stop_loss_pct=float(
            _read_value(raw, env, "risk", "stop_loss_pct", "CT_STOP_LOSS_PCT", 0.02)
        ),
        take_profit_pct=float(
            _read_value(raw, env, "risk", "take_profit_pct", "CT_TAKE_PROFIT_PCT", 0.04)
        ),
        max_daily_loss_pct=float(
            _read_value(raw, env, "risk", "max_daily_loss_pct", "CT_MAX_DAILY_LOSS_PCT", 0.05)
        ),
        max_concurrent_positions=int(
            _read_value(
                raw,
                env,
                "risk",
                "max_concurrent_positions",
                "CT_MAX_CONCURRENT_POSITIONS",
                1,
            )
        ),
    )
    backtest = BacktestConfig(
        initial_capital=float(
            _read_value(raw, env, "backtest", "initial_capital", "CT_INITIAL_CAPITAL", 1_000_000.0)
        ),
        fee_rate=float(_read_value(raw, env, "backtest", "fee_rate", "CT_FEE_RATE", 0.0005)),
        slippage_pct=float(
            _read_value(raw, env, "backtest", "slippage_pct", "CT_SLIPPAGE_PCT", 0.0005)
        ),
    )
    telegram = TelegramConfig(
        bot_token=str(_read_value(raw, env, "telegram", "bot_token", "CT_TELEGRAM_BOT_TOKEN", "")),
        chat_id=str(_read_value(raw, env, "telegram", "chat_id", "CT_TELEGRAM_CHAT_ID", "")),
    )
    runtime = RuntimeConfig(
        log_level=str(_read_value(raw, env, "runtime", "log_level", "CT_LOG_LEVEL", "INFO")),
        poll_interval_seconds=int(
            _read_value(
                raw,
                env,
                "runtime",
                "poll_interval_seconds",
                "CT_POLL_INTERVAL_SECONDS",
                60,
            )
        ),
        max_iterations=int(
            _read_value(raw, env, "runtime", "max_iterations", "CT_MAX_ITERATIONS", 0)
        ),
        healthcheck_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "healthcheck_path",
                "CT_HEALTHCHECK_PATH",
                "artifacts/health.json",
            )
        ),
        strategy_run_journal_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "strategy_run_journal_path",
                "CT_STRATEGY_RUN_JOURNAL_PATH",
                "artifacts/strategy-runs.jsonl",
            )
        ),
    )
    credentials = CredentialsConfig(
        upbit_access_key=str(
            _read_value(
                raw,
                env,
                "credentials",
                "upbit_access_key",
                "CT_UPBIT_ACCESS_KEY",
                "",
            )
        ),
        upbit_secret_key=str(
            _read_value(
                raw,
                env,
                "credentials",
                "upbit_secret_key",
                "CT_UPBIT_SECRET_KEY",
                "",
            )
        ),
    )
    app_config = AppConfig(
        trading=trading,
        strategy=strategy,
        risk=risk,
        backtest=backtest,
        telegram=telegram,
        runtime=runtime,
        credentials=credentials,
    )
    _validate_config(app_config)
    return app_config


def _read_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _read_value(
    raw: dict[str, Any],
    environ: dict[str, str],
    section: str,
    key: str,
    env_name: str,
    default: Any,
) -> Any:
    if env_name in environ:
        return environ[env_name]
    return raw.get(section, {}).get(key, default)


def _read_bool(
    raw: dict[str, Any],
    environ: dict[str, str],
    section: str,
    key: str,
    env_name: str,
    default: bool,
) -> bool:
    value = _read_value(raw, environ, section, key, env_name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _validate_config(config: AppConfig) -> None:
    if config.runtime.poll_interval_seconds <= 0:
        raise ValueError("runtime.poll_interval_seconds must be positive")
    if config.risk.max_concurrent_positions <= 0:
        raise ValueError("risk.max_concurrent_positions must be positive")
    if not config.trading.paper_trading:
        raise ValueError(
            "Live trading is not implemented yet. Keep CT_PAPER_TRADING=true."
        )
