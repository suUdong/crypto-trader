from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_trader.config import AppConfig, RegimeConfig
from crypto_trader.data.base import MarketDataClient
from crypto_trader.macro.adapter import MacroRegimeAdapter
from crypto_trader.macro.client import MacroClient
from crypto_trader.models import PipelineResult, Position, RuntimeCheckpoint, StrategyRunRecord
from crypto_trader.monitoring.structured_logger import StructuredLogger
from crypto_trader.notifications.alert_manager import TradeAlertManager
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.paper_trading import PaperTradeJournal
from crypto_trader.operator.runtime_state import RuntimeCheckpointStore
from crypto_trader.notifications.telegram import NullNotifier, TelegramNotifier, SlackNotifier
from crypto_trader.operator.pnl_report import PnLReportGenerator
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

    def __init__(
        self,
        wallets: list[StrategyWallet],
        market_data: MarketDataClient,
        config: AppConfig,
        kill_switch: KillSwitch | None = None,
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
        self._kill_switch_path = Path(
            getattr(config.runtime, "kill_switch_path", "artifacts/kill-switch.json")
        )
        self._session_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
        self._config_path = getattr(config, "source_config_path", "")
        self._wallet_names = [w.name for w in wallets]
        if kill_switch is None and not config.trading.paper_trading:
            # Only auto-load kill switch state for live trading
            self._kill_switch.load(self._kill_switch_path)
        self._total_starting_equity = sum(w.session_starting_equity for w in wallets)
        self._prev_trade_count: dict[str, int] = {w.name: len(w.broker.closed_trades) for w in wallets}
        self._regime_detector = RegimeDetector(RegimeConfig(
            short_lookback=config.regime.short_lookback,
            long_lookback=config.regime.long_lookback,
            bull_threshold_pct=config.regime.bull_threshold_pct,
            bear_threshold_pct=config.regime.bear_threshold_pct,
        ))
        if config.macro.enabled:
            db_path = config.macro.db_path if config.macro.has_db else None
            self._macro_client = MacroClient(db_path)
            self._logger.info("Macro layer enabled (db=%s)", db_path or "default")
        self._notifier = TelegramNotifier(config.telegram) if config.telegram.enabled else NullNotifier()
        notifiers = [self._notifier]
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
        self._correlation_guard = CorrelationGuard(max_cluster_exposure=6)
        self._slippage_monitor = SlippageMonitor(
            expected_slippage_pct=config.backtest.slippage_pct,
        )

    def _handle_signal(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        self._logger.info("Received %s, finishing current tick then shutting down...", sig_name)
        self._shutdown_requested = True

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

            self._maybe_check_wallet_health()
            self._apply_kill_switch_penalty()
            tick_results = self._run_tick(symbols)
            self._check_kill_switch_after_tick(tick_results)
            self._save_checkpoint(tick_results)
            self._maybe_refresh_artifacts()
            self._maybe_send_pnl_notify()
            self._iteration += 1

            if not daemon and max_iter > 0 and self._iteration >= max_iter:
                self._logger.info("Reached max_iterations=%d, stopping.", max_iter)
                break

            if not self._shutdown_requested:
                time.sleep(poll)

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

        # Refresh macro/regime-aware multipliers after regime detection
        self._refresh_macro()

        for symbol in symbols:
            if symbol not in candle_cache:
                try:
                    candle_cache[symbol] = self._market_data.get_ohlcv(
                        symbol=symbol,
                        interval=self._config.trading.interval,
                        count=self._config.trading.candle_count,
                    )
                except Exception as exc:
                    self._logger.error("Failed to fetch candles for %s: %s", symbol, exc)
                    continue

            candles = candle_cache[symbol]
            if not candles:
                continue

            for wallet in self._wallets:
                if wallet.allowed_symbols and symbol not in wallet.allowed_symbols:
                    continue
                if self._wallet_health.is_disabled(wallet.name):
                    continue
                # Correlation guard: skip tick if no position and cluster is full
                if not wallet.broker.positions:
                    positions_list = [
                        (w.name, sym)
                        for w in self._wallets
                        for sym in w.broker.positions
                    ]
                    cluster_exposure = self._correlation_guard.get_cluster_exposure(positions_list)
                    check = self._correlation_guard.check_entry(symbol, wallet.name, cluster_exposure)
                    if not check.allowed:
                        self._logger.debug(
                            "[%s] %s entry blocked by correlation guard: %s",
                            wallet.name,
                            symbol,
                            check.reason,
                        )
                        continue
                result = wallet.run_once(symbol, candles)
                results.append(result)
                if result.error:
                    self._logger.error(result.message)
                    self._structured_logger.log_error(
                        wallet.name, wallet.strategy_type, symbol, result.error,
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
                    elif (
                        result.signal.action.value in ("buy", "sell")
                        and result.order is None
                    ):
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
        snapshot = self._macro_client.get_snapshot()
        adjustment = self._macro_adapter.compute(snapshot)
        for wallet in self._wallets:
            regime_weight = self._macro_adapter.strategy_weight(
                wallet.strategy_type, self._current_market_regime,
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

    def _apply_regime_weights(self) -> None:
        """Apply regime-aware strategy weights without macro data."""
        weekend_mult = WEEKEND_POSITION_MULTIPLIER if self._is_weekend else 1.0
        for wallet in self._wallets:
            regime_weight = self._macro_adapter.strategy_weight(
                wallet.strategy_type, self._current_market_regime,
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
            wallet.session_starting_equity = ws.get("cash", wallet.broker.cash) + sum(
                p.get("quantity", 0) * p.get("entry_price", 0)
                for p in ws.get("positions", {}).values()
            )

            # Restore open positions
            positions_data = ws.get("positions", {})
            for symbol, pos_data in positions_data.items():
                try:
                    entry_time = datetime.fromisoformat(pos_data["entry_time"])
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=UTC)
                except (KeyError, ValueError):
                    entry_time = datetime.now(UTC)

                position = Position(
                    symbol=pos_data.get("symbol", symbol),
                    quantity=pos_data["quantity"],
                    entry_price=pos_data["entry_price"],
                    entry_time=entry_time,
                    entry_index=pos_data.get("entry_index"),
                    entry_fee_paid=pos_data.get("entry_fee_paid", 0.0),
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
        for wallet in self._wallets:
            wallet_states[wallet.name] = {
                "strategy_type": wallet.strategy_type,
                "cash": wallet.broker.cash,
                "realized_pnl": wallet.broker.realized_pnl,
                "open_positions": len(wallet.broker.positions),
                "equity": wallet.broker.equity(latest_prices),
                "trade_count": len(wallet.broker.closed_trades),
                "positions": {
                    symbol: {
                        "symbol": pos.symbol,
                        "quantity": pos.quantity,
                        "entry_price": pos.entry_price,
                        "entry_time": pos.entry_time.isoformat(),
                        "entry_index": pos.entry_index,
                        "entry_fee_paid": pos.entry_fee_paid,
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
                self._trade_journal.append_many(new_trades, wallet_name=wallet.name)
                self._journal_trade_counts[wallet.name] = current_count

    def _maybe_check_wallet_health(self) -> None:
        """Periodically evaluate wallet health and auto-disable losers."""
        if time.time() - self._last_health_check < self._health_check_interval:
            return
        try:
            wallet_names = [w.name for w in self._wallets]
            self._wallet_health.evaluate(wallet_names)
            newly_disabled = self._wallet_health.get_disabled_wallets()
            if newly_disabled:
                msg = (
                    "[Crypto Trader] Wallet Auto-Disable\n"
                    + "\n".join(
                        f"  {name}: DISABLED ({self._wallet_health.get_status(name).disabled_reason})"
                        for name in newly_disabled
                    )
                )
                self._notifier.send_message(msg)
                self._logger.warning("Auto-disabled wallets: %s", newly_disabled)
            self._last_health_check = time.time()
        except Exception as exc:
            self._logger.error("Wallet health check failed: %s", exc)

    def _maybe_send_pnl_notify(self) -> None:
        if time.time() - self._last_pnl_notify < self.PNL_NOTIFY_INTERVAL:
            return
        try:
            report = self._pnl_generator.generate_from_checkpoint(
                self._config.runtime.runtime_checkpoint_path,
                self._config.runtime.paper_trade_journal_path,
            )
            disabled = self._wallet_health.get_disabled_wallets()
            paused = [
                w.name for w in self._wallets
                if w.risk_manager.is_auto_paused
            ]
            lines = [
                "[Crypto Trader] Daily PnL Report",
                f"Equity: {report.total_equity:,.0f} KRW | Return: {report.portfolio_return_pct:+.2f}%",
                f"Sharpe: {report.portfolio_sharpe:.2f} | Trades: {report.total_trades} | Win: {report.portfolio_win_rate:.0%}",
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

    def _maybe_refresh_artifacts(self) -> None:
        """Periodically refresh drift, promotion, position, health and perf artifacts."""
        if self._iteration % 10 != 0 or self._iteration == 0:
            return
        try:
            self._refresh_position_snapshot()
            self._refresh_health_snapshot()
            self._refresh_daily_performance()
            # Heavier operations only every 60 iterations
            if self._iteration % 60 == 0:
                self._refresh_portfolio_promotion()
            self._logger.info("Periodic artifact refresh completed (iteration %d)", self._iteration)
        except Exception as exc:
            self._logger.error("Artifact refresh failed: %s", exc)

    def _refresh_position_snapshot(self) -> None:
        """Save current open positions to positions.json."""
        snapshot_path = Path(self._config.runtime.position_snapshot_path)
        positions = []
        for wallet in self._wallets:
            for symbol, pos in wallet.broker.positions.items():
                positions.append({
                    "wallet": wallet.name,
                    "symbol": symbol,
                    "qty": pos.quantity,
                    "entry_price": pos.entry_price,
                    "side": "long",
                })
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
        success = True
        for r in last_results:
            if r.error is not None:
                success = False
                last_error = r.error
            if r.signal and r.signal.action.value != "hold":
                last_signal = r.signal.action.value

        snapshot = {
            "updated_at": datetime.now(UTC).isoformat(),
            "success": success,
            "consecutive_failures": 0,
            "last_error": last_error,
            "last_signal": last_signal,
            "last_order_status": None,
            "cash": total_cash,
            "open_positions": total_positions,
            "total_equity": total_equity,
            "wallet_count": len(self._wallets),
            "mode": "multi_symbol",
        }
        health_path = Path(self._config.runtime.healthcheck_path)
        health_path.parent.mkdir(parents=True, exist_ok=True)
        health_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    def _refresh_daily_performance(self) -> None:
        """Write aggregated daily-performance.json from all wallets."""
        latest_prices = getattr(self, "_latest_prices", {})

        total_trades = 0
        winning = 0
        losing = 0
        realized_pnl = 0.0
        initial_capital = 0.0
        total_equity = 0.0

        for wallet in self._wallets:
            trades = wallet.broker.closed_trades
            total_trades += len(trades)
            for t in trades:
                if t.pnl > 0:
                    winning += 1
                else:
                    losing += 1
            realized_pnl += wallet.broker.realized_pnl
            initial_capital += wallet.session_starting_equity
            total_equity += wallet.broker.equity(latest_prices)

        win_rate = winning / total_trades if total_trades > 0 else 0.0
        realized_return_pct = (realized_pnl / initial_capital) if initial_capital > 0 else 0.0

        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "trade_count": total_trades,
            "winning_trade_count": winning,
            "losing_trade_count": losing,
            "realized_pnl": realized_pnl,
            "realized_return_pct": realized_return_pct,
            "win_rate": win_rate,
            "open_position_count": sum(len(w.broker.positions) for w in self._wallets),
            "mark_to_market_equity": total_equity,
            "initial_capital": initial_capital,
            "mode": "multi_symbol",
        }
        perf_path = Path(self._config.runtime.daily_performance_path)
        perf_path.parent.mkdir(parents=True, exist_ok=True)
        perf_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

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
                "portfolio_drawdown_pct": round(self._kill_switch.state.portfolio_drawdown_pct * 100, 2),
                "daily_loss_pct": round(self._kill_switch.state.daily_loss_pct * 100, 2),
            },
        }
        heartbeat_path = artifacts_dir / "daemon-heartbeat.json"
        heartbeat_path.write_text(json.dumps(heartbeat, indent=2), encoding="utf-8")
