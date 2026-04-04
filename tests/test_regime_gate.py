"""Tests for regime-aware wallet active_regimes gate."""
from __future__ import annotations

from datetime import datetime, timedelta

from crypto_trader.config import RiskConfig, WalletConfig, _strategy_override_names
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import StrategyWallet


def test_active_regimes_allowed_for_all_strategies() -> None:
    """active_regimes must pass config validation for every strategy type."""
    strategy_types = [
        "momentum",
        "vpin",
        "accumulation_breakout",
        "volume_spike",
        "stealth_3gate",
        "mean_reversion",
        "funding_rate",
        "consensus",
        "kimchi_premium",
        "truth_seeker",
        "truth_seeker_v2",
        "etf_flow_admission",
    ]
    for strategy in strategy_types:
        allowed = _strategy_override_names(strategy)
        assert "active_regimes" in allowed, (
            f"active_regimes not allowed for strategy '{strategy}'"
        )


def _make_candles(n: int = 50, base: float = 100.0) -> list[Candle]:
    start = datetime(2025, 1, 1, 0, 0, 0)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=base,
            high=base * 1.01,
            low=base * 0.99,
            close=base,
            volume=1000.0,
        )
        for i in range(n)
    ]


class _StaticSignalStrategy:
    """Strategy that always returns a fixed signal."""

    def __init__(self, action: SignalAction, confidence: float = 0.9) -> None:
        self._action = action
        self._confidence = confidence

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
        macro: object = None,
    ) -> Signal:
        return Signal(
            action=self._action,
            reason="static_signal",
            confidence=self._confidence,
        )


def _make_wallet(
    active_regimes: list[str] | None = None,
    market_regime: str = "bull",
) -> StrategyWallet:
    wallet_config = WalletConfig(
        name="test_wallet",
        strategy="momentum",
        initial_capital=1_000_000.0,
        strategy_overrides=(
            {"active_regimes": active_regimes} if active_regimes is not None else {}
        ),
    )
    broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
    risk_manager = RiskManager(
        RiskConfig(
            risk_per_trade_pct=0.01,
            stop_loss_pct=0.03,
            take_profit_pct=0.06,
            max_daily_loss_pct=0.05,
            max_concurrent_positions=5,
            min_entry_confidence=0.0,
        )
    )
    wallet = StrategyWallet(
        wallet_config,
        _StaticSignalStrategy(SignalAction.BUY),
        broker,
        risk_manager,
    )
    wallet.set_market_regime(market_regime)
    return wallet


def test_regime_gate_blocks_buy_in_wrong_regime() -> None:
    """active_regimes=["bull"], regime=bear → BUY must be HOLD with regime_gate reason."""
    wallet = _make_wallet(active_regimes=["bull"], market_regime="bear")
    result = wallet.run_once("KRW-SOL", _make_candles())
    assert result.signal.action == SignalAction.HOLD
    assert "regime_gate" in result.signal.reason


def test_regime_gate_reason_contains_regime_name() -> None:
    """regime_gate reason must name the blocked regime."""
    wallet = _make_wallet(active_regimes=["bull"], market_regime="sideways")
    result = wallet.run_once("KRW-SOL", _make_candles())
    assert result.signal.action == SignalAction.HOLD
    assert "sideways" in result.signal.reason


def test_regime_gate_allows_buy_in_active_regime() -> None:
    """active_regimes includes regime → regime_gate must NOT block."""
    wallet = _make_wallet(active_regimes=["bull", "sideways"], market_regime="sideways")
    result = wallet.run_once("KRW-SOL", _make_candles())
    # regime_gate must NOT be the reason — may still be blocked by macro gate
    assert "regime_gate" not in result.signal.reason


def test_regime_gate_does_not_block_sell_exit() -> None:
    """SELL (exit) must never be blocked by active_regimes gate."""
    wallet_config = WalletConfig(
        name="test_wallet",
        strategy="momentum",
        initial_capital=1_000_000.0,
        strategy_overrides={"active_regimes": ["bull"]},
    )
    broker = PaperBroker(starting_cash=500_000.0, fee_rate=0.0005, slippage_pct=0.0005)
    # Inject an existing position so strategy sees it and can SELL
    broker.positions["KRW-SOL"] = Position(
        symbol="KRW-SOL",
        quantity=5.0,
        entry_price=100.0,
        entry_time=datetime(2025, 1, 1),
    )
    risk_manager = RiskManager(RiskConfig(min_entry_confidence=0.0))
    sell_strategy = _StaticSignalStrategy(SignalAction.SELL, confidence=0.9)
    wallet = StrategyWallet(wallet_config, sell_strategy, broker, risk_manager)
    wallet.set_market_regime("bear")  # regime would block BUY but must not block SELL

    result = wallet.run_once("KRW-SOL", _make_candles())

    assert "regime_gate" not in result.signal.reason


def test_default_active_regimes_is_bull() -> None:
    """Wallet with no active_regimes override defaults to ['bull']."""
    wallet = _make_wallet(active_regimes=None, market_regime="bull")
    assert wallet._active_regimes == ["bull"]


def test_set_market_regime_not_called_defaults_to_sideways() -> None:
    """Without set_market_regime, default is 'sideways' — bull-only wallet blocks."""
    wallet_config = WalletConfig(
        name="test_wallet",
        strategy="momentum",
        initial_capital=1_000_000.0,
        strategy_overrides={"active_regimes": ["bull"]},
    )
    broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
    risk_manager = RiskManager(RiskConfig(min_entry_confidence=0.0))
    wallet = StrategyWallet(
        wallet_config,
        _StaticSignalStrategy(SignalAction.BUY),
        broker,
        risk_manager,
    )
    # Intentionally NOT calling set_market_regime → defaults to "sideways"
    result = wallet.run_once("KRW-SOL", _make_candles())
    assert result.signal.action == SignalAction.HOLD
    assert "regime_gate" in result.signal.reason
