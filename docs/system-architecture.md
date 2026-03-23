# System Architecture

## High-Level Pipeline

1. Market data ingestion
2. Feature calculation
3. Signal generation
4. Risk evaluation
5. Paper order execution
6. Notification and audit logging

## Core Modules

- `config`: environment and strategy parameter loading
- `data`: exchange clients and market data services
- `strategy`: indicator and signal logic
- `backtest`: historical simulation engine
- `execution`: paper broker and order routing
- `notifications`: Telegram delivery
- `monitoring`: logging, metrics, and health checks

## Exchange Boundary

The first implementation uses an Upbit adapter for KRW spot markets. The exchange boundary is abstracted so Binance can be added later without changing strategy, risk, or backtest logic.

## Operational Requirements

- Components must degrade safely on transient API failures
- Order execution starts in paper-trading mode only
- All orders, signals, and exceptions must be logged with timestamps
- Configuration must come from environment variables and TOML files, not hardcoded values
