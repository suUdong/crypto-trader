from __future__ import annotations

import json
import logging
import math
import os
import signal
import socket
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from crypto_trader.capital_allocator import CapitalAllocator, StrategyPerformance
from crypto_trader.config import AppConfig, RegimeConfig
from crypto_trader.data.base import MarketDataClient
from crypto_trader.macro.adapter import MacroRegimeAdapter
from crypto_trader.macro.client import MacroClient
from crypto_trader.models import PipelineResult, Position, RuntimeCheckpoint, StrategyRunRecord
from crypto_trader.monitoring.structured_logger import StructuredLogger
from crypto_trader.notifications.alert_manager import TradeAlertManager
from crypto_trader.notifications.telegram import (
    Notifier,
    NullNotifier,
    SlackNotifier,
    TelegramNotifier,
)
from crypto_trader.operator.automated_reporting import (
    AutomatedReportGenerator,
    build_legacy_daily_performance_summary,
)
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.paper_trading import PaperTradeJournal
from crypto_trader.operator.pnl_report import PnLReportGenerator
from crypto_trader.operator.runtime_state import RuntimeCheckpointStore
from crypto_trader.risk.correlation_guard import CorrelationGuard
from crypto_trader.risk.kill_switch import KillSwitch, KillSwitchConfig
from crypto_trader.risk.slippage_monitor import SlippageMonitor
from crypto_trader.risk.wallet_health import WalletHealthMonitor
from crypto_trader.strategy.regime import (
    WEEKEND_POSITION_MULTIPLIER,
    RegimeDetector,
)
from crypto_trader.wallet import StrategyWallet


class MultiSymbolRuntime:
    PNL_NOTIFY_INTERVAL = 86400  # 24 hours in seconds
    _FUTURE_ENTRY_GRACE = timedelta(minutes=5)
    _KST = ZoneInfo("Asia/Seoul")
    _CORRELATION_LOOKBACK_BARS = 24
    _REALLOCATION_MIN_TRANSFER = 50_000.0

    def __init__(
        self,
        wallets: list[StrategyWallet],
        market_data: MarketDataClient,
        config: AppConfig,
        kill_switch: KillSwitch | None = None,
        *,
        restart_count: int = 0,
        last_restart_at: str | None = None,
        supervisor_active: bool = False,
    ) -> None:
        self._wallets = wallets
        self._market_data = market_data
        self._config = config
        self._logger = logging.getLogger(__name__)
        self._shutdown_requested = False
        self._iteration = 0
        self._start_time = time.monotonic()
        self._macro_client: MacroClient | None = None
        self._macro_adapter = MacroRegimeAdapter()
        self._current_market_regime: str = "sideways"
        self._is_weekend: bool = False
        self._kill_switch = kill_switch or KillSwitch(
            config=KillSwitchConfig(
                max_portfolio_drawdown_pct=config.kill_switch.max_portfolio_drawdown_pct,
                max_daily_loss_pct=config.kill_switch.max_daily_loss_pct,
                max_consecutive_losses=config.kill_switch.max_consecutive_losses,
                max_strategy_drawdown_pct=config.kill_switch.max_strategy_drawdown_pct,
                cooldown_minutes=config.kill_switch.cooldown_minutes,
                warn_threshold_pct=config.kill_switch.warn_threshold_pct,
                reduce_threshold_pct=config.kill_switch.reduce_threshold_pct,
                reduce_position_factor=config.kill_switch.reduce_position_factor,
            )
        )
        self._kill_switch_path = Path(config.runtime.kill_switch_path)
        self._session_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
        self._config_path = getattr(config, "source_config_path", "")
        self._wallet_names = [w.name for w in wallets]
        if kill_switch is None and not config.trading.paper_trading:
            # Only auto-load kill switch state for live trading
            self._kill_switch.load(self._kill_switch_path)
        self._total_starting_equity = sum(w.session_starting_equity for w in wallets)
        self._portfolio_peak_equity = self._total_starting_equity
        self._prev_trade_count: dict[str, int] = {
            w.name: len(w.broker.closed_trades) for w in wallets
        }
        self._regime_detector = RegimeDetector(
            RegimeConfig(
                short_lookback=config.regime.short_lookback,
                long_lookback=config.regime.long_lookback,
                bull_threshold_pct=config.regime.bull_threshold_pct,
                bear_threshold_pct=config.regime.bear_threshold_pct,
            )
        )
        if config.macro.enabled:
            base_url = config.macro.base_url if config.macro.has_base_url else None
            db_path = config.macro.db_path if config.macro.has_db else None
            self._macro_client = MacroClient(
                db_path=db_path,
                base_url=base_url,
                timeout_seconds=config.macro.timeout_seconds,
            )
            self._logger.info(
                "Macro layer enabled (base_url=%s db=%s)",
                base_url or "disabled",
                db_path or "default",
            )
        self._notifier = (
            TelegramNotifier(config.telegram) if config.telegram.enabled else NullNotifier()
        )
        notifiers: list[Notifier] = [self._notifier]
        if config.slack.enabled:
            notifiers.append(SlackNotifier(config.slack))
        self._alert_manager = TradeAlertManager(notifiers)
        self._structured_logger = StructuredLogger()
        self._pnl_generator = PnLReportGenerator()
        self._last_pnl_notify: float = 0.0
        self._trade_journal = PaperTradeJournal(config.runtime.paper_trade_journal_path)
        self._journal_trade_counts: dict[str, int] = {w.name: 0 for w in wallets}
        self._strategy_run_journal = StrategyRunJournal(config.runtime.strategy_run_journal_path)
        snapshot_path = Path(config.runtime.runtime_checkpoint_path).parent / "pnl-snapshots.jsonl"
        self._wallet_health = WalletHealthMonitor(snapshot_path)
        self._last_health_check: float = 0.0
        self._health_check_interval = 86400  # 24h
        self._notified_disabled_wallets: set[str] = set()
        self._correlation_guard = CorrelationGuard(
            max_cluster_exposure=6,
            max_correlation=0.85,
            max_high_correlation_exposure=1,
        )
        self._capital_allocator = CapitalAllocator()
        self._slippage_monitor = SlippageMonitor(
            expected_slippage_pct=config.backtest.slippage_pct,
        )
        self._restart_count = restart_count
        self._last_restart_at = last_restart_at
        self._supervisor_active = supervisor_active
        self._network_recovery_backoff_seconds = max(
            1,
            int(getattr(config.runtime, "network_recovery_backoff_seconds", 15)),
        )
        self._failure_streak = 0
        self._last_error: str | None = None
        self._last_error_type: str | None = None
        self._last_success_at: str | None = None
        self._last_failure_at: str | None = None
        self._last_tick_started_at: str | None = None
        self._last_tick_completed_at: str | None = None
        self._last_tick_duration_seconds = 0.0
        self._last_tick_had_error = False
        self._last_tick_recoverable = False
        self._last_retry_delay_seconds = 0
        self._last_successful_results = 0
        self._last_failed_results = 0
        self._tick_errors: list[Exception] = []
        self._latest_prices: dict[str, float] = {}
        self._last_results: list[PipelineResult] = []
        self._last_correlation_snapshot: dict[str, Any] = {}
        self._last_portfolio_risk_state: dict[str, Any] = {}
        self._last_capital_reallocation: dict[str, Any] = {
            "transfer_count": 0,
            "transfers": [],
            "target_capital": {},
        }

    def _handle_signal(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        self._logger.info("Received %s, finishing current tick then shutting down...", sig_name)
        self._shutdown_requested = True

    def _begin_tick(self) -> None:
        self._tick_errors = []
        self._last_tick_started_at = datetime.now(UTC).isoformat()
        self._last_tick_had_error = False
        self._last_tick_recoverable = False
        self._last_retry_delay_seconds = 0

    def _record_tick_error(self, exc: Exception) -> None:
        self._tick_errors.append(exc)
        self._last_tick_had_error = True
        recoverable = self._is_recoverable_error(exc)
        self._last_tick_recoverable = self._last_tick_recoverable or recoverable
        self._last_error = str(exc)
        self._last_error_type = type(exc).__name__
        self._last_failure_at = datetime.now(UTC).isoformat()
        self._logger.warning("Tick error detected: %s", exc)

    def _finalize_tick_state(
        self,
        results: list[PipelineResult],
        *,
        duration_seconds: float,
    ) -> None:
        completed_at = datetime.now(UTC).isoformat()
        self._last_tick_completed_at = completed_at
        self._last_tick_duration_seconds = round(duration_seconds, 3)
        self._last_successful_results = sum(1 for result in results if result.error is None)
        self._last_failed_results = len(self._tick_errors)
        if self._last_tick_had_error:
            self._failure_streak += 1
            if not results and self._last_tick_recoverable:
                self._last_retry_delay_seconds = self._network_recovery_backoff_seconds
        else:
            self._failure_streak = 0
            self._last_error = None
            self._last_error_type = None
            self._last_success_at = completed_at

    def _status(self) -> str:
        return "degraded" if self._last_tick_had_error else "healthy"

    def _is_recoverable_error(self, exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError, socket.timeout, URLError)):
            return True
        if isinstance(exc, HTTPError):
            return exc.code >= 500 or exc.code == 429
        message = str(exc).lower()
        transient_markers = (
            "timeout",
            "timed out",
            "temporarily unavailable",
            "temporary failure",
            "connection reset",
            "connection aborted",
            "connection refused",
            "broken pipe",
            "network",
            "remote end closed connection",
            "name or service not known",
        )
        return any(marker in message for marker in transient_markers)

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        symbols = self._config.trading.symbols
        max_iter = self._config.runtime.max_iterations
        daemon = self._config.runtime.daemon_mode
        poll = self._config.runtime.poll_interval_seconds

        self._logger.info(
            "Starting multi-symbol runtime: symbols=%s wallets=%s daemon=%s poll=%ds",
            symbols,
            [w.name for w in self._wallets],
            daemon,
            poll,
        )

        self._restore_from_checkpoint()

        while not self._shutdown_requested:
            if self._kill_switch.is_triggered:
                self._logger.critical(
                    "Kill switch active: %s — all trading halted",
                    self._kill_switch.state.trigger_reason,
                )
                self._kill_switch.save(self._kill_switch_path)
                break

            self._begin_tick()
            tick_started = time.monotonic()
            self._maybe_check_wallet_health()
            tick_results = self._run_tick(symbols)
            self._check_kill_switch_after_tick(tick_results)
            rebalance_prices = {
                result.symbol: result.latest_price
                for result in tick_results
                if result.latest_price is not None
            }
            if rebalance_prices:
                self._rebalance_idle_wallet_cash(rebalance_prices)
            self._save_checkpoint(tick_results)
            self._refresh_runtime_artifacts()
            self._maybe_refresh_artifacts()
            self._maybe_send_pnl_notify()
            self._finalize_tick_state(
                tick_results,
                duration_seconds=time.monotonic() - tick_started,
            )
            self._save_heartbeat(Path(self._config.runtime.runtime_checkpoint_path).parent)
            self._refresh_health_snapshot()
            self._iteration += 1

            if not daemon and max_iter > 0 and self._iteration >= max_iter:
                self._logger.info("Reached max_iterations=%d, stopping.", max_iter)
                break

            if not self._shutdown_requested:
                delay = self._last_retry_delay_seconds or poll
                time.sleep(delay)

        self._logger.info("Multi-symbol runtime stopped after %d iterations.", self._iteration)

    def _run_tick(self, symbols: list[str]) -> list[PipelineResult]:
        results: list[PipelineResult] = []
        candle_cache: dict[str, Any] = {}

        # Pre-fetch first symbol to detect regime before processing
        first = symbols[0]
        try:
            candle_cache[first] = self._market_data.get_ohlcv(
                symbol=first,
                interval=self._config.trading.interval,
                count=self._config.trading.candle_count,
            )
            if candle_cache[first]:
                analysis = self._regime_detector.analyze(candle_cache[first])
                self._current_market_regime = analysis.regime.value
                self._is_weekend = analysis.is_weekend
        except Exception as exc:
            self._logger.error("Failed to fetch candles for %s: %s", first, exc)
            if self._is_recoverable_error(exc):
                self._record_tick_error(exc)
                candle_cache[first] = []
            else:
                raise

        for symbol in symbols:
            if symbol == first:
                continue
            try:
                candle_cache[symbol] = self._market_data.get_ohlcv(
                    symbol=symbol,
                    interval=self._config.trading.interval,
                    count=self._config.trading.candle_count,
                )
            except Exception as exc:
                self._logger.error("Failed to fetch candles for %s: %s", symbol, exc)
                if self._is_recoverable_error(exc):
                    self._record_tick_error(exc)
                    candle_cache[symbol] = []
                    continue
                raise

        # Refresh macro/regime-aware multipliers after regime detection
        self._refresh_macro()
        self._apply_kill_switch_penalty()

        latest_prices = {
            cached_symbol: symbol_candles[-1].close
            for cached_symbol, symbol_candles in candle_cache.items()
            if symbol_candles
        }
        portfolio_risk = self._compute_portfolio_risk_state(latest_prices)
        self._apply_portfolio_risk_penalty()
        self._rebalance_idle_wallet_cash(latest_prices)

        for symbol in symbols:
            candles = candle_cache[symbol]
            if not candles:
                try:
                    candles = self._market_data.get_ohlcv(
                        symbol=symbol,
                        interval=self._config.trading.interval,
                        count=self._config.trading.candle_count,
                    )
                    candle_cache[symbol] = candles
                    if candles:
                        latest_prices[symbol] = candles[-1].close
                        portfolio_risk = self._compute_portfolio_risk_state(latest_prices)
                except Exception as exc:
                    self._logger.error("Retry fetch failed for %s: %s", symbol, exc)
                    if self._is_recoverable_error(exc):
                        self._record_tick_error(exc)
                        continue
                    raise
                if not candles:
                    continue

            for wallet in self._wallets:
                if wallet.allowed_symbols and symbol not in wallet.allowed_symbols:
                    continue
                if self._wallet_health.is_disabled(wallet.name):
                    continue
                if symbol not in wallet.broker.positions:
                    positions_list = [
                        (w.name, sym) for w in self._wallets for sym in w.broker.positions
                    ]
                    correlation_snapshot = self._correlation_guard.build_snapshot(
                        candle_cache,
                        positions_list,
                        lookback_bars=self._CORRELATION_LOOKBACK_BARS,
                    )
                    self._last_correlation_snapshot = correlation_snapshot.to_dict()
                    if portfolio_risk["open_positions"] >= portfolio_risk["allowed_new_positions"]:
                        self._logger.debug(
                            "[%s] %s entry blocked by portfolio drawdown gate: %s/%s",
                            wallet.name,
                            symbol,
                            portfolio_risk["open_positions"],
                            portfolio_risk["allowed_new_positions"],
                        )
                        continue
                    cluster_exposure = self._correlation_guard.get_cluster_exposure(positions_list)
                    check = self._correlation_guard.check_entry(
                        symbol,
                        wallet.name,
                        cluster_exposure,
                        correlation_snapshot=correlation_snapshot,
                    )
                    if not check.allowed:
                        self._logger.debug(
                            "[%s] %s entry blocked by correlation guard: %s %s",
                            wallet.name,
                            symbol,
                            check.reason,
                            ",".join(check.blocking_symbols),
                        )
                        continue
                try:
                    result = wallet.run_once(symbol, candles)
                except Exception as exc:
                    self._logger.exception(
                        "Wallet execution failed for %s %s",
                        wallet.name,
                        symbol,
                    )
                    if self._is_recoverable_error(exc):
                        self._record_tick_error(exc)
                        self._alert_manager.alert_error(wallet.name, symbol, str(exc))
                        continue
                    raise
                results.append(result)
                if result.latest_price is not None:
                    latest_prices[result.symbol] = result.latest_price
                portfolio_risk = self._compute_portfolio_risk_state(latest_prices)
                if result.error:
                    self._logger.error(result.message)
                    self._record_tick_error(RuntimeError(result.error))
                    self._structured_logger.log_error(
                        wallet.name,
                        wallet.strategy_type,
                        symbol,
                        result.error,
                    )
                    self._alert_manager.alert_error(wallet.name, symbol, result.error)
                else:
                    self._logger.info(result.message)
                    # Log signal
                    self._structured_logger.log_signal(
                        wallet_name=wallet.name,
                        strategy_type=wallet.strategy_type,
                        symbol=symbol,
                        action=result.signal.action.value,
                        reason=result.signal.reason,
                        confidence=result.signal.confidence,
                        indicators=result.signal.indicators,
                        market_regime=self._current_market_regime,
                    )
                    # Log trade or rejection
                    if result.order is not None and result.order.status == "filled":
                        self._slippage_monitor.record_fill(
                            symbol=symbol,
                            side=result.order.side.value,
                            market_price=result.latest_price or result.order.fill_price,
                            fill_price=result.order.fill_price,
                            quantity=result.order.quantity,
                        )
                        self._structured_logger.log_trade(
                            wallet_name=wallet.name,
                            strategy_type=wallet.strategy_type,
                            symbol=symbol,
                            side=result.order.side.value,
                            quantity=result.order.quantity,
                            fill_price=result.order.fill_price,
                            fee_paid=result.order.fee_paid,
                            order_status=result.order.status,
                            reason=result.order.reason,
                        )
                        self._alert_manager.alert_trade(
                            wallet_name=wallet.name,
                            symbol=symbol,
                            side=result.order.side.value,
                            quantity=result.order.quantity,
                            fill_price=result.order.fill_price,
                            fee_paid=result.order.fee_paid,
                            reason=result.order.reason,
                        )
                    elif result.signal.action.value in ("buy", "sell") and result.order is None:
                        self._structured_logger.log_rejection(
                            wallet_name=wallet.name,
                            strategy_type=wallet.strategy_type,
                            symbol=symbol,
                            side=result.signal.action.value,
                            reason=result.signal.reason,
                            requested_quantity=0.0,
                        )
                        self._alert_manager.alert_rejection(
                            wallet_name=wallet.name,
                            symbol=symbol,
                            side=result.signal.action.value,
                            reason=result.signal.reason,
                        )
                record = StrategyRunRecord(
                    recorded_at=datetime.now(UTC).isoformat(),
                    symbol=symbol,
                    latest_price=result.latest_price,
                    market_regime=self._current_market_regime,
                    signal_action=result.signal.action.value,
                    signal_reason=result.signal.reason,
                    signal_confidence=result.signal.confidence,
                    order_status=result.order.status if result.order else None,
                    order_side=result.order.side if result.order else None,
                    session_starting_equity=wallet.session_starting_equity,
                    cash=wallet.broker.cash,
                    open_positions=len(wallet.broker.positions),
                    realized_pnl=wallet.broker.realized_pnl,
                    success=result.error is None,
                    error=result.error,
                    consecutive_failures=0,
                    verdict_status="continue",
                    verdict_confidence=1.0,
                    wallet_name=wallet.name,
                    strategy_type=wallet.strategy_type,
                    signal_indicators=result.signal.indicators,
                    signal_context=result.signal.context,
                    session_id=self._session_id,
                )
                self._strategy_run_journal.append(record)

        return results

    def _check_kill_switch_after_tick(self, results: list[PipelineResult]) -> None:
        """Check kill switch conditions after each tick using portfolio equity."""
        latest_prices: dict[str, float] = {}
        for r in results:
            if r.latest_price is not None:
                latest_prices[r.symbol] = r.latest_price

        total_equity = sum(w.broker.equity(latest_prices) for w in self._wallets)
        total_realized = sum(w.broker.realized_pnl for w in self._wallets)

        # Detect new trade completions and feed each to kill switch
        new_trade_results: list[bool] = []
        for wallet in self._wallets:
            current_count = len(wallet.broker.closed_trades)
            prev_count = self._prev_trade_count.get(wallet.name, 0)
            if current_count > prev_count:
                for trade in wallet.broker.closed_trades[prev_count:]:
                    new_trade_results.append(trade.pnl > 0)
                self._prev_trade_count[wallet.name] = current_count

        if not new_trade_results:
            state = self._kill_switch.check(
                current_equity=total_equity,
                starting_equity=self._total_starting_equity,
                realized_pnl=total_realized,
                trade_won=None,
            )
        else:
            for won in new_trade_results:
                state = self._kill_switch.check(
                    current_equity=total_equity,
                    starting_equity=self._total_starting_equity,
                    realized_pnl=total_realized,
                    trade_won=won,
                )
                if state.triggered:
                    break
        self._kill_switch.save(self._kill_switch_path)

        if state.triggered:
            self._logger.critical(
                "KILL SWITCH TRIGGERED: %s — stopping after this tick",
                state.trigger_reason,
            )
            self._alert_manager.alert_kill_switch(
                reason=state.trigger_reason,
                portfolio_dd=state.portfolio_drawdown_pct,
                daily_loss=state.daily_loss_pct,
                consecutive_losses=state.consecutive_losses,
            )
            self._structured_logger.log_system(
                wallet_name="portfolio",
                strategy_type="kill_switch",
                symbol="*",
                message=f"Kill switch triggered: {state.trigger_reason}",
                details={
                    "portfolio_dd": state.portfolio_drawdown_pct,
                    "daily_loss": state.daily_loss_pct,
                    "consecutive_losses": state.consecutive_losses,
                },
            )

    def _refresh_macro(self) -> None:
        weekend_mult = WEEKEND_POSITION_MULTIPLIER if self._is_weekend else 1.0
        if self._macro_client is None:
            self._apply_regime_weights()
            return
        try:
            snapshot = self._macro_client.get_snapshot()
        except Exception as exc:
            self._logger.error("Macro snapshot refresh failed: %s", exc)
            if self._is_recoverable_error(exc):
                self._record_tick_error(exc)
                self._apply_regime_weights()
                return
            raise
        adjustment = self._macro_adapter.compute(snapshot)
        for wallet in self._wallets:
            regime_weight = self._macro_adapter.strategy_weight(
                wallet.strategy_type,
                self._current_market_regime,
            )
            combined = adjustment.position_size_multiplier * regime_weight * weekend_mult
            wallet.set_macro_multiplier(combined)
        if snapshot is not None:
            self._logger.info(
                "Macro regime=%s confidence=%.0f%% multiplier=%.2f market_regime=%s weekend=%s",
                snapshot.overall_regime,
                snapshot.overall_confidence * 100,
                adjustment.position_size_multiplier,
                self._current_market_regime,
                self._is_weekend,
            )

    def _apply_kill_switch_penalty(self) -> None:
        """Scale down position sizes when kill switch tiered thresholds are breached."""
        penalty = self._kill_switch.state.position_size_penalty
        if penalty < 1.0:
            for wallet in self._wallets:
                current = wallet._macro_multiplier
                wallet.set_macro_multiplier(current * penalty)
            self._logger.warning(
                "Kill switch penalty active: position sizes scaled by %.0f%%",
                penalty * 100,
            )

    @staticmethod
    def _coerce_numeric(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _compute_portfolio_risk_state(self, latest_prices: dict[str, float]) -> dict[str, Any]:
        total_equity = sum(wallet.broker.equity(latest_prices) for wallet in self._wallets)
        open_positions = sum(len(wallet.broker.positions) for wallet in self._wallets)
        if total_equity > self._portfolio_peak_equity:
            self._portfolio_peak_equity = total_equity
        drawdown_pct = 0.0
        if self._portfolio_peak_equity > 0:
            drawdown_pct = max(
                0.0,
                (self._portfolio_peak_equity - total_equity) / self._portfolio_peak_equity,
            )
        limit_pct = self._coerce_numeric(
            getattr(self._config.kill_switch, "max_portfolio_drawdown_pct", None),
            self._kill_switch._config.max_portfolio_drawdown_pct,
        )
        warn = self._coerce_numeric(
            getattr(self._config.kill_switch, "warn_threshold_pct", None),
            self._kill_switch._config.warn_threshold_pct,
        )
        reduce = self._coerce_numeric(
            getattr(self._config.kill_switch, "reduce_threshold_pct", None),
            self._kill_switch._config.reduce_threshold_pct,
        )
        reduce_factor = self._coerce_numeric(
            getattr(self._config.kill_switch, "reduce_position_factor", None),
            self._kill_switch._config.reduce_position_factor,
        )
        entry_size_penalty = 1.0
        if limit_pct > 0 and drawdown_pct > 0:
            ratio = min(1.0, drawdown_pct / limit_pct)
            if ratio >= 1.0:
                entry_size_penalty = 0.0
            elif ratio >= reduce:
                entry_size_penalty = reduce_factor
            elif ratio >= warn:
                interp = (ratio - warn) / max(1e-9, reduce - warn)
                entry_size_penalty = 1.0 - interp * (1.0 - reduce_factor)
        entry_size_penalty = min(
            entry_size_penalty,
            self._kill_switch.state.position_size_penalty,
        )
        max_concurrent_positions = max(
            1,
            int(
                self._coerce_numeric(
                    getattr(self._config.risk, "max_concurrent_positions", None),
                    self._config.risk.max_concurrent_positions
                    if isinstance(self._config.risk.max_concurrent_positions, (int, float))
                    else 1,
                )
            ),
        )
        base_position_limit = len(self._wallets) * max_concurrent_positions
        if limit_pct <= 0:
            allowed_new_positions = base_position_limit
        elif entry_size_penalty <= 0:
            allowed_new_positions = 0
        else:
            allowed_new_positions = max(1, math.ceil(base_position_limit * entry_size_penalty))
        state = {
            "peak_equity": round(self._portfolio_peak_equity, 2),
            "total_equity": round(total_equity, 2),
            "drawdown_pct": round(drawdown_pct * 100, 2),
            "entry_size_penalty": round(entry_size_penalty, 4),
            "base_position_limit": base_position_limit,
            "allowed_new_positions": allowed_new_positions,
            "active_position_limit": allowed_new_positions,
            "open_positions": open_positions,
        }
        self._last_portfolio_risk_state = state
        return state

    def _apply_portfolio_risk_penalty(self) -> None:
        penalty = float(self._last_portfolio_risk_state.get("entry_size_penalty", 1.0) or 1.0)
        if penalty >= 1.0:
            return
        for wallet in self._wallets:
            wallet.set_macro_multiplier(wallet._macro_multiplier * penalty)
        self._logger.warning(
            "Portfolio drawdown penalty active: position sizes scaled by %.0f%%",
            penalty * 100,
        )

    def _rebalance_idle_wallet_cash(self, latest_prices: dict[str, float]) -> None:
        idle_wallets = [wallet for wallet in self._wallets if not wallet.broker.positions]
        if len(idle_wallets) < 2:
            self._last_capital_reallocation = {
                "transfer_count": 0,
                "transfers": [],
                "target_capital": {},
            }
            return

        performances = [
            StrategyPerformance(
                strategy=wallet.name,
                strategy_type=wallet.strategy_type,
                return_pct=(
                    (
                        (wallet.broker.equity(latest_prices) / wallet.session_starting_equity)
                        - 1.0
                    )
                    * 100.0
                    if wallet.session_starting_equity > 0
                    else 0.0
                ),
                sharpe=max(
                    -3.0,
                    min(
                        5.0,
                        (
                            wallet.broker.realized_pnl
                            / max(wallet.session_starting_equity * 0.05, 1.0)
                        ),
                    ),
                ),
                mdd_pct=max(
                    0.0,
                    (
                        (wallet.session_starting_equity - wallet.broker.equity(latest_prices))
                        / wallet.session_starting_equity
                        * 100.0
                    )
                    if wallet.session_starting_equity > 0
                    else 0.0,
                ),
                trade_count=len(wallet.broker.closed_trades),
                win_rate=(
                    sum(1 for trade in wallet.broker.closed_trades if trade.pnl > 0)
                    / len(wallet.broker.closed_trades)
                    if wallet.broker.closed_trades
                    else 0.0
                ),
                equity=wallet.broker.equity(latest_prices),
                initial_capital=wallet.session_starting_equity,
            )
            for wallet in self._wallets
        ]
        total_capital = sum(performance.equity for performance in performances)
        allocation = self._capital_allocator.allocate(performances, total_capital)
        current_cash = {wallet.name: wallet.broker.cash for wallet in idle_wallets}
        target_capital = {
            item.strategy: item.capital
            for item in allocation.allocations
            if item.strategy in current_cash
        }
        transfers = CapitalAllocator.plan_transfers(
            current_capital=current_cash,
            target_capital=target_capital,
            min_transfer=self._REALLOCATION_MIN_TRANSFER,
        )
        wallet_map = {wallet.name: wallet for wallet in self._wallets}
        for transfer in transfers:
            wallet_map[transfer.source].adjust_capital(-transfer.amount)
            wallet_map[transfer.target].adjust_capital(transfer.amount)
        self._last_capital_reallocation = {
            "transfer_count": len(transfers),
            "total_reallocated": round(sum(transfer.amount for transfer in transfers), 2),
            "transfers": [
                {
                    "source": transfer.source,
                    "target": transfer.target,
                    "amount": transfer.amount,
                }
                for transfer in transfers
            ],
            "target_capital": {name: round(amount, 2) for name, amount in target_capital.items()},
        }

    def _apply_regime_weights(self) -> None:
        """Apply regime-aware strategy weights without macro data."""
        weekend_mult = WEEKEND_POSITION_MULTIPLIER if self._is_weekend else 1.0
        for wallet in self._wallets:
            regime_weight = self._macro_adapter.strategy_weight(
                wallet.strategy_type,
                self._current_market_regime,
            )
            wallet.set_macro_multiplier(regime_weight * weekend_mult)

    def _restore_from_checkpoint(self) -> None:
        """Restore wallet broker state from last checkpoint if available."""
        cp_path = Path(self._config.runtime.runtime_checkpoint_path)
        if not cp_path.exists():
            self._logger.info("No checkpoint found, starting fresh")
            return

        try:
            checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._logger.warning("Failed to read checkpoint for restore: %s", exc)
            return

        wallet_states = checkpoint.get("wallet_states", {})
        restored_count = 0

        for wallet in self._wallets:
            ws = wallet_states.get(wallet.name)
            if ws is None:
                continue

            # Restore cash and realized PnL
            wallet.broker.cash = ws.get("cash", wallet.broker.cash)
            wallet.broker.realized_pnl = ws.get("realized_pnl", 0.0)
            wallet.session_starting_equity = ws.get(
                "initial_capital",
                ws.get("cash", wallet.broker.cash)
                + sum(
                    p.get("quantity", 0) * p.get("entry_price", 0)
                    for p in ws.get("positions", {}).values()
                )
                - ws.get("realized_pnl", 0.0),
            )

            # Restore open positions
            positions_data = ws.get("positions", {})
            for symbol, pos_data in positions_data.items():
                try:
                    entry_time = datetime.fromisoformat(pos_data["entry_time"])
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=UTC)
                    if entry_time > datetime.now(UTC) + self._FUTURE_ENTRY_GRACE:
                        entry_time = entry_time.replace(tzinfo=self._KST).astimezone(UTC)
                except (KeyError, ValueError):
                    entry_time = datetime.now(UTC)

                position = Position(
                    symbol=pos_data.get("symbol", symbol),
                    quantity=pos_data["quantity"],
                    entry_price=pos_data["entry_price"],
                    entry_time=entry_time,
                    entry_index=pos_data.get("entry_index"),
                    entry_fee_paid=pos_data.get("entry_fee_paid", 0.0),
                    entry_confidence=pos_data.get("entry_confidence", 0.0),
                    high_watermark=pos_data.get("high_watermark", 0.0),
                    partial_tp_taken=pos_data.get("partial_tp_taken", False),
                )
                wallet.broker.positions[symbol] = position
                restored_count += 1

        if restored_count > 0:
            self._logger.info(
                "Restored %d positions from checkpoint across %d wallets",
                restored_count,
                len(wallet_states),
            )

        # Update journal trade counts to avoid re-journaling old trades
        for wallet in self._wallets:
            self._journal_trade_counts[wallet.name] = len(wallet.broker.closed_trades)
            self._prev_trade_count[wallet.name] = len(wallet.broker.closed_trades)

    def _save_checkpoint(self, results: list[PipelineResult]) -> None:
        store = RuntimeCheckpointStore(self._config.runtime.runtime_checkpoint_path)

        latest_prices: dict[str, float] = {}
        for r in results:
            if r.latest_price is not None:
                latest_prices[r.symbol] = r.latest_price

        # Store for use by periodic artifact refreshes
        self._latest_prices = latest_prices
        self._last_results = results

        wallet_states = {}
        target_capital = self._last_capital_reallocation.get("target_capital", {})
        for wallet in self._wallets:
            wallet_states[wallet.name] = {
                "strategy_type": wallet.strategy_type,
                "initial_capital": wallet.session_starting_equity,
                "cash": wallet.broker.cash,
                "realized_pnl": wallet.broker.realized_pnl,
                "open_positions": len(wallet.broker.positions),
                "equity": wallet.broker.equity(latest_prices),
                "trade_count": len(wallet.broker.closed_trades),
                "target_capital": target_capital.get(wallet.name),
                "capital_gap": round(
                    target_capital.get(wallet.name, wallet.broker.cash) - wallet.broker.cash,
                    2,
                ),
                "positions": {
                    symbol: {
                        "symbol": pos.symbol,
                        "quantity": pos.quantity,
                        "entry_price": pos.entry_price,
                        "entry_time": pos.entry_time.isoformat(),
                        "entry_index": pos.entry_index,
                        "entry_fee_paid": pos.entry_fee_paid,
                        "entry_confidence": pos.entry_confidence,
                        "high_watermark": pos.high_watermark,
                        "partial_tp_taken": pos.partial_tp_taken,
                    }
                    for symbol, pos in wallet.broker.positions.items()
                },
            }

        checkpoint = RuntimeCheckpoint(
            generated_at=datetime.now(UTC).isoformat(),
            iteration=self._iteration + 1,
            symbols=self._config.trading.symbols,
            wallet_states=wallet_states,
            session_id=self._session_id,
            config_path=self._config_path,
            wallet_names=self._wallet_names,
            correlation=self._last_correlation_snapshot,
            portfolio_risk=self._last_portfolio_risk_state,
            capital_reallocation=self._last_capital_reallocation,
        )
        store.save(checkpoint)
        self._persist_journal()
        self._save_heartbeat(Path(self._config.runtime.runtime_checkpoint_path).parent)

    def _persist_journal(self) -> None:
        """Append new closed trades from all wallets to the paper trade journal."""
        for wallet in self._wallets:
            current_count = len(wallet.broker.closed_trades)
            prev_count = self._journal_trade_counts.get(wallet.name, 0)
            if current_count > prev_count:
                new_trades = wallet.broker.closed_trades[prev_count:current_count]
                self._trade_journal.append_many(
                    new_trades,
                    wallet_name=wallet.name,
                    session_id=self._session_id,
                )
                self._journal_trade_counts[wallet.name] = current_count

    def _maybe_check_wallet_health(self) -> None:
        """Periodically evaluate wallet health and auto-disable losers."""
        if time.time() - self._last_health_check < self._health_check_interval:
            return
        try:
            wallet_names = [w.name for w in self._wallets]
            self._wallet_health.evaluate(wallet_names)
            disabled_wallets = set(self._wallet_health.get_disabled_wallets())
            newly_disabled = sorted(disabled_wallets - self._notified_disabled_wallets)
            if newly_disabled:
                disabled_lines = []
                for name in newly_disabled:
                    status = self._wallet_health.get_status(name)
                    if status is not None:
                        disabled_lines.append(
                            f"  {name}: DISABLED ({status.disabled_reason})"
                        )
                msg = "[Crypto Trader] Wallet Auto-Disable\n" + "\n".join(disabled_lines)
                self._notifier.send_message(msg)
                self._logger.warning("Auto-disabled wallets: %s", newly_disabled)
                self._notified_disabled_wallets.update(newly_disabled)
            self._last_health_check = time.time()
        except Exception as exc:
            self._logger.error("Wallet health check failed: %s", exc)
            if self._is_recoverable_error(exc):
                self._record_tick_error(exc)
            else:
                raise

    def _maybe_send_pnl_notify(self) -> None:
        if time.time() - self._last_pnl_notify < self.PNL_NOTIFY_INTERVAL:
            return
        try:
            report = self._pnl_generator.generate_from_checkpoint(
                self._config.runtime.runtime_checkpoint_path,
                self._config.runtime.paper_trade_journal_path,
            )
            disabled = self._wallet_health.get_disabled_wallets()
            paused = [w.name for w in self._wallets if w.risk_manager.is_auto_paused]
            lines = [
                "[Crypto Trader] Daily PnL Report",
                f"Equity: {report.total_equity:,.0f} KRW | "
                f"Return: {report.portfolio_return_pct:+.2f}%",
                f"Sharpe: {report.portfolio_sharpe:.2f} | "
                f"Trades: {report.total_trades} | Win: {report.portfolio_win_rate:.0%}",
                "---",
            ]
            for s in sorted(report.strategies, key=lambda x: x.total_return_pct, reverse=True):
                status = ""
                if s.wallet in disabled:
                    status = " [DISABLED]"
                elif s.wallet in paused:
                    status = " [PAUSED]"
                pf = f"{s.profit_factor:.1f}" if s.profit_factor < 1000 else "inf"
                lines.append(
                    f"{s.wallet}: {s.total_return_pct:+.2f}% | "
                    f"{s.trade_count}t W:{s.win_rate:.0%} PF:{pf}{status}"
                )
            if disabled:
                lines.append(f"---\nDisabled: {', '.join(disabled)}")
            if paused:
                lines.append(f"Paused: {', '.join(paused)}")
            self._notifier.send_message("\n".join(lines))
            self._last_pnl_notify = time.time()
        except Exception as exc:
            self._logger.error("Failed to send PnL notification: %s", exc)
            if self._is_recoverable_error(exc):
                self._record_tick_error(exc)
            else:
                raise

    def _maybe_refresh_artifacts(self) -> None:
        """Periodically refresh heavier artifacts that do not need every tick."""
        current_iteration = self._iteration + 1
        if current_iteration != 1 and current_iteration % 60 != 0:
            return
        try:
            self._refresh_portfolio_promotion()
            self._logger.info(
                "Periodic heavy artifact refresh completed (iteration %d)",
                current_iteration,
            )
        except Exception as exc:
            self._logger.error("Artifact refresh failed: %s", exc)
            if self._is_recoverable_error(exc):
                self._record_tick_error(exc)
            else:
                raise

    def _refresh_runtime_artifacts(self) -> None:
        """Keep dashboard/runtime snapshots current on every checkpoint."""
        try:
            self._refresh_position_snapshot()
            self._refresh_health_snapshot()
            self._refresh_daily_performance()
        except Exception as exc:
            self._logger.error("Runtime artifact refresh failed: %s", exc)
            if self._is_recoverable_error(exc):
                self._record_tick_error(exc)
            else:
                raise

    def _refresh_position_snapshot(self) -> None:
        """Save current open positions to positions.json."""
        snapshot_path = Path(self._config.runtime.position_snapshot_path)
        positions = []
        for wallet in self._wallets:
            for symbol, pos in wallet.broker.positions.items():
                positions.append(
                    {
                        "wallet": wallet.name,
                        "symbol": symbol,
                        "qty": pos.quantity,
                        "entry_price": pos.entry_price,
                        "side": "long",
                    }
                )
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "count": len(positions),
            "positions": positions,
        }
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _refresh_portfolio_promotion(self) -> None:
        """Refresh portfolio-level promotion gate artifact."""
        from crypto_trader.operator.promotion import PortfolioPromotionGate

        gate = PortfolioPromotionGate()
        decision = gate.evaluate_from_checkpoint(
            checkpoint_path=self._config.runtime.runtime_checkpoint_path,
            journal_path=self._config.runtime.strategy_run_journal_path,
        )
        promo_path = Path(self._config.runtime.promotion_gate_path)
        gate.save(decision, promo_path)

    def _refresh_health_snapshot(self) -> None:
        """Write aggregated health.json from all wallets (multi-strategy equivalent)."""
        latest_prices = getattr(self, "_latest_prices", {})
        last_results = getattr(self, "_last_results", [])

        total_cash = sum(w.broker.cash for w in self._wallets)
        total_positions = sum(len(w.broker.positions) for w in self._wallets)
        total_equity = sum(w.broker.equity(latest_prices) for w in self._wallets)

        # Determine last signal from most recent results
        last_signal = "hold"
        last_error = None
        success = not self._last_tick_had_error
        for r in last_results:
            if r.error is not None:
                last_error = r.error
            if r.signal and r.signal.action.value != "hold":
                last_signal = r.signal.action.value

        snapshot = {
            "updated_at": datetime.now(UTC).isoformat(),
            "success": success,
            "status": self._status(),
            "degraded": self._last_tick_had_error,
            "consecutive_failures": self._failure_streak,
            "failure_streak": self._failure_streak,
            "last_error": self._last_error or last_error,
            "last_error_type": self._last_error_type,
            "last_signal": last_signal,
            "last_order_status": None,
            "cash": total_cash,
            "open_positions": total_positions,
            "total_equity": total_equity,
            "wallet_count": len(self._wallets),
            "mode": "multi_symbol",
            "recoverable_error": self._last_tick_recoverable,
            "recovery_delay_seconds": self._last_retry_delay_seconds,
            "last_success_at": self._last_success_at,
            "last_failure_at": self._last_failure_at,
            "tick_started_at": self._last_tick_started_at,
            "tick_completed_at": self._last_tick_completed_at,
            "tick_duration_seconds": self._last_tick_duration_seconds,
            "successful_results": self._last_successful_results,
            "failed_results": self._last_failed_results,
            "restart_count": self._restart_count,
            "last_restart_at": self._last_restart_at,
            "supervisor_active": self._supervisor_active,
            "auto_restart_enabled": bool(
                getattr(self._config.runtime, "auto_restart_enabled", True)
            ),
            "config_path": self._config_path,
        }
        health_path = Path(self._config.runtime.healthcheck_path)
        health_path.parent.mkdir(parents=True, exist_ok=True)
        health_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    def _refresh_daily_performance(self) -> None:
        perf_path = Path(self._config.runtime.daily_performance_path)
        perf_path.parent.mkdir(parents=True, exist_ok=True)
        generator = AutomatedReportGenerator()
        daily_report_path = generator.default_output_path(
            period="daily",
            artifacts_dir=perf_path.parent,
        )
        weekly_report_path = generator.default_output_path(
            period="weekly",
            artifacts_dir=perf_path.parent,
        )
        daily_report = generator.generate(
            checkpoint_path=self._config.runtime.runtime_checkpoint_path,
            strategy_run_journal_path=self._config.runtime.strategy_run_journal_path,
            trade_journal_path=self._config.runtime.paper_trade_journal_path,
            period="daily",
            hours=24,
        )
        weekly_report = generator.generate(
            checkpoint_path=self._config.runtime.runtime_checkpoint_path,
            strategy_run_journal_path=self._config.runtime.strategy_run_journal_path,
            trade_journal_path=self._config.runtime.paper_trade_journal_path,
            period="weekly",
            hours=168,
        )
        generator.save(daily_report, daily_report_path)
        generator.save(weekly_report, weekly_report_path)
        legacy_summary = build_legacy_daily_performance_summary(
            daily_report,
            report_path=daily_report_path,
            weekly_report_path=weekly_report_path,
        )
        perf_path.write_text(
            json.dumps(legacy_summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _save_heartbeat(self, artifacts_dir: Path) -> None:
        slip_stats = self._slippage_monitor.get_stats()
        heartbeat = {
            "last_heartbeat": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "iteration": self._iteration + 1,
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "poll_interval_seconds": self._config.runtime.poll_interval_seconds,
            "session_id": self._session_id,
            "config_path": self._config_path,
            "symbols": self._config.trading.symbols,
            "wallet_names": self._wallet_names,
            "status": self._status(),
            "failure_streak": self._failure_streak,
            "last_error": self._last_error,
            "last_error_type": self._last_error_type,
            "last_success_at": self._last_success_at,
            "last_failure_at": self._last_failure_at,
            "tick_started_at": self._last_tick_started_at,
            "tick_completed_at": self._last_tick_completed_at,
            "tick_duration_seconds": self._last_tick_duration_seconds,
            "recoverable_error": self._last_tick_recoverable,
            "recovery_delay_seconds": self._last_retry_delay_seconds,
            "successful_results": self._last_successful_results,
            "failed_results": self._last_failed_results,
            "restart_count": self._restart_count,
            "last_restart_at": self._last_restart_at,
            "supervisor_active": self._supervisor_active,
            "auto_restart_enabled": bool(
                getattr(self._config.runtime, "auto_restart_enabled", True)
            ),
            "slippage": {
                "total_trades": slip_stats.total_trades,
                "anomaly_count": slip_stats.anomaly_count,
                "avg_slippage_pct": round(slip_stats.avg_slippage_pct * 100, 4),
                "max_slippage_pct": round(slip_stats.max_slippage_pct * 100, 4),
                "anomaly_rate": round(self._slippage_monitor.anomaly_rate * 100, 2),
            },
            "kill_switch": {
                "warning_active": self._kill_switch.state.warning_active,
                "position_size_penalty": self._kill_switch.state.position_size_penalty,
                "portfolio_drawdown_pct": round(
                    self._kill_switch.state.portfolio_drawdown_pct * 100, 2
                ),
                "daily_loss_pct": round(self._kill_switch.state.daily_loss_pct * 100, 2),
            },
            "correlation": self._last_correlation_snapshot,
            "portfolio_risk": self._last_portfolio_risk_state,
            "capital_reallocation": self._last_capital_reallocation,
        }
        heartbeat_path = artifacts_dir / "daemon-heartbeat.json"
        heartbeat_path.write_text(json.dumps(heartbeat, indent=2), encoding="utf-8")
