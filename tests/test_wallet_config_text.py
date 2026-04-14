from __future__ import annotations

from crypto_trader.operator.wallet_config_text import (
    find_wallet_block,
    list_wallet_names_by_strategy,
    parse_wallet_blocks,
)


def test_parse_wallet_blocks_skips_commented_blocks() -> None:
    lines = [
        '# [[wallets]]',
        '# name = "commented_wallet"',
        '# strategy = "accumulation_breakout"',
        '[[wallets]]',
        'name = "live_wallet"',
        'strategy = "accumulation_breakout"',
        'symbols = ["KRW-BTC"]',
    ]

    blocks = parse_wallet_blocks(lines)

    assert len(blocks) == 1
    assert blocks[0].name == "live_wallet"
    assert blocks[0].strategy == "accumulation_breakout"


def test_find_wallet_block_returns_active_range_only() -> None:
    lines = [
        '# name = "accumulation_tree_wallet"',
        '# symbols = ["KRW-OLD"]',
        '[[wallets]]',
        'name = "momentum_wallet"',
        'strategy = "momentum"',
        'symbols = ["KRW-BTC"]',
    ]

    assert find_wallet_block(lines, "accumulation_tree_wallet") is None
    assert find_wallet_block(lines, "momentum_wallet") == (2, 6)


def test_list_wallet_names_by_strategy_filters_active_wallets() -> None:
    lines = [
        '[[wallets]]',
        'name = "accumulation_a"',
        'strategy = "accumulation_breakout"',
        'symbols = ["KRW-A"]',
        '',
        '# [[wallets]]',
        '# name = "accumulation_b"',
        '# strategy = "accumulation_breakout"',
        '',
        '[[wallets]]',
        'name = "momentum_wallet"',
        'strategy = "momentum"',
        'symbols = ["KRW-BTC"]',
    ]

    assert list_wallet_names_by_strategy(lines, "accumulation_breakout") == [
        "accumulation_a",
    ]
