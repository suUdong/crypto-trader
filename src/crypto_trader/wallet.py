from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Mapping
from pathlib import Path
from dataclasses import replace
from datetime import UTC
from typing import Any, Protocol

from crypto_trader.config import (
    AppConfig,
    RegimeConfig,
    RiskConfig,
    StrategyConfig,
    WalletConfig,
    _sanitize_risk_config,
)
from crypto_trader.execution import Broker
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.macro.adapter import MacroRegimeAdapter
from crypto_trader.macro.client import MacroSnapshot
from crypto_trader.models import (
    Candle,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    PipelineResult,
    Position,
    Signal,
    SignalAction,
)
from crypto_trader.risk.manager import RiskManager
from crypto_trader.strategy.bollinger_mean_reversion import BollingerMeanReversionStrategy
from crypto_trader.strategy.bollinger_rsi import BollingerRsiStrategy
from crypto_trader.strategy.composite import CompositeStrategy
from crypto_trader.strategy.consensus import ConsensusStrategy
from crypto_trader.strategy.ema_crossover import EMACrossoverStrategy
from crypto_trader.strategy.evaluator import evaluate_strategy
from crypto_trader.strategy.funding_rate import FundingRateStrategy
from crypto_trader.strategy.kimchi_premium import KimchiPremiumStrategy
from crypto_trader.strategy.mean_reversion import MeanReversionStrategy
from crypto_trader.strategy.momentum import MomentumStrategy
from crypto_trader.strategy.momentum_pullback import MomentumPullbackStrategy
from crypto_trader.strategy.obi import OBIStrategy
from crypto_trader.strategy.bb_squeeze_independent import BBSqueezeIndependentStrategy
from crypto_trader.strategy.etf_flow_admission import EtfFlowAdmissionStrategy
from crypto_trader.strategy.rsi_mr_bear import RsiMrBearStrategy
from crypto_trader.strategy.stealth_3gate import Stealth3GateStrategy
from crypto_trader.strategy.volatility_breakout import VolatilityBreakoutStrategy
from crypto_trader.strategy.volume_spike import VolumeSpikeStrategy
from crypto_trader.strategy.vpin import VPINStrategy

# --- Lab Mode Strategies ---
from crypto_trader.strategy.btc_regime_rotation import BtcRegimeRotationStrategy
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.strategy.truth_seeker_v2 import TruthSeekerV2Strategy
from crypto_trader.strategy.experimental.accumulation_hunter import AccumulationBreakoutStrategy


class StrategyProtocol(Protocol):
    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal: ...


def create_strategy(
    strategy_type: str,
    strategy_config: StrategyConfig,
    regime_config: RegimeConfig,
    extra_params: Mapping[str, Any] | None = None,
) -> StrategyProtocol:
    params = extra_params or {}
    if strategy_type == "momentum":
        fg_block = (
            int(params["fear_greed_block_threshold"])
            if params.get("fear_greed_block_threshold") is not None
            else None
        )
        return MomentumStrategy(
            strategy_config, regime_config, fear_greed_block_threshold=fg_block
        )
    if strategy_type == "momentum_pullback":
        return MomentumPullbackStrategy(strategy_config, regime_config)
    if strategy_type == "bollinger_rsi":
        return BollingerRsiStrategy(strategy_config, regime_config)
    if strategy_type == "bollinger_mr":
        return BollingerMeanReversionStrategy(
            strategy_config,
            adx_ceiling=float(params.get("adx_ceiling", 25.0)),
            squeeze_lookback=int(params.get("squeeze_lookback", 50)),
            squeeze_threshold_pct=float(params.get("squeeze_threshold_pct", 20.0)),
        )
    if strategy_type == "mean_reversion":
        return MeanReversionStrategy(
            strategy_config,
            regime_config,
            weekend_bollinger_window=(
                int(params["weekend_bollinger_window"])
                if params.get("weekend_bollinger_window") is not None
                else None
            ),
            weekend_bollinger_stddev=(
                float(params["weekend_bollinger_stddev"])
                if params.get("weekend_bollinger_stddev") is not None
                else None
            ),
            weekend_rsi_period=(
                int(params["weekend_rsi_period"])
                if params.get("weekend_rsi_period") is not None
                else None
            ),
            weekend_rsi_oversold_floor=(
                float(params["weekend_rsi_oversold_floor"])
                if params.get("weekend_rsi_oversold_floor") is not None
                else None
            ),
            weekend_rsi_recovery_ceiling=(
                float(params["weekend_rsi_recovery_ceiling"])
                if params.get("weekend_rsi_recovery_ceiling") is not None
                else None
            ),
            weekend_noise_lookback=(
                int(params["weekend_noise_lookback"])
                if params.get("weekend_noise_lookback") is not None
                else None
            ),
            weekend_adx_threshold=(
                float(params["weekend_adx_threshold"])
                if params.get("weekend_adx_threshold") is not None
                else None
            ),
            weekend_max_holding_bars=(
                int(params["weekend_max_holding_bars"])
                if params.get("weekend_max_holding_bars") is not None
                else None
            ),
            weekend_volume_filter_mult=(
                float(params["weekend_volume_filter_mult"])
                if params.get("weekend_volume_filter_mult") is not None
                else None
            ),
            fear_greed_extreme_threshold=(
                int(params["fear_greed_extreme_threshold"])
                if params.get("fear_greed_extreme_threshold") is not None
                else None
            ),
            fear_greed_entry_rsi_ceiling=(
                float(params["fear_greed_entry_rsi_ceiling"])
                if params.get("fear_greed_entry_rsi_ceiling") is not None
                else None
            ),
            fear_greed_band_buffer_pct=float(params.get("fear_greed_band_buffer_pct", 0.0)),
            fear_greed_confidence_boost=float(params.get("fear_greed_confidence_boost", 0.0)),
        )
    if strategy_type == "kimchi_premium":
        return KimchiPremiumStrategy(
            strategy_config,
            min_trade_interval_bars=int(params.get("min_trade_interval_bars", 12)),
            min_confidence=float(params.get("min_confidence", 0.6)),
            cooldown_hours=float(params.get("cooldown_hours", 24.0)),
        )
    if strategy_type == "obi":
        return OBIStrategy(strategy_config)
    if strategy_type == "vpin":
        return VPINStrategy(
            strategy_config,
            vpin_high_threshold=float(params.get("vpin_high_threshold", 0.7)),
            vpin_low_threshold=float(params.get("vpin_low_threshold", 0.45)),
            bucket_count=int(params.get("bucket_count", 20)),
            vpin_momentum_threshold=float(params.get("vpin_momentum_threshold", 0.01)),
            vpin_rsi_ceiling=float(params.get("vpin_rsi_ceiling", 70.0)),
            vpin_rsi_floor=float(params.get("vpin_rsi_floor", 30.0)),
            ema_trend_period=int(params.get("ema_trend_period", 20)),
            adx_threshold=float(params.get("adx_threshold", 15.0)),
        )
    if strategy_type == "truth_seeker":
        return TruthSeekerStrategy(
            strategy_config,
            vpin_threshold=float(params.get("vpin_threshold", 0.45)),
            obi_threshold=float(params.get("obi_threshold", 0.12)),
        )
    if strategy_type == "truth_seeker_v2":
        return TruthSeekerV2Strategy(
            strategy_config,
            vpin_threshold=float(params.get("vpin_threshold", 0.45)),
            obi_threshold=float(params.get("obi_threshold", 0.12)),
            toxic_vpin_threshold=float(params.get("toxic_vpin_threshold", 0.80)),
        )
    if strategy_type == "accumulation_breakout":
        return AccumulationBreakoutStrategy(
            strategy_config,
            vpin_threshold=float(params.get("vpin_threshold", 0.55)),
            cvd_slope_threshold=float(params.get("cvd_slope_threshold", 10.0)),
            volatility_ceiling=float(params.get("volatility_ceiling", 0.015)),
            stealth_lookback=int(params.get("stealth_lookback", 36)),
            stealth_rs_low=float(params.get("stealth_rs_low", 0.5)),
            stealth_rs_high=float(params.get("stealth_rs_high", 1.0)),
        )
    if strategy_type == "funding_rate":
        return FundingRateStrategy(
            strategy_config,
            high_funding_threshold=float(params.get("high_funding_threshold", 0.0003)),
            extreme_funding_threshold=float(params.get("extreme_funding_threshold", 0.0005)),
            negative_funding_threshold=float(params.get("negative_funding_threshold", -0.0001)),
            deep_negative_threshold=float(params.get("deep_negative_threshold", -0.0003)),
            rsi_oversold=float(params.get("rsi_oversold", 35.0)),
            rsi_overbought=float(params.get("rsi_overbought", 70.0)),
            momentum_lookback=int(params.get("momentum_lookback", 10)),
            min_confidence=float(params.get("min_confidence", 0.5)),
            max_holding_bars=int(params.get("max_holding_bars", 48)),
            cooldown_bars=int(params.get("cooldown_bars", 6)),
        )
    if strategy_type == "etf_flow_admission":
        return EtfFlowAdmissionStrategy(
            strategy_config,
            max_fear_index=int(params.get("max_fear_index", 20)),
            max_kimchi_premium=float(params.get("max_kimchi_premium", -0.002)),
            rsi_oversold=float(params.get("rsi_oversold", 30.0)),
            std_multiplier=float(params.get("std_multiplier", 0.5)),
            min_absolute_flow=float(params.get("min_absolute_flow", 20.0)),
        )
    if strategy_type == "ema_crossover":
        return EMACrossoverStrategy(strategy_config)
    if strategy_type == "volatility_breakout":
        return VolatilityBreakoutStrategy(
            strategy_config,
            k_base=strategy_config.k_base,
            noise_lookback=strategy_config.noise_lookback,
            ma_filter_period=strategy_config.ma_filter_period,
            max_holding_bars=strategy_config.max_holding_bars,
        )
    if strategy_type == "volume_spike":
        return VolumeSpikeStrategy(
            strategy_config,
            regime_config,
            spike_mult=float(params.get("spike_mult", 2.5)),
            volume_window=int(params.get("volume_window", 20)),
            min_body_ratio=float(params.get("min_body_ratio", 0.4)),
        )
    if strategy_type == "consensus":
        sub_strategy_names = params.get("sub_strategies", ["momentum", "vpin", "ema_crossover"])
        min_agree = int(params.get("min_agree", 2))
        sub_strategies = [
            create_strategy(name, strategy_config, regime_config, extra_params=params)
            for name in sub_strategy_names
            if name != "consensus"  # prevent recursion
        ]
        min_confidence_sum = float(params.get("min_confidence_sum", 0.0))
        weights_raw = params.get("weights")
        weights = [float(w) for w in weights_raw] if weights_raw else None
        quorum_threshold = float(params.get("quorum_threshold", 0.0))
        exit_mode = str(params.get("exit_mode", "any"))
        return ConsensusStrategy(
            sub_strategies,
            min_agree=min_agree,
            min_confidence_sum=min_confidence_sum,
            weights=weights,
            quorum_threshold=quorum_threshold,
            exit_mode=exit_mode,
        )
    if strategy_type == "btc_regime_rotation":
        min_alpha = float(params.get("min_alpha", 1.0))
        return BtcRegimeRotationStrategy(strategy_config, min_alpha=min_alpha)
    if strategy_type == "stealth_3gate":
        return Stealth3GateStrategy(
            strategy_config,
            stealth_window=int(params.get("stealth_window", 36)),
            stealth_sma_period=int(params.get("stealth_sma_period", 20)),
            rs_low=float(params.get("rs_low", 0.5)),
            rs_high=float(params.get("rs_high", 1.0)),
            cvd_slope_threshold=float(params.get("cvd_slope_threshold", 0.0)),
            btc_stealth_gate=bool(params.get("btc_stealth_gate", True)),
            min_confidence=float(params.get("min_confidence", 0.3)),
        )
    if strategy_type == "bb_squeeze_independent":
        return BBSqueezeIndependentStrategy(
            strategy_config,
            squeeze_pctile_th=float(params.get("squeeze_pctile_th", 40.0)),
            squeeze_lb=int(params.get("squeeze_lb", 15)),
            upper_ratio=float(params.get("upper_ratio", 0.97)),
            adx_threshold=float(params.get("adx_threshold", 25.0)),
            tp_atr=float(params.get("tp_atr", 5.0)),
            sl_atr=float(params.get("sl_atr", 2.0)),
            bb_period=int(params.get("bb_period", 20)),
            bb_std=float(params.get("bb_std", 2.0)),
            bw_pctile_lb=int(params.get("bw_pctile_lb", 120)),
            ema_period=int(params.get("ema_period", 20)),
            atr_period=int(params.get("atr_period", 20)),
            expansion_lb=int(params.get("expansion_lb", 4)),
            trail_atr=float(params.get("trail_atr", 0.3)),
            min_profit_atr=float(params.get("min_profit_atr", 1.5)),
            max_hold=int(params.get("max_hold", 20)),
            btc_sma_period=int(params.get("btc_sma_period", 200)),
        )
    if strategy_type == "rsi_mr_bear":
        return RsiMrBearStrategy(
            strategy_config,
            rsi_entry=float(params.get("rsi_entry", 25.0)),
            rsi_exit=float(params.get("rsi_exit", 50.0)),
            sl_pct=float(params.get("sl_pct", 0.02)),
            max_hold=int(params.get("max_hold", 24)),
            rsi_period=int(params.get("rsi_period", 14)),
            btc_sma_period=int(params.get("btc_sma_period", 200)),
        )
    return CompositeStrategy(strategy_config, regime_config)




class StrategyWallet:
    _LIMIT_FRIENDLY_STRATEGIES = frozenset(
        {
            "bollinger_mr",
            "bollinger_rsi",
            "funding_rate",
            "kimchi_premium",
            "mean_reversion",
            "momentum_pullback",
        }
    )

    def __init__(
        self,
        wallet_config: WalletConfig,
        strategy: StrategyProtocol,
        broker: Broker,
        risk_manager: RiskManager,
    ) -> None:
        self.name = wallet_config.name
        self.strategy_type = wallet_config.strategy
        self.strategy = strategy
        self.broker = broker
        self.risk_manager = risk_manager
        self.allowed_symbols: set[str] = (
            set(wallet_config.symbols) if wallet_config.symbols else set()
        )
        self.config_initial_capital = wallet_config.initial_capital
        self.session_starting_equity = broker.cash
        self._logger = logging.getLogger(f"{__name__}.{self.name}")
        self._macro_multiplier: float = 1.0
        self._macro_snapshot: MacroSnapshot | None = None
        self._macro_adapter = MacroRegimeAdapter()
        self._prefer_limit_entries = bool(
            wallet_config.strategy_overrides.get(
                "prefer_limit_entries",
                wallet_config.strategy in self._LIMIT_FRIENDLY_STRATEGIES,
            )
        )
        self._btc_stealth_gate: bool = bool(
            wallet_config.strategy_overrides.get("btc_stealth_gate", False)
        )
        self._btc_30bar_gate: bool = bool(
            wallet_config.strategy_overrides.get("btc_30bar_gate", False)
        )
        # Regime-aware gate: list of regime strings this wallet may trade in.
        # Populated from strategy_overrides["active_regimes"]; defaults to ["bull"].
        # Gate only fires when active_regimes is explicitly configured in strategy_overrides.
        self._active_regimes: list[str] = list(
            wallet_config.strategy_overrides.get("active_regimes", ["bull"])
        )
        self._active_regimes_explicit: bool = "active_regimes" in wallet_config.strategy_overrides
        # Injected per-tick by multi_runtime via set_market_regime(); defaults to "sideways"
        # so un-initialized wallets do not accidentally trade in unknown regimes.
        self._current_market_regime: str = "sideways"
        self._limit_confidence_cap = float(
            wallet_config.strategy_overrides.get("limit_confidence_cap", 0.72)
        )
        self._market_confidence_floor = float(
            wallet_config.strategy_overrides.get("market_confidence_floor", 0.82)
        )
        self._limit_volume_floor = float(
            wallet_config.strategy_overrides.get("limit_volume_floor", 1.0)
        )
        self._execution_cost_multiplier = float(
            wallet_config.strategy_overrides.get("execution_cost_multiplier", 1.1)
        )
        _fg_raw = wallet_config.strategy_overrides.get("fear_greed_block_threshold")
        self._fear_greed_block_threshold: int | None = (
            int(_fg_raw) if _fg_raw is not None else None
        )
        self._crypto_confidence_threshold: float = float(
            wallet_config.strategy_overrides.get("crypto_confidence_threshold", 0.65)
        )

    def set_macro_multiplier(self, multiplier: float) -> None:
        self._macro_multiplier = multiplier

    def set_macro_snapshot(self, snapshot: MacroSnapshot | None) -> None:
        self._macro_snapshot = snapshot
        if hasattr(self.strategy, "set_macro_snapshot"):
            self.strategy.set_macro_snapshot(snapshot)

    def set_market_regime(self, regime: str) -> None:
        """Inject the current market regime string (bull/sideways/bear) from multi_runtime."""
        self._current_market_regime = regime

    def adjust_capital(self, delta_cash: float) -> None:
        if abs(delta_cash) <= 0:
            return
        if self.broker.cash + delta_cash < -1e-9:
            raise ValueError(f"{self.name} cash would go negative after adjustment")
        self.broker.cash += delta_cash
        self.session_starting_equity = max(0.0, self.session_starting_equity + delta_cash)
        self.risk_manager.adjust_capital_base(delta_cash)

    def position_metrics(self, latest_prices: Mapping[str, float]) -> list[dict[str, float | str]]:
        metrics: list[dict[str, float | str]] = []
        for symbol, position in self.broker.positions.items():
            market_price = float(latest_prices.get(symbol, position.entry_price))
            metrics.append(
                {
                    "wallet": self.name,
                    "symbol": symbol,
                    "qty": position.quantity,
                    "entry_price": position.entry_price,
                    "market_price": market_price,
                    "unrealized_pnl": position.unrealized_pnl(market_price),
                    "unrealized_pnl_pct": position.pnl_pct(market_price),
                    "marked_value": position.quantity * market_price,
                    "side": position.side,
                    "entry_time": position.entry_time.isoformat(),
                }
            )
        return metrics

    def reduce_position(
        self,
        symbol: str,
        latest_price: float,
        requested_at: dt.datetime,
        *,
        keep_fraction: float,
        reason: str,
        volume_ratio: float = 1.0,
    ) -> OrderResult | None:
        position = self.broker.positions.get(symbol)
        if position is None:
            return None
        clamped_keep = max(0.0, min(1.0, keep_fraction))
        sell_qty = position.quantity * (1.0 - clamped_keep)
        if sell_qty <= 1e-8:
            return None
        if sell_qty >= position.quantity - 1e-8:
            sell_qty = position.quantity
        order = self.broker.submit_order(
            OrderRequest(
                symbol=symbol,
                side=OrderSide.SELL,
                quantity=sell_qty,
                requested_at=requested_at,
                reason=reason,
            ),
            latest_price,
            volume_ratio=volume_ratio,
        )
        if order is not None and order.status == "filled" and order.side is OrderSide.SELL:
            entry_value = position.entry_price * position.quantity
            if entry_value > 0:
                pnl_pct = (order.fill_price - position.entry_price) / position.entry_price
                self.risk_manager.record_trade(pnl_pct)
        return order

    def _marked_equity(self, symbol: str, latest_price: float) -> float:
        prices = {
            open_symbol: (
                latest_price if open_symbol == symbol else open_position.entry_price
            )
            for open_symbol, open_position in self.broker.positions.items()
        }
        return self.broker.equity(prices)

    def _read_btc_regime(self) -> bool | None:
        """Read BTC bull/bear regime from stealth-watchlist.json (written by lab loop).

        Returns True (bull), False (bear), or None (file missing/stale > 3h).
        Only checked when self._btc_stealth_gate is True.
        """
        if not self._btc_stealth_gate:
            return None
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        path = Path("artifacts/stealth-watchlist.json")
        try:
            data = _json.loads(path.read_text())
            updated_at = _dt.fromisoformat(data["updated_at"])
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=_tz.utc)
            age_hours = (_dt.now(_tz.utc) - updated_at).total_seconds() / 3600
            if age_hours > 3.0:
                return None  # stale — don't gate on old data
            return bool(data.get("btc_bull_regime", True))
        except Exception:
            return None  # fail open

    def _read_btc_30bar_pos(self) -> bool | None:
        """Read BTC 30-bar momentum from stealth-watchlist.json.

        Returns True (30-bar return > 0%), False, or None (file missing/stale > 3h).
        Only checked when self._btc_30bar_gate is True.
        """
        if not self._btc_30bar_gate:
            return None
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        path = Path("artifacts/stealth-watchlist.json")
        try:
            data = _json.loads(path.read_text())
            updated_at = _dt.fromisoformat(data["updated_at"])
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=_tz.utc)
            age_hours = (_dt.now(_tz.utc) - updated_at).total_seconds() / 3600
            if age_hours > 3.0:
                return None  # stale — don't gate on old data
            return bool(data.get("btc_30bar_pos", True))
        except Exception:
            return None  # fail open

    @staticmethod
    def _volume_ratio(candles: list[Candle], window: int = 20) -> float:
        """Current bar volume / rolling average volume."""
        if len(candles) < 2:
            return 1.0
        lookback = candles[-(window + 1) : -1] if len(candles) > window else candles[:-1]
        avg_vol = sum(c.volume for c in lookback) / max(1, len(lookback))
        if avg_vol <= 0:
            return 1.0
        return candles[-1].volume / avg_vol

    def _choose_entry_order_type(self, signal: Signal, volume_ratio: float) -> OrderType:
        if signal.confidence >= self._market_confidence_floor:
            return OrderType.MARKET
        if (
            self._prefer_limit_entries
            and volume_ratio >= self._limit_volume_floor
            and signal.confidence <= self._limit_confidence_cap
        ):
            return OrderType.LIMIT
        return OrderType.MARKET

    def _expected_round_trip_drag_pct(
        self,
        entry_order_type: OrderType,
        volume_ratio: float,
    ) -> float:
        return self.broker.estimate_round_trip_cost_pct(
            entry_order_type,
            volume_ratio=volume_ratio,
            exit_order_type=OrderType.MARKET,
        ) * self._execution_cost_multiplier

    def _execution_edge_budget_pct(self, signal: Signal) -> float:
        confidence_excess = max(0.0, signal.confidence - self.risk_manager.effective_min_confidence)
        target_move = max(
            self.risk_manager._config.take_profit_pct,
            self.risk_manager._config.stop_loss_pct,
        )
        return confidence_excess * target_move

    def _passes_execution_cost_gate(
        self,
        signal: Signal,
        entry_order_type: OrderType,
        volume_ratio: float,
    ) -> bool:
        return self._execution_edge_budget_pct(signal) >= self._expected_round_trip_drag_pct(
            entry_order_type,
            volume_ratio,
        )

    _MIN_NOTIONAL: float = 10_000.0  # KRW — trades below this are fee-dominated

    def run_once(self, symbol: str, candles: list[Candle]) -> PipelineResult:
        try:
            self.risk_manager.update_atr_from_candles(candles)
            self.risk_manager.tick_cooldown()
            position = self.broker.positions.get(symbol)
            signal = evaluate_strategy(
                self.strategy,
                candles,
                position,
                symbol=symbol,
                macro=self._macro_snapshot,
            )
            latest_price = candles[-1].close
            order: OrderResult | None = None
            utc_hour: int | None = None
            if candles:
                ts = candles[-1].timestamp
                # Ensure we use UTC hour; fall back to raw hour if tz-naive
                if ts.tzinfo is not None:
                    utc_hour = ts.astimezone(UTC).hour
                else:
                    utc_hour = ts.hour
            vol_ratio = self._volume_ratio(candles)

            # --- active_regimes gate (fast, no I/O) — must run before macro gate ---
            if position is None and signal.action is SignalAction.BUY and self._active_regimes_explicit:
                if self._current_market_regime not in self._active_regimes:
                    self._logger.info(
                        "[%s] BUY blocked by active_regimes gate: regime=%s not in %s",
                        symbol,
                        self._current_market_regime,
                        self._active_regimes,
                    )
                    signal = Signal(
                        action=SignalAction.HOLD,
                        reason=f"regime_gate: {self._current_market_regime}",
                        confidence=signal.confidence,
                        indicators=signal.indicators,
                        context={**(signal.context or {}), "original_action": "BUY"},
                    )

            # --- Macro regime gate: block entries in adverse regimes ---
            force_fear_buy = str(signal.context.get("force_fear_buy", "")).lower() == "true"
            regime_blocked, regime_reason = self._macro_adapter.should_block_entry(
                self._macro_snapshot,
                strategy_type=self.strategy_type,
                force_fear_buy=force_fear_buy,
                btc_bull_regime=self._read_btc_regime(),
                fear_greed_block_threshold=self._fear_greed_block_threshold,
                crypto_confidence_threshold=self._crypto_confidence_threshold,
            )
            effective_min_confidence = self._macro_adapter.confidence_floor(
                self._macro_snapshot, self.risk_manager.effective_min_confidence,
            )

            # BTC 30-bar momentum gate (Gate2): blocks entry if BTC 30-bar return <= 0
            if not regime_blocked and self._btc_30bar_gate:
                btc_30bar_ok = self._read_btc_30bar_pos()
                if btc_30bar_ok is False:
                    regime_blocked = True
                    regime_reason = "btc_30bar_gate: BTC 30-bar return not positive"

            if position is None and signal.action is SignalAction.BUY and regime_blocked:
                self._logger.info(
                    "[%s] BUY blocked by regime gate: %s (signal_confidence=%.2f)",
                    symbol, regime_reason, signal.confidence,
                )
                signal = Signal(
                    action=SignalAction.HOLD,
                    reason=regime_reason,
                    confidence=signal.confidence,
                    indicators=signal.indicators,
                    context={**(signal.context or {}), "original_action": "BUY"},
                )

            if (
                position is None
                and signal.action is SignalAction.BUY
                and not regime_blocked
                and signal.confidence >= effective_min_confidence
                and not self.risk_manager.in_cooldown
                and not self.risk_manager.is_auto_paused
            ):
                marked_equity = self._marked_equity(symbol, latest_price)
                if self.risk_manager.can_open(
                    active_positions=len(self.broker.positions),
                    realized_pnl=self.broker.realized_pnl,
                    starting_equity=self.session_starting_equity,
                    current_equity=marked_equity,
                ):
                    quantity = self.risk_manager.size_position(
                        self.broker.cash,
                        latest_price,
                        self._macro_multiplier,
                        utc_hour=utc_hour,
                    )
                    notional = quantity * latest_price
                    if quantity > 0 and notional >= self._MIN_NOTIONAL:
                        entry_order_type = self._choose_entry_order_type(signal, vol_ratio)
                        if not self._passes_execution_cost_gate(
                            signal,
                            entry_order_type,
                            vol_ratio,
                        ):
                            signal = Signal(
                                action=signal.action,
                                reason="execution_edge_below_cost_threshold",
                                confidence=signal.confidence,
                                indicators=signal.indicators,
                                context=signal.context,
                            )
                        else:
                            now = candles[-1].timestamp
                            order = self.broker.submit_order(
                                OrderRequest(
                                    symbol=symbol,
                                    side=OrderSide.BUY,
                                    quantity=quantity,
                                    requested_at=now,
                                    reason=signal.reason,
                                    confidence=signal.confidence,
                                    order_type=entry_order_type,
                                ),
                                latest_price,
                                candle_index=len(candles) - 1,
                                volume_ratio=vol_ratio,
                            )
            elif position is not None:
                # Circuit breaker: force-close when daily loss limit hit
                marked_equity = self._marked_equity(symbol, latest_price)
                if self.risk_manager.should_force_exit(
                    self.broker.realized_pnl,
                    self.session_starting_equity,
                    marked_equity,
                ):
                    now = candles[-1].timestamp
                    order = self.broker.submit_order(
                        OrderRequest(
                            symbol=symbol,
                            side=OrderSide.SELL,
                            quantity=position.quantity,
                            requested_at=now,
                            reason="circuit_breaker",
                            order_type=OrderType.MARKET,
                        ),
                        latest_price,
                        volume_ratio=vol_ratio,
                    )
                    if order is not None and order.status == "filled":
                        entry_value = position.entry_price * position.quantity
                        if entry_value > 0:
                            pnl_pct = (
                                order.fill_price - position.entry_price
                            ) / position.entry_price
                            self.risk_manager.record_trade(pnl_pct)
                    message = (
                        f"[{self.name}] {symbol} price={latest_price:.2f} "
                        f"signal=CIRCUIT_BREAKER reason=daily_loss_limit"
                    )
                    if order is not None:
                        message += (
                            f" order={order.status} side={order.side.value} "
                            f"qty={order.quantity:.8f} fill={order.fill_price:.2f}"
                        )
                    return PipelineResult(
                        symbol=symbol,
                        signal=Signal(
                            action=SignalAction.SELL,
                            reason="circuit_breaker",
                            confidence=1.0,
                        ),
                        order=order,
                        message=message,
                        latest_price=latest_price,
                    )

                holding_bars = (
                    0 if position.entry_index is None else len(candles) - position.entry_index - 1
                )
                exit_reason = self.risk_manager.exit_reason(
                    position,
                    latest_price,
                    holding_bars=holding_bars,
                )
                should_sell = signal.action is SignalAction.SELL or exit_reason is not None
                if should_sell:
                    now = candles[-1].timestamp
                    # Partial take-profit: sell only a fraction, mark position
                    if exit_reason == "partial_take_profit":
                        sell_qty = position.quantity * self.risk_manager._config.partial_tp_pct
                        sell_qty = max(sell_qty, 1e-8)  # floor
                    else:
                        sell_qty = position.quantity
                    order = self.broker.submit_order(
                        OrderRequest(
                            symbol=symbol,
                            side=OrderSide.SELL,
                            quantity=sell_qty,
                            requested_at=now,
                            reason=exit_reason or signal.reason,
                            order_type=OrderType.MARKET,
                        ),
                        latest_price,
                        volume_ratio=vol_ratio,
                    )
                    # Mark partial TP taken so it doesn't re-trigger
                    if (
                        exit_reason == "partial_take_profit"
                        and order is not None
                        and order.status == "filled"
                    ):
                        remaining_pos = self.broker.positions.get(symbol)
                        if remaining_pos is not None:
                            remaining_pos.partial_tp_taken = True
                    if (
                        order is not None
                        and order.status == "filled"
                        and order.side is OrderSide.SELL
                    ):
                        entry_value = position.entry_price * position.quantity
                        if entry_value > 0:
                            pnl_pct = (
                                order.fill_price - position.entry_price
                            ) / position.entry_price
                            self.risk_manager.record_trade(pnl_pct)

            message = (
                f"[{self.name}] {symbol} price={latest_price:.2f} "
                f"signal={signal.action.value} reason={signal.reason}"
            )
            if order is not None:
                message += (
                    f" order={order.status} order_type={order.order_type.value} "
                    f"side={order.side.value} "
                    f"qty={order.quantity:.8f} fill={order.fill_price:.2f}"
                )
            return PipelineResult(
                symbol=symbol,
                signal=signal,
                order=order,
                message=message,
                latest_price=latest_price,
            )
        except Exception as exc:
            self._logger.exception("Wallet %s failed for %s", self.name, symbol)
            signal = Signal(action=SignalAction.HOLD, reason="wallet_error", confidence=0.0)
            return PipelineResult(
                symbol=symbol,
                signal=signal,
                order=None,
                message=f"[{self.name}] {symbol} error={exc}",
                latest_price=None,
                error=str(exc),
            )


def build_wallets(config: AppConfig) -> list[StrategyWallet]:
    wallets: list[StrategyWallet] = []
    go_live_set = set(config.trading.go_live_wallets)
    use_live = not config.trading.paper_trading and config.credentials.has_upbit_credentials
    for wc in config.wallets:
        strategy_config = _strategy_config_for_wallet(config.strategy, wc)
        risk_config = _risk_config_for_wallet(config, wc)
        strategy = create_strategy(
            wc.strategy,
            strategy_config,
            config.regime,
            wc.strategy_overrides,
        )
        wallet_goes_live = use_live and (not go_live_set or wc.name in go_live_set)
        broker: Broker
        if wallet_goes_live:
            from crypto_trader.execution.live import LiveBroker

            broker = LiveBroker(
                access_key=config.credentials.upbit_access_key,
                secret_key=config.credentials.upbit_secret_key,
                starting_cash=wc.initial_capital,
                fee_rate=config.backtest.fee_rate,
            )
        else:
            broker = PaperBroker(
                starting_cash=wc.initial_capital,
                fee_rate=config.backtest.fee_rate,
                slippage_pct=config.backtest.slippage_pct,
                maker_fee_rate=float(
                    wc.strategy_overrides.get("maker_fee_rate", config.backtest.fee_rate)
                ),
            )
        strategy_hold = strategy_config.max_holding_bars
        risk_manager = RiskManager(
            risk_config,
            trailing_stop_pct=risk_config.trailing_stop_pct,
            atr_stop_multiplier=risk_config.atr_stop_multiplier,
            max_holding_bars=strategy_hold,
        )
        wallets.append(StrategyWallet(wc, strategy, broker, risk_manager))
    return wallets


def _strategy_config_for_wallet(
    base: StrategyConfig,
    wallet_config: WalletConfig,
) -> StrategyConfig:
    strategy_fields = set(StrategyConfig.__dataclass_fields__)
    overrides = {
        key: value
        for key, value in wallet_config.strategy_overrides.items()
        if key in strategy_fields
    }
    return replace(base, **overrides)


def _risk_config_for_wallet(config: AppConfig, wallet_config: WalletConfig) -> RiskConfig:
    risk_fields = set(type(config.risk).__dataclass_fields__)
    overrides = {
        key: value for key, value in wallet_config.risk_overrides.items() if key in risk_fields
    }
    return _sanitize_risk_config(replace(config.risk, **overrides))
