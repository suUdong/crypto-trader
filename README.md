# Crypto Trader

Automated crypto trading system with Upbit-first market support, composite signal generation, backtesting, and a paper-trading execution pipeline.

## Delivery Stages

1. Strategy and system design contracts
2. Core Python implementation with tests
3. Production hardening, deployment, and CI/CD

## Primary Scope

- Exchange priority: Upbit KRW markets
- Expansion path: Binance via exchange adapter boundary
- Strategy: momentum + Bollinger Bands + RSI
- Risk controls: position sizing, stop loss, take profit, daily loss cap
- Runtime flow: market data -> signals -> risk -> execution -> notifications

## Local Commands

- `python3 -m unittest discover -s tests -t . -v`
- `ruff check .`
- `mypy src`
- `python3 -m crypto_trader.cli backtest --config config/example.toml`
- `python3 -m crypto_trader.cli run-loop --config config/example.toml`

Current execution mode is paper trading only. `CT_PAPER_TRADING=false` is rejected until a real order adapter and live-trading safeguards exist.
