# Walk-Forward Validation Results

- Total days: `90`
- Train window: `60` days
- Test window: `15` days

| Strategy | Folds | Avg Train Sharpe | Avg Test Sharpe | Avg Test Return | Avg Test MDD | Total Test Trades |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| momentum | 2 | 1.53 | 1.89 | +0.99% | 2.44% | 103 |

## Selected Strategy

- Strategy: `momentum`
- Selection basis: highest aggregate out-of-sample Sharpe (`1.89`)
- Latest deployment fold: `#2`
- Latest fold test return: `+0.65%`
- Latest fold tuned params: `{'momentum_lookback': 15, 'momentum_entry_threshold': 0.008, 'rsi_period': 18, 'rsi_overbought': 65.0, 'max_holding_bars': 36}`
- Latest fold tuned risk: `{'stop_loss_pct': 0.03, 'take_profit_pct': 0.1, 'risk_per_trade_pct': 0.01, 'trailing_stop_pct': 0.0, 'atr_stop_multiplier': 0.0}`

## Fold Detail

### momentum
- Fold #1: train_sharpe=2.22, test_sharpe=1.86, test_return=+1.33%, test_mdd=3.22%, trades=57
- Fold #2: train_sharpe=0.84, test_sharpe=1.91, test_return=+0.65%, test_mdd=1.66%, trades=46
