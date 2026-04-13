from datetime import datetime, timezone
from crypto_trader.models import Position

def test_position_has_entry_atr_default_zero():
    pos = Position(
        symbol="KRW-BTC",
        quantity=0.001,
        entry_price=100_000_000.0,
        entry_time=datetime.now(timezone.utc),
    )
    assert pos.entry_atr == 0.0

def test_position_entry_atr_set_at_construction():
    pos = Position(
        symbol="KRW-BTC",
        quantity=0.001,
        entry_price=100_000_000.0,
        entry_time=datetime.now(timezone.utc),
        entry_atr=1_500_000.0,
    )
    assert pos.entry_atr == 1_500_000.0
