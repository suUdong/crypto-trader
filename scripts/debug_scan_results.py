import torch
import pyupbit
import numpy as np
import pandas as pd
import time

def get_alpha_scan_results():
    try:
        print("Starting get_alpha_scan_results...")
        print("Fetching symbols...")
        symbols = pyupbit.get_tickers(fiat="KRW")
        target_symbols = symbols[:5] # 5개로 줄여서 즉각 확인
        data_list = []
        valid_symbols = []
        
        for s in target_symbols:
            print(f"Fetching {s}...")
            df = pyupbit.get_ohlcv(s, interval="minute15", count=200)
            if df is not None and len(df) >= 100:
                data_list.append(df[['open', 'high', 'low', 'close', 'volume']].values)
                valid_symbols.append(s)
            time.sleep(0.05)
            
        print(f"Fetched {len(valid_symbols)} symbols.")
        if not data_list: return "No data fetched."
        
        print("Creating CUDA tensor...")
        data = torch.tensor(np.array(data_list), device='cuda', dtype=torch.float32)
        print("CUDA tensor created.")
        
        close = data[:, :, 3]
        high = data[:, :, 1]
        low = data[:, :, 2]
        volatility = (high - low) / (close + 1e-9)
        
        print("Calculating alpha...")
        avg_vol = volatility.mean(dim=1)
        results = []
        for i, s in enumerate(valid_symbols):
            score = (volatility[i].mean() / avg_vol.mean()).item()
            results.append({"Symbol": s, "Alpha_Score": round(score, 4)})
            
        df_res = pd.DataFrame(results).sort_values(by="Alpha_Score", ascending=False)
        return df_res.head(10).to_string(index=False)
    except Exception as e:
        return f"Scan Error: {str(e)}"

if __name__ == "__main__":
    print(get_alpha_scan_results())
