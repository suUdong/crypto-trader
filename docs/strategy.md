# Strategy Design

## Market Scope

- Primary venue: Upbit KRW spot markets
- Initial symbols: configurable KRW pairs from Upbit
- Future venue: Binance spot through a compatible exchange adapter

## Signal Model

The live and backtest strategy uses three aligned components:

1. Momentum filter
   - Measures rolling percentage return over a configurable lookback window
   - Requires positive momentum for long entries
2. Bollinger Bands mean-reversion trigger
   - Uses a simple moving average with upper and lower bands
   - Looks for price recovery from the lower band for long entries
3. RSI confirmation
   - Confirms oversold-to-recovery behavior
   - Avoids entering when RSI already signals overbought conditions

## Entry Logic

A long signal is eligible only when:

- momentum exceeds the configured threshold
- closing price is at or below the lower Bollinger Band, or has just crossed back above it
- RSI is below the configured recovery ceiling and above the configured oversold floor after recovery

## Exit Logic

Positions are closed when any of the following occur:

- stop loss is hit
- take profit is hit
- momentum deteriorates below the exit threshold
- RSI exceeds the overbought threshold
- maximum holding period is exceeded

## Risk Model

- Position sizing uses a capped risk-per-trade percentage of current equity
- Stop loss and take profit are configured as percentages from entry
- Daily drawdown halts new entries after the loss cap is reached
- Maximum concurrent positions is configurable and defaults to one in paper mode

## Backtest Expectations

- Candlestick input supports OHLCV data at configurable intervals
- Costs include fees and slippage assumptions
- Reports include equity curve, win rate, profit factor, drawdown, and trade log
