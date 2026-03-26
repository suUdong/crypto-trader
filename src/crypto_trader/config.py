from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class WalletConfig:
    name: str = "default"
    strategy: str = "composite"
    initial_capital: float = 1_000_000.0
    symbols: list[str] = field(default_factory=list)
    strategy_overrides: dict[str, Any] = field(default_factory=dict)
    risk_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradingConfig:
    exchange: str = "upbit"
    symbol: str = "KRW-BTC"
    symbols: list[str] = field(default_factory=lambda: ["KRW-BTC"])
    interval: str = "minute60"
    candle_count: int = 200
    paper_trading: bool = True


@dataclass(slots=True)
class StrategyConfig:
    momentum_lookback: int = 20
    momentum_entry_threshold: float = 0.005
    momentum_exit_threshold: float = -0.01
    bollinger_window: int = 20
    bollinger_stddev: float = 1.5
    rsi_period: int = 14
    rsi_oversold_floor: float = 20.0
    rsi_recovery_ceiling: float = 60.0
    rsi_overbought: float = 70.0
    k_base: float = 0.5
    noise_lookback: int = 20
    ma_filter_period: int = 20
    max_holding_bars: int = 48
    adx_period: int = 14
    adx_threshold: float = 20.0
    volume_filter_mult: float = 0.0


@dataclass(slots=True)
class RegimeConfig:
    short_lookback: int = 10
    long_lookback: int = 30
    bull_threshold_pct: float = 0.03
    bear_threshold_pct: float = -0.03


@dataclass(slots=True)
class DriftConfig:
    bull_return_tolerance_pct: float = 0.15
    sideways_return_tolerance_pct: float = 0.08
    bear_return_tolerance_pct: float = 0.05
    bull_error_rate_threshold: float = 0.25
    sideways_error_rate_threshold: float = 0.2
    bear_error_rate_threshold: float = 0.1


@dataclass(slots=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.01
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    trailing_stop_pct: float = 0.0
    atr_stop_multiplier: float = 2.0
    max_daily_loss_pct: float = 0.05
    max_concurrent_positions: int = 1
    min_entry_confidence: float = 0.6
    drawdown_reduction_pct: float = 0.5
    partial_tp_pct: float = 0.5
    cooldown_bars: int = 3


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
    daemon_mode: bool = True
    healthcheck_path: str = "artifacts/health.json"
    runtime_checkpoint_path: str = "artifacts/runtime-checkpoint.json"
    backtest_baseline_path: str = "artifacts/backtest-baseline.json"
    regime_report_path: str = "artifacts/regime-report.json"
    drift_calibration_path: str = "artifacts/drift-calibration.json"
    operator_report_path: str = "artifacts/operator-report.md"
    strategy_run_journal_path: str = "artifacts/strategy-runs.jsonl"
    paper_trade_journal_path: str = "artifacts/paper-trades.jsonl"
    position_snapshot_path: str = "artifacts/positions.json"
    daily_performance_path: str = "artifacts/daily-performance.json"
    drift_report_path: str = "artifacts/drift-report.json"
    promotion_gate_path: str = "artifacts/promotion-gate.json"
    daily_memo_path: str = "artifacts/daily-memo.md"
    strategy_report_path: str = "artifacts/strategy-report.md"
    performance_report_path: str = "artifacts/performance-report.md"


@dataclass(slots=True)
class MacroConfig:
    enabled: bool = False
    db_path: str = ""

    @property
    def has_db(self) -> bool:
        return bool(self.db_path.strip())


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
    regime: RegimeConfig
    drift: DriftConfig
    risk: RiskConfig
    backtest: BacktestConfig
    telegram: TelegramConfig
    runtime: RuntimeConfig
    credentials: CredentialsConfig
    macro: MacroConfig = field(default_factory=MacroConfig)
    wallets: list[WalletConfig] = field(default_factory=lambda: [
        WalletConfig("momentum_wallet", "momentum", 1_000_000.0),
        WalletConfig("mean_reversion_wallet", "mean_reversion", 1_000_000.0),
        WalletConfig("composite_wallet", "composite", 1_000_000.0),
    ])


_STRATEGY_FIELD_NAMES = {field.name for field in fields(StrategyConfig)}
_RISK_FIELD_NAMES = {field.name for field in fields(RiskConfig)}
_STRATEGY_EXTRA_OVERRIDE_FIELDS: dict[str, set[str]] = {
    "kimchi_premium": {"min_trade_interval_bars", "min_confidence", "cooldown_hours"},
    "consensus": {"sub_strategies", "min_agree"},
}


def load_config(path: str | Path | None = None, environ: dict[str, str] | None = None) -> AppConfig:
    env = environ or dict(os.environ)
    config_path = Path(path or env.get("CT_CONFIG", "config/example.toml"))
    raw = _read_toml(config_path) if config_path.exists() else {}

    single_symbol = _read_value(raw, env, "trading", "symbol", "CT_SYMBOL", "KRW-BTC")
    raw_symbols = raw.get("trading", {}).get("symbols", None)
    symbols_list: list[str] = list(raw_symbols) if raw_symbols else [str(single_symbol)]
    trading = TradingConfig(
        exchange=_read_value(raw, env, "trading", "exchange", "CT_EXCHANGE", "upbit"),
        symbol=str(single_symbol),
        symbols=symbols_list,
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
                0.005,
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
            _read_value(raw, env, "strategy", "bollinger_stddev", "CT_BOLLINGER_STDDEV", 1.8)
        ),
        rsi_period=int(_read_value(raw, env, "strategy", "rsi_period", "CT_RSI_PERIOD", 14)),
        rsi_oversold_floor=float(
            _read_value(raw, env, "strategy", "rsi_oversold_floor", "CT_RSI_OVERSOLD_FLOOR", 20.0)
        ),
        rsi_recovery_ceiling=float(
            _read_value(
                raw, env, "strategy", "rsi_recovery_ceiling", "CT_RSI_RECOVERY_CEILING", 60.0
            )
        ),
        rsi_overbought=float(
            _read_value(raw, env, "strategy", "rsi_overbought", "CT_RSI_OVERBOUGHT", 70.0)
        ),
        k_base=float(_read_value(raw, env, "strategy", "k_base", "CT_K_BASE", 0.5)),
        noise_lookback=int(
            _read_value(raw, env, "strategy", "noise_lookback", "CT_NOISE_LOOKBACK", 20)
        ),
        ma_filter_period=int(
            _read_value(raw, env, "strategy", "ma_filter_period", "CT_MA_FILTER_PERIOD", 20)
        ),
        max_holding_bars=int(
            _read_value(raw, env, "strategy", "max_holding_bars", "CT_MAX_HOLDING_BARS", 48)
        ),
    )
    regime = RegimeConfig(
        short_lookback=int(
            _read_value(raw, env, "regime", "short_lookback", "CT_REGIME_SHORT_LOOKBACK", 10)
        ),
        long_lookback=int(
            _read_value(raw, env, "regime", "long_lookback", "CT_REGIME_LONG_LOOKBACK", 30)
        ),
        bull_threshold_pct=float(
            _read_value(raw, env, "regime", "bull_threshold_pct", "CT_REGIME_BULL_THRESHOLD", 0.03)
        ),
        bear_threshold_pct=float(
            _read_value(raw, env, "regime", "bear_threshold_pct", "CT_REGIME_BEAR_THRESHOLD", -0.03)
        ),
    )
    drift = DriftConfig(
        bull_return_tolerance_pct=float(
            _read_value(
                raw,
                env,
                "drift",
                "bull_return_tolerance_pct",
                "CT_BULL_DRIFT_TOLERANCE",
                0.15,
            )
        ),
        sideways_return_tolerance_pct=float(
            _read_value(
                raw,
                env,
                "drift",
                "sideways_return_tolerance_pct",
                "CT_SIDEWAYS_DRIFT_TOLERANCE",
                0.08,
            )
        ),
        bear_return_tolerance_pct=float(
            _read_value(
                raw,
                env,
                "drift",
                "bear_return_tolerance_pct",
                "CT_BEAR_DRIFT_TOLERANCE",
                0.05,
            )
        ),
        bull_error_rate_threshold=float(
            _read_value(
                raw,
                env,
                "drift",
                "bull_error_rate_threshold",
                "CT_BULL_ERROR_RATE_THRESHOLD",
                0.25,
            )
        ),
        sideways_error_rate_threshold=float(
            _read_value(
                raw,
                env,
                "drift",
                "sideways_error_rate_threshold",
                "CT_SIDEWAYS_ERROR_RATE_THRESHOLD",
                0.2,
            )
        ),
        bear_error_rate_threshold=float(
            _read_value(
                raw,
                env,
                "drift",
                "bear_error_rate_threshold",
                "CT_BEAR_ERROR_RATE_THRESHOLD",
                0.1,
            )
        ),
    )
    risk = RiskConfig(
        risk_per_trade_pct=float(
            _read_value(raw, env, "risk", "risk_per_trade_pct", "CT_RISK_PER_TRADE_PCT", 0.01)
        ),
        stop_loss_pct=float(
            _read_value(raw, env, "risk", "stop_loss_pct", "CT_STOP_LOSS_PCT", 0.03)
        ),
        take_profit_pct=float(
            _read_value(raw, env, "risk", "take_profit_pct", "CT_TAKE_PROFIT_PCT", 0.06)
        ),
        trailing_stop_pct=float(
            _read_value(raw, env, "risk", "trailing_stop_pct", "CT_TRAILING_STOP_PCT", 0.0)
        ),
        atr_stop_multiplier=float(
            _read_value(
                raw,
                env,
                "risk",
                "atr_stop_multiplier",
                "CT_ATR_STOP_MULTIPLIER",
                0.0,
            )
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
        min_entry_confidence=float(
            _read_value(
                raw,
                env,
                "risk",
                "min_entry_confidence",
                "CT_MIN_ENTRY_CONFIDENCE",
                0.6,
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
        daemon_mode=_read_bool(raw, env, "runtime", "daemon_mode", "CT_DAEMON_MODE", True),
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
        runtime_checkpoint_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "runtime_checkpoint_path",
                "CT_RUNTIME_CHECKPOINT_PATH",
                "artifacts/runtime-checkpoint.json",
            )
        ),
        backtest_baseline_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "backtest_baseline_path",
                "CT_BACKTEST_BASELINE_PATH",
                "artifacts/backtest-baseline.json",
            )
        ),
        regime_report_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "regime_report_path",
                "CT_REGIME_REPORT_PATH",
                "artifacts/regime-report.json",
            )
        ),
        drift_calibration_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "drift_calibration_path",
                "CT_DRIFT_CALIBRATION_PATH",
                "artifacts/drift-calibration.json",
            )
        ),
        operator_report_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "operator_report_path",
                "CT_OPERATOR_REPORT_PATH",
                "artifacts/operator-report.md",
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
        paper_trade_journal_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "paper_trade_journal_path",
                "CT_PAPER_TRADE_JOURNAL_PATH",
                "artifacts/paper-trades.jsonl",
            )
        ),
        position_snapshot_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "position_snapshot_path",
                "CT_POSITION_SNAPSHOT_PATH",
                "artifacts/positions.json",
            )
        ),
        daily_performance_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "daily_performance_path",
                "CT_DAILY_PERFORMANCE_PATH",
                "artifacts/daily-performance.json",
            )
        ),
        drift_report_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "drift_report_path",
                "CT_DRIFT_REPORT_PATH",
                "artifacts/drift-report.json",
            )
        ),
        promotion_gate_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "promotion_gate_path",
                "CT_PROMOTION_GATE_PATH",
                "artifacts/promotion-gate.json",
            )
        ),
        daily_memo_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "daily_memo_path",
                "CT_DAILY_MEMO_PATH",
                "artifacts/daily-memo.md",
            )
        ),
        strategy_report_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "strategy_report_path",
                "CT_STRATEGY_REPORT_PATH",
                "artifacts/strategy-report.md",
            )
        ),
        performance_report_path=str(
            _read_value(
                raw,
                env,
                "runtime",
                "performance_report_path",
                "CT_PERFORMANCE_REPORT_PATH",
                "artifacts/performance-report.md",
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
    macro = MacroConfig(
        enabled=_read_bool(raw, env, "macro", "enabled", "CT_MACRO_ENABLED", False),
        db_path=str(
            _read_value(raw, env, "macro", "db_path", "CT_MACRO_DB_PATH", "")
        ),
    )
    raw_wallets = raw.get("wallets", None)
    if raw_wallets and isinstance(raw_wallets, list):
        wallets = [
            WalletConfig(
                name=str(w.get("name", f"wallet_{i}")),
                strategy=str(w.get("strategy", "composite")),
                initial_capital=float(w.get("initial_capital", 1_000_000.0)),
                symbols=list(w.get("symbols", [])),
                strategy_overrides=_read_wallet_override_map(w, "strategy_overrides"),
                risk_overrides=_read_wallet_override_map(w, "risk_overrides"),
            )
            for i, w in enumerate(raw_wallets)
        ]
    else:
        wallets = [
            WalletConfig("momentum_wallet", "momentum", 1_000_000.0),
            WalletConfig("mean_reversion_wallet", "mean_reversion", 1_000_000.0),
            WalletConfig("composite_wallet", "composite", 1_000_000.0),
        ]
    app_config = AppConfig(
        trading=trading,
        strategy=strategy,
        regime=regime,
        drift=drift,
        risk=risk,
        backtest=backtest,
        telegram=telegram,
        runtime=runtime,
        credentials=credentials,
        macro=macro,
        wallets=wallets,
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


def _read_wallet_override_map(raw_wallet: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw_wallet.get(key, {})
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def _strategy_override_names(strategy_name: str) -> set[str]:
    return _STRATEGY_FIELD_NAMES | _STRATEGY_EXTRA_OVERRIDE_FIELDS.get(strategy_name, set())


def _apply_strategy_overrides(
    base: StrategyConfig,
    overrides: dict[str, Any],
) -> StrategyConfig:
    config_kwargs = {
        key: value
        for key, value in overrides.items()
        if key in _STRATEGY_FIELD_NAMES
    }
    return replace(base, **config_kwargs)


def _apply_risk_overrides(base: RiskConfig, overrides: dict[str, Any]) -> RiskConfig:
    config_kwargs = {
        key: value
        for key, value in overrides.items()
        if key in _RISK_FIELD_NAMES
    }
    return replace(base, **config_kwargs)


def _validate_config(config: AppConfig) -> None:
    errors: list[str] = []

    if config.trading.candle_count <= 1:
        errors.append("trading.candle_count must be greater than 1")

    _validate_strategy_config("strategy", config.strategy, errors)

    if config.regime.short_lookback <= 0:
        errors.append("regime.short_lookback must be positive")
    if config.regime.long_lookback <= config.regime.short_lookback:
        errors.append("regime.long_lookback must be greater than regime.short_lookback")
    if config.regime.bull_threshold_pct <= 0:
        errors.append("regime.bull_threshold_pct must be positive")
    if config.regime.bear_threshold_pct >= 0:
        errors.append("regime.bear_threshold_pct must be negative")

    if config.drift.bull_return_tolerance_pct <= 0:
        errors.append("drift.bull_return_tolerance_pct must be positive")
    if config.drift.sideways_return_tolerance_pct <= 0:
        errors.append("drift.sideways_return_tolerance_pct must be positive")
    if config.drift.bear_return_tolerance_pct <= 0:
        errors.append("drift.bear_return_tolerance_pct must be positive")

    for field_name, value in _positive_probability_fields(config).items():
        if value <= 0:
            errors.append(f"{field_name} must be positive")

    for field_name, value in _positive_probability_fields(config).items():
        if value >= 1:
            errors.append(f"{field_name} must be less than 1")

    if config.backtest.initial_capital <= 0:
        errors.append("backtest.initial_capital must be positive")

    _validate_risk_config("risk", config.risk, errors)

    if config.runtime.poll_interval_seconds <= 0:
        errors.append("runtime.poll_interval_seconds must be positive")
    if not config.runtime.healthcheck_path.strip():
        errors.append("runtime.healthcheck_path must not be empty")
    if not config.runtime.runtime_checkpoint_path.strip():
        errors.append("runtime.runtime_checkpoint_path must not be empty")
    if not config.runtime.backtest_baseline_path.strip():
        errors.append("runtime.backtest_baseline_path must not be empty")
    if not config.runtime.regime_report_path.strip():
        errors.append("runtime.regime_report_path must not be empty")
    if not config.runtime.drift_calibration_path.strip():
        errors.append("runtime.drift_calibration_path must not be empty")
    if not config.runtime.operator_report_path.strip():
        errors.append("runtime.operator_report_path must not be empty")
    if not config.runtime.strategy_run_journal_path.strip():
        errors.append("runtime.strategy_run_journal_path must not be empty")
    if not config.runtime.paper_trade_journal_path.strip():
        errors.append("runtime.paper_trade_journal_path must not be empty")
    if not config.runtime.position_snapshot_path.strip():
        errors.append("runtime.position_snapshot_path must not be empty")
    if not config.runtime.daily_performance_path.strip():
        errors.append("runtime.daily_performance_path must not be empty")
    if not config.runtime.drift_report_path.strip():
        errors.append("runtime.drift_report_path must not be empty")
    if not config.runtime.promotion_gate_path.strip():
        errors.append("runtime.promotion_gate_path must not be empty")
    if not config.runtime.daily_memo_path.strip():
        errors.append("runtime.daily_memo_path must not be empty")
    if not config.runtime.strategy_report_path.strip():
        errors.append("runtime.strategy_report_path must not be empty")

    if not config.trading.symbols:
        errors.append("trading.symbols must contain at least one symbol")
    for sym in config.trading.symbols:
        if not sym.startswith("KRW-"):
            errors.append(f"trading.symbols: '{sym}' must start with 'KRW-'")

    valid_strategies = {
        "momentum",
        "mean_reversion",
        "composite",
        "kimchi_premium",
        "obi",
        "vpin",
        "volatility_breakout",
        "consensus",
    }
    for wc in config.wallets:
        if not wc.name.strip():
            errors.append("wallet name must not be empty")
        if wc.strategy not in valid_strategies:
            errors.append(f"wallet '{wc.name}': strategy must be one of {valid_strategies}")
        if wc.initial_capital <= 0:
            errors.append(f"wallet '{wc.name}': initial_capital must be positive")
        invalid_strategy_overrides = (
            set(wc.strategy_overrides) - _strategy_override_names(wc.strategy)
        )
        if invalid_strategy_overrides:
            invalid = ", ".join(sorted(invalid_strategy_overrides))
            errors.append(f"wallet '{wc.name}': invalid strategy_overrides keys: {invalid}")
        invalid_risk_overrides = set(wc.risk_overrides) - _RISK_FIELD_NAMES
        if invalid_risk_overrides:
            invalid = ", ".join(sorted(invalid_risk_overrides))
            errors.append(f"wallet '{wc.name}': invalid risk_overrides keys: {invalid}")
        _validate_strategy_config(
            f"wallet '{wc.name}'.strategy_overrides",
            _apply_strategy_overrides(config.strategy, wc.strategy_overrides),
            errors,
        )
        _validate_risk_config(
            f"wallet '{wc.name}'.risk_overrides",
            _apply_risk_overrides(config.risk, wc.risk_overrides),
            errors,
        )

    if not config.trading.paper_trading and not config.credentials.has_upbit_credentials:
        errors.append(
            "Live trading requires Upbit API credentials. "
            "Set CT_UPBIT_ACCESS_KEY and CT_UPBIT_SECRET_KEY."
        )

    if errors:
        raise ValueError("Invalid configuration:\n- " + "\n- ".join(errors))


def _positive_probability_fields(config: AppConfig) -> dict[str, float]:
    return {
        "drift.bull_error_rate_threshold": config.drift.bull_error_rate_threshold,
        "drift.sideways_error_rate_threshold": config.drift.sideways_error_rate_threshold,
        "drift.bear_error_rate_threshold": config.drift.bear_error_rate_threshold,
        "backtest.fee_rate": config.backtest.fee_rate,
        "backtest.slippage_pct": config.backtest.slippage_pct,
        "risk.risk_per_trade_pct": config.risk.risk_per_trade_pct,
        "risk.stop_loss_pct": config.risk.stop_loss_pct,
        "risk.take_profit_pct": config.risk.take_profit_pct,
        "risk.max_daily_loss_pct": config.risk.max_daily_loss_pct,
    }


def _validate_strategy_config(prefix: str, strategy: StrategyConfig, errors: list[str]) -> None:
    if strategy.momentum_lookback <= 0:
        errors.append(f"{prefix}.momentum_lookback must be positive")
    if strategy.bollinger_window <= 1:
        errors.append(f"{prefix}.bollinger_window must be greater than 1")
    if strategy.bollinger_stddev <= 0:
        errors.append(f"{prefix}.bollinger_stddev must be positive")
    if strategy.rsi_period <= 0:
        errors.append(f"{prefix}.rsi_period must be positive")
    if strategy.max_holding_bars <= 0:
        errors.append(f"{prefix}.max_holding_bars must be positive")


def _validate_risk_config(prefix: str, risk: RiskConfig, errors: list[str]) -> None:
    if risk.take_profit_pct <= risk.stop_loss_pct:
        errors.append(f"{prefix}.take_profit_pct must be greater than {prefix}.stop_loss_pct")
    if risk.max_concurrent_positions <= 0:
        errors.append(f"{prefix}.max_concurrent_positions must be positive")
