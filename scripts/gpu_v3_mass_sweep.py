
import sys
import torch
import itertools
import time
import pandas as pd
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

from crypto_trader.config import StrategyConfig, BacktestConfig, RiskConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.truth_seeker_v3 import TruthSeekerV3Strategy

def run_v3_backtest(params):
    symbol, vpin_th, hurst_th, tp, sl, candles, btc_candles = params
    
    equity = 5000000.0
    cash = equity
    pos_qty = 0.0
    pos_price = 0.0
    trades = 0
    
    strat = TruthSeekerV3Strategy(config=StrategyConfig(), vpin_threshold=vpin_th, hurst_threshold=hurst_th)
    
    for i in range(60, len(candles)):
        current = candles[i]
        price = current.close
        
        if pos_qty > 0:
            pnl = (price - pos_price) / pos_price
            # v3 Exit logic (RSI included in evaluate inside strategy)
            sig = strat.evaluate(candles[i-60 : i+1], btc_candles=btc_candles[i-60 : i+1] if btc_candles else None)
            if pnl >= tp or pnl <= -sl or sig.action == SignalAction.SELL:
                cash += pos_qty * price * (1 - 0.001)
                pos_qty = 0.0
                trades += 1
        else:
            sig = strat.evaluate(candles[i-60 : i+1], btc_candles=btc_candles[i-60 : i+1] if btc_candles else None)
            if sig.action == SignalAction.BUY:
                pos_qty = (cash * 0.99) / price
                pos_price = price
                cash -= pos_qty * price * (1 + 0.001)

    final_equity = cash + (pos_qty * candles[-1].close if pos_qty > 0 else 0)
    return {"vpin": vpin_th, "hurst": hurst_th, "tp": tp, "sl": sl, "return": (final_equity - 5000000)/5000000 * 100, "trades": trades}

def main():
    import pyupbit
    symbol = "KRW-SOL"
    print(f"Loading 6 months data for {symbol} and BTC...")
    df_sol = pyupbit.get_ohlcv(symbol, interval="minute15", count=2000)
    df_btc = pyupbit.get_ohlcv("KRW-BTC", interval="minute15", count=2000)
    
    candles = [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df_sol.iterrows()]
    btc_candles = [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df_btc.iterrows()]

    # V3 Grid Search
    tasks = []
    for v in [0.4, 0.45, 0.5]:
        for h in [0.5, 0.55, 0.6]:
            for tp in [0.10, 0.15]:
                for sl in [0.03, 0.04]:
                    tasks.append((symbol, v, h, tp, sl, candles, btc_candles))

    print(f"Starting V3 Quant Sweep with {len(tasks)} combinations...")
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(run_v3_backtest, tasks))
    
    results.sort(key=lambda x: x["return"], reverse=True)
    print("\n" + "="*60)
    print(f"  TRUTH-SEEKER V3 (QUANT MASTER) TOP RESULTS")
    print("="*60)
    for i, r in enumerate(results[:5]):
        print(f"#{i+1} | VPIN:{r['vpin']:.2f} Hurst:{r['hurst']:.2f} TP:{r['tp']:.2f} | ROI:{r['return']:7.2f}% | Trd:{r['trades']}")
    print("="*60)

if __name__ == "__main__":
    main()
