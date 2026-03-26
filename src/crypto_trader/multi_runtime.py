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
from crypto_trader.models import PipelineResult, RuntimeCheckpoint, StrategyRunRecord
from crypto_trader.operator.journal import StrategyRunJournal
from crypto_trader.operator.paper_trading import PaperTradeJournal
from crypto_trader.operator.runtime_state import RuntimeCheckpointStore
from crypto_trader.notifications.telegram import NullNotifier, TelegramNotifier
from crypto_trader.operator.pnl_report import PnLReportGenerator
from crypto_trader.risk.kill_switch import KillSwitch, KillSwitchConfig
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
        self._pnl_generator = PnLReportGenerator()
        self._last_pnl_notify: float = 0.0
        self._trade_journal = PaperTradeJournal(config.runtime.paper_trade_journal_path)
        self._journal_trade_counts: dict[str, int] = {w.name: 0 for w in wallets}
        self._strategy_run_journal = StrategyRunJournal(config.runtime.strategy_run_journal_path)
        snapshot_path = Path(config.runtime.runtime_checkpoint_path).parent / "pnl-snapshots.jsonl"
        self._wallet_health = WalletHealthMonitor(snapshot_path)
        self._last_health_check: float = 0.0
        self._health_check_interval = 86400  # 24h

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

        while not self._shutdown_requested:
            if self._kill_switch.is_triggered:
                self._logger.critical(
                    "Kill switch active: %s — all trading halted",
                    self._kill_switch.state.trigger_reason,
                )
                self._kill_switch.save(self._kill_switch_path)
                break

            self._maybe_check_wallet_health()
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
                result = wallet.run_once(symbol, candles)
                results.append(result)
                if result.error:
                    self._logger.error(result.message)
                else:
                    self._logger.info(result.message)
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
            self._notifier.send_message(
                f"KILL SWITCH TRIGGERED\n"
                f"Reason: {state.trigger_reason}\n"
                f"Portfolio DD: {state.portfolio_drawdown_pct:.2%}\n"
                f"Daily loss: {state.daily_loss_pct:.2%}\n"
                f"Consecutive losses: {state.consecutive_losses}\n"
                f"All trading halted."
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

    def _apply_regime_weights(self) -> None:
        """Apply regime-aware strategy weights without macro data."""
        weekend_mult = WEEKEND_POSITION_MULTIPLIER if self._is_weekend else 1.0
        for wallet in self._wallets:
            regime_weight = self._macro_adapter.strategy_weight(
                wallet.strategy_type, self._current_market_regime,
            )
            wallet.set_macro_multiplier(regime_weight * weekend_mult)

    def _save_checkpoint(self, results: list[PipelineResult]) -> None:
        store = RuntimeCheckpointStore(self._config.runtime.runtime_checkpoint_path)

        latest_prices: dict[str, float] = {}
        for r in results:
            if r.latest_price is not None:
                latest_prices[r.symbol] = r.latest_price

        wallet_states = {}
        for wallet in self._wallets:
            wallet_states[wallet.name] = {
                "strategy_type": wallet.strategy_type,
                "cash": wallet.broker.cash,
                "realized_pnl": wallet.broker.realized_pnl,
                "open_positions": len(wallet.broker.positions),
                "equity": wallet.broker.equity(latest_prices),
                "trade_count": len(wallet.broker.closed_trades),
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
        """Periodically refresh drift, promotion, and position artifacts."""
        if self._iteration % 60 != 0 or self._iteration == 0:
            return
        try:
            self._refresh_position_snapshot()
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
                    "qty": pos.qty,
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

    def _save_heartbeat(self, artifacts_dir: Path) -> None:
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
        }
        heartbeat_path = artifacts_dir / "daemon-heartbeat.json"
        heartbeat_path.write_text(json.dumps(heartbeat, indent=2), encoding="utf-8")
