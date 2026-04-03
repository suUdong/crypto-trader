
import torch
import sys
import time
import pandas as pd
import numpy as np
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

def fetch_market_data(symbol, days=30):
    try:
        import pyupbit
        df = pyupbit.get_ohlcv(symbol, interval="minute60", count=days*24)
        if df is None or len(df) < 50: return None
        return df
    except: return None

def analyze_alpha_pattern(df, btc_df):
    """
    데이터 길이를 동적으로 맞추어 상대 강도 및 수급 분석
    """
    common_len = min(len(df), len(btc_df))
    df = df.iloc[-common_len:]
    btc_sub = btc_df.iloc[-common_len:]

    closes = torch.tensor(df['close'].values, device='cuda', dtype=torch.float32)
    btc_closes = torch.tensor(btc_sub['close'].values, device='cuda', dtype=torch.float32)
    
    # 1. 상대 강도 (Relative Strength)
    rs = (closes / closes[0]) / (btc_closes / btc_closes[0])
    current_rs = rs[-1].item()
    
    # 2. 수급 집중도 (VPIN Proxy)
    price_range = (df['high'] - df['low']).values
    vpin_proxy = np.abs(df['close'] - df['open']).values / (price_range + 1e-9)
    accumulation_score = vpin_proxy[-24:].mean() / (vpin_proxy[:-24].mean() + 1e-9)
    
    # 3. 누적 거래량 델타 (CVD Proxy)
    cvd = (df['volume'] * np.where(df['close'] >= df['open'], 1, -1)).cumsum()
    cvd_slope = (cvd.iloc[-1] - cvd.iloc[-24]) / (df['volume'].mean() + 1e-9)

    return {
        "rs_score": current_rs,
        "acc_score": accumulation_score,
        "cvd_slope": cvd_slope,
        "total_alpha": (current_rs * 0.4) + (accumulation_score * 0.3) + (cvd_slope * 0.3)
    }

def main():
    import pyupbit
    symbols = pyupbit.get_tickers(fiat="KRW")
    btc_df = pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=30*24)
    
    print("\n" + "="*80)
    print("  🔍 RTX 3080 ALPHA HUNTER: SEARCHING FOR THE NEXT SOLANA (2026)")
    print("="*80)
    
    alpha_results = []
    for symbol in symbols[:60]: # 스캔 범위를 60개로 확대
        df = fetch_market_data(symbol)
        if df is None: continue
        
        metrics = analyze_alpha_pattern(df, btc_df)
        alpha_results.append({
            "Symbol": symbol,
            "Alpha_Score": metrics['total_alpha'],
            "RS": metrics['rs_score'],
            "Acc": metrics['acc_score'],
            "CVD_Slope": metrics['cvd_slope']
        })
        print(f"Scanning {symbol}... Alpha: {metrics['total_alpha']:.2f}", end="\r")
        time.sleep(0.05)

    df_final = pd.DataFrame(alpha_results).sort_values(by="Alpha_Score", ascending=False)
    
    print("\n" + "="*80)
    print("  🏆 TOP 10 CANDIDATES FOR 2026 BULL RUN (By 3080 Analysis)")
    print("="*80)
    # 가독성을 위해 필드 정리
    print(df_final.head(10).to_string(index=False))
    print("="*80)
    print("\n💡 Alpha Score > 1.1: Outperforming BTC with strong buying intent.")

if __name__ == "__main__":
    main()
