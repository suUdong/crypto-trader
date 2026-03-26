# Walk-Forward Validation Results

- Total days: `90`
- Train window: `60` days
- Test window: `15` days

| Strategy | Folds | Avg Train Sharpe | Avg Test Sharpe | Avg Test Return | Avg Test MDD | Total Test Trades |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| kimchi_premium | 2 | 0.00 | 0.00 | +0.00% | 0.00% | 0 |
| momentum | 2 | 0.36 | 4.22 | +4.23% | 2.28% | 111 |

## Validation Decision

- Top candidate strategy: `momentum`
- Selection basis: highest aggregate out-of-sample Sharpe (`4.22`)
- Gate status: `PASS`
- Gate thresholds: `avg_test_sharpe > 0.00`, `avg_test_return_pct > +0.00%`, `total_test_trades >= 20`
- Latest deployment fold: `#2`
- Latest fold test return: `+0.27%`
- Latest fold tuned params: `{'momentum_lookback': 15, 'momentum_entry_threshold': 0.008, 'rsi_period': 18, 'rsi_overbought': 65.0, 'max_holding_bars': 36}`
- Latest fold tuned risk: `{'stop_loss_pct': 0.03, 'take_profit_pct': 0.08, 'risk_per_trade_pct': 0.01, 'trailing_stop_pct': 0.0, 'atr_stop_multiplier': 0.0}`

## Fold Detail

### kimchi_premium
- Fold #1: train_sharpe=0.00, test_sharpe=0.00, test_return=+0.00%, test_mdd=0.00%, trades=0
- Fold #2: train_sharpe=0.00, test_sharpe=0.00, test_return=+0.00%, test_mdd=0.00%, trades=0

### momentum
- Fold #1: train_sharpe=0.23, test_sharpe=7.52, test_return=+8.19%, test_mdd=2.96%, trades=61
- Fold #2: train_sharpe=0.50, test_sharpe=0.93, test_return=+0.27%, test_mdd=1.60%, trades=50
