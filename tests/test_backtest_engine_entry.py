"""BacktestEngine이 신호 봉 다음 봉 시가에 진입하는지 검증."""
from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig, RiskConfig
from crypto_trader.models import Candle, Signal, SignalAction
from crypto_trader.risk.manager import RiskManager


class AlwaysBuyStrategy:
    """항상 BUY 신호를 반환하는 테스트용 전략."""

    def evaluate(self, candles: list[Candle], position=None, *, symbol: str = "") -> Signal:
        return Signal(
            action=SignalAction.BUY,
            confidence=1.0,
            reason="always_buy",
        )


def _make_candle(hour: int, open_: float, close: float) -> Candle:
    return Candle(
        timestamp=datetime(2024, 1, 1, hour, 0, tzinfo=UTC),
        open=open_,
        high=max(open_, close) + 1.0,
        low=min(open_, close) - 1.0,
        close=close,
        volume=1000.0,
    )


def _make_engine() -> BacktestEngine:
    config = BacktestConfig(initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0)
    risk = RiskManager(RiskConfig())
    return BacktestEngine(AlwaysBuyStrategy(), risk, config, symbol="TEST")


def test_entry_uses_next_bar_open() -> None:
    """진입가가 신호 봉 종가가 아닌 다음 봉 시가여야 한다.

    bar 0: open=100, close=110  ← 여기서 BUY 신호 발생
    bar 1: open=105, close=115  ← 여기서 진입해야 함 (시가 105)

    수정 전: entry_price ≈ 110 (신호 봉 close, 선행 편향)
    수정 후: entry_price ≈ 105 (다음 봉 open, 정상)
    """
    candles = [
        _make_candle(0, open_=100.0, close=110.0),  # bar 0: 신호 봉
        _make_candle(1, open_=105.0, close=115.0),  # bar 1: 진입 봉 (open=105)
        _make_candle(2, open_=106.0, close=112.0),  # bar 2
        _make_candle(3, open_=107.0, close=108.0),  # bar 3
        _make_candle(4, open_=106.0, close=100.0),  # bar 4: 하락으로 청산 유도
    ]
    engine = _make_engine()
    result = engine.run(candles)

    assert len(result.trade_log) >= 1, "최소 1개 거래가 발생해야 함"
    first_trade = result.trade_log[0]
    # slippage_pct=0.0 이므로 fill_price = open 그대로
    assert abs(first_trade.entry_price - 105.0) < 1.0, (
        f"진입가({first_trade.entry_price:.1f})가 다음 봉 시가(105.0) 근방이어야 함.\n"
        f"신호 봉 종가(110.0)라면 선행 편향 버그."
    )


def test_no_entry_on_last_bar() -> None:
    """마지막 봉에서 신호 발생 시 다음 봉이 없으므로 진입하지 않아야 한다."""
    candles = [
        _make_candle(0, open_=100.0, close=100.0),
        _make_candle(1, open_=100.0, close=105.0),  # 마지막 봉에서 BUY 신호
    ]
    engine = _make_engine()
    result = engine.run(candles)
    # 마지막 봉 이후 진입할 봉이 없으므로 거래 없어야 함
    assert len(result.trade_log) == 0, (
        f"마지막 봉 신호는 진입 불가여야 함. 거래 수: {len(result.trade_log)}"
    )
