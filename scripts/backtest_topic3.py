import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'src'))

import asyncio
from crypto_trader.config import load_config
from crypto_trader.models import Candle
from crypto_trader.strategy.hmm_vol_breakout import HMMVolBreakoutStrategy
import pyupbit
import pandas as pd

async def run_sim():
    print("[*] Loading SOL/KRW data for backtest...")
    df = pyupbit.get_ohlcv("KRW-SOL", interval="minute5", count=200)
    if df is None:
        print("[!] Failed to fetch data")
        return
        
    candles = [
        Candle(
            timestamp=index.to_pydatetime(),
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            volume=row['volume']
        )
        for index, row in df.iterrows()
    ]
    
    config = load_config()
    strategy = HMMVolBreakoutStrategy(config.strategy, config.regime)
    
    print("[*] Running simulation...")
    signals_count = 0
    for i in range(100, len(candles)):
        signal = strategy.evaluate(candles[:i+1], symbol="KRW-SOL")
        if signal.action.name == 'BUY':
            print(f"[+] BUY Signal at {candles[i].timestamp}: {signal.reason} (Conf: {signal.confidence:.2f})")
            signals_count += 1
            
    print(f"[*] Simulation finished. Total BUY signals: {signals_count}")

if __name__ == "__main__":
    asyncio.run(run_sim())
