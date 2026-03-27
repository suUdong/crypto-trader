from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.wallet import StrategyWallet


class StrategyComparisonReport:
    def generate(
        self,
        wallets: list[StrategyWallet],
        symbols: list[str],
        latest_prices: dict[str, float],
    ) -> str:
        now = datetime.now(UTC).isoformat()
        lines: list[str] = []
        lines.append("# Strategy Comparison Report")
        lines.append(f"\nGenerated: {now}\n")
        lines.append(f"Symbols: {', '.join(symbols)}\n")
        lines.append(f"Wallets: {len(wallets)}\n")

        lines.append("## Per-Wallet Summary\n")
        lines.append(
            "| Wallet | Strategy | Cash | Realized PnL | "
            "Open Positions | Equity | Trades | Win Rate |"
        )
        lines.append(
            "|--------|----------|------|-------------|"
            "----------------|--------|--------|----------|"
        )

        wallet_metrics: list[dict[str, object]] = []
        for wallet in wallets:
            equity = wallet.broker.equity(latest_prices)
            trades = wallet.broker.closed_trades
            trade_count = len(trades)
            winning = sum(1 for t in trades if t.pnl > 0)
            win_rate = winning / trade_count if trade_count > 0 else 0.0
            return_pct = (
                (equity - wallet.session_starting_equity)
                / max(1.0, wallet.session_starting_equity)
                * 100
            )
            lines.append(
                f"| {wallet.name} | {wallet.strategy_type} | "
                f"{wallet.broker.cash:,.0f} | {wallet.broker.realized_pnl:,.0f} | "
                f"{len(wallet.broker.positions)} | {equity:,.0f} | "
                f"{trade_count} | {win_rate:.1%} |"
            )
            wallet_metrics.append(
                {
                    "name": wallet.name,
                    "strategy": wallet.strategy_type,
                    "equity": equity,
                    "return_pct": return_pct,
                    "trade_count": trade_count,
                    "win_rate": win_rate,
                    "realized_pnl": wallet.broker.realized_pnl,
                }
            )

        lines.append("\n## Per-Symbol Positions\n")
        for wallet in wallets:
            if not wallet.broker.positions:
                continue
            lines.append(f"### {wallet.name}\n")
            lines.append("| Symbol | Qty | Entry Price | Market Price | Unrealized PnL |")
            lines.append("|--------|-----|-------------|-------------|----------------|")
            for symbol, pos in wallet.broker.positions.items():
                mkt = latest_prices.get(symbol, pos.entry_price)
                upnl = (mkt - pos.entry_price) * pos.quantity
                lines.append(
                    f"| {symbol} | {pos.quantity:.8f} | {pos.entry_price:,.0f} | "
                    f"{mkt:,.0f} | {upnl:,.0f} |"
                )

        if wallet_metrics:
            lines.append("\n## Performance Rankings\n")
            by_return = sorted(
                wallet_metrics, key=lambda m: float(str(m["return_pct"])), reverse=True
            )
            lines.append("### By Return %\n")
            for i, m in enumerate(by_return, 1):
                lines.append(f"{i}. **{m['name']}** ({m['strategy']}): {m['return_pct']:+.4f}%")

            by_trades = sorted(
                wallet_metrics, key=lambda m: int(str(m["trade_count"])), reverse=True
            )
            lines.append("\n### By Trade Count\n")
            for i, m in enumerate(by_trades, 1):
                lines.append(f"{i}. **{m['name']}** ({m['strategy']}): {m['trade_count']} trades")

        return "\n".join(lines)

    def save(self, report: str, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(report, encoding="utf-8")
