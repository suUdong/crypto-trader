import torch
import time
import pyupbit
import numpy as np
import pandas as pd
import sys
from pathlib import Path

def test_scan():
    try:
        print("Fetching tickers...")
        symbols = pyupbit.get_tickers(fiat="KRW")
        target_symbols = symbols[:10] # 10개로 테스트
        data_list = []
        valid_symbols = []
        
        for s in target_symbols:
            print(f"Fetching {s}...")
            df = pyupbit.get_ohlcv(s, interval="minute15", count=100)
            if df is not None:
                data_list.append(df[['open', 'high', 'low', 'close', 'volume']].values)
                valid_symbols.append(s)
            time.sleep(0.1)
            
        print(f"Data fetched for {len(valid_symbols)} symbols.")
        data = torch.tensor(np.array(data_list), device='cuda', dtype=torch.float32)
        print("Tensor created on CUDA.")
        
        close = data[:, :, 3]
        high = data[:, :, 1]
        low = data[:, :, 2]
        volatility = (high - low) / (close + 1e-9)
        
        print("Starting matmul test...")
        for i in range(10):
            _ = torch.matmul(volatility, volatility.transpose(1, 0))
        print("Matmul test completed.")
        
        avg_vol = volatility.mean(dim=1)
        results = []
        for i, s in enumerate(valid_symbols):
            score = (volatility[i].mean() / avg_vol.mean()).item()
            results.append({"Symbol": s, "Alpha_Score": round(score, 4)})
            
        df_res = pd.DataFrame(results).sort_values(by="Alpha_Score", ascending=False)
        print(df_res.head(5).to_string(index=False))
        
    except Exception as e:
        print(f"FAILED: {str(e)}")

if __name__ == "__main__":
    test_scan()
