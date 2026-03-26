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
from crypto_trader.models import PipelineResult, RuntimeCheckpoint
from crypto_trader.operator.paper_trading import PaperTradeJournal
from crypto_trader.operator.runtime_state import RuntimeCheckpointStore
from crypto_trader.notifications.telegram import NullNotifier, TelegramNotifier
from crypto_trader.operator.pnl_report import PnLReportGenerator
from crypto_trader.risk.kill_switch import KillSwitch
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
        self._kill_switch = kill_switch or KillSwitch()
        self._kill_switch_path = Path(
            getattr(config.runtime, "kill_switch_path", "artifacts/kill-switch.json")
        )
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

            tick_results = self._run_tick(symbols)
            self._check_kill_switch_after_tick(tick_results)
            self._save_checkpoint(tick_results)
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
                result = wallet.run_once(symbol, candles)
                results.append(result)
                if result.error:
                    self._logger.error(result.message)
                else:
                    self._logger.info(result.message)

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
                self._trade_journal.append_many(new_trades)
                self._journal_trade_counts[wallet.name] = current_count

    def _maybe_send_pnl_notify(self) -> None:
        if time.time() - self._last_pnl_notify < self.PNL_NOTIFY_INTERVAL:
            return
        try:
            report = self._pnl_generator.generate_from_checkpoint(
                self._config.runtime.runtime_checkpoint_path,
                self._config.runtime.paper_trade_journal_path,
            )
            lines = [
                "[Crypto Trader] Daily PnL",
                f"Portfolio: {report.portfolio_return_pct:+.2f}% | Trades: {report.total_trades} | Win: {report.portfolio_win_rate:.0%}",
                "---",
            ]
            for s in report.strategies:
                lines.append(f"{s.strategy}: {s.total_return_pct:+.2f}% ({s.trade_count} trades)")
            self._notifier.send_message("\n".join(lines))
            self._last_pnl_notify = time.time()
        except Exception as exc:
            self._logger.error("Failed to send PnL notification: %s", exc)

    def _save_heartbeat(self, artifacts_dir: Path) -> None:
        heartbeat = {
            "last_heartbeat": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "iteration": self._iteration + 1,
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "poll_interval_seconds": self._config.runtime.poll_interval_seconds,
        }
        heartbeat_path = artifacts_dir / "daemon-heartbeat.json"
        heartbeat_path.write_text(json.dumps(heartbeat, indent=2), encoding="utf-8")
