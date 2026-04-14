from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WalletBlock:
    name: str
    strategy: str | None
    start: int
    end: int


def parse_wallet_blocks(lines: list[str]) -> list[WalletBlock]:
    blocks: list[WalletBlock] = []
    block_start: int | None = None

    def build_block(start: int, end: int) -> WalletBlock | None:
        wallet_name: str | None = None
        strategy_name: str | None = None
        for line in lines[start + 1:end]:
            stripped = line.strip()
            if stripped.startswith("name = "):
                match = re.search(r'"([^"]+)"', stripped)
                if match:
                    wallet_name = match.group(1)
            elif stripped.startswith("strategy = "):
                match = re.search(r'"([^"]+)"', stripped)
                if match:
                    strategy_name = match.group(1)
        if wallet_name is None:
            return None
        return WalletBlock(
            name=wallet_name,
            strategy=strategy_name,
            start=start,
            end=end,
        )

    for index, line in enumerate(lines):
        if line.strip() == "[[wallets]]":
            if block_start is not None:
                block = build_block(block_start, index)
                if block is not None:
                    blocks.append(block)
            block_start = index
    if block_start is not None:
        block = build_block(block_start, len(lines))
        if block is not None:
            blocks.append(block)
    return blocks


def find_wallet_block(lines: list[str], wallet_name: str) -> tuple[int, int] | None:
    for block in parse_wallet_blocks(lines):
        if block.name == wallet_name:
            return block.start, block.end
    return None


def list_wallet_names_by_strategy(lines: list[str], strategy_name: str) -> list[str]:
    return [
        block.name
        for block in parse_wallet_blocks(lines)
        if block.strategy == strategy_name
    ]
