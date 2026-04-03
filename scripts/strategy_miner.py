
import torch
import sys
import time
import pandas as pd
import numpy as np
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

def run_strategy_mining(symbol):
    """
    3080으로 특정 종목의 '급등 전조 현상'을 수학적으로 추출합니다.
    """
    import pyupbit
    print(f"Mining Alpha Patterns for {symbol}...")
    df = pyupbit.get_ohlcv(symbol, interval="minute60", count=500)
    if df is None: return
    
    # 1. 3080으로 모든 시점의 '수급 에너지' 계산
    closes = torch.tensor(df['close'].values, device='cuda', dtype=torch.float32)
    vols = torch.tensor(df['volume'].values, device='cuda', dtype=torch.float32)
    
    # CVD (누적 매수세) 계산
    deltas = torch.where(closes[1:] >= closes[:-1], vols[1:], -vols[1:])
    cvd = torch.cumsum(deltas, dim=0)
    
    # 가격 변동성 (Volatility)
    price_std = torch.std(closes[-24:]) / closes[-1]
    
    # 2. '폭발 전' 특이점 포착 (Discovery Logic)
    # 최근 24시간 동안 가격은 죽어있는데(std 저하), CVD는 미친듯이 올랐는가?
    cvd_slope = (cvd[-1] - cvd[-24]) / vols[-24:].mean()
    
    print(f"[{symbol}] Price Volatility: {price_std:.4f} | CVD Buy Pressure: {cvd_slope:.2f}")
    
    if price_std < 0.01 and cvd_slope > 10:
        print(f"🔥 ALPHA FOUND: Strong Accumulation detected in {symbol}!")
        return True
    return False

def main():
    targets = ["KRW-DOOD", "KRW-TREE", "KRW-ARKM"]
    for t in targets:
        run_strategy_mining(t)
        time.sleep(0.1)

if __name__ == "__main__":
    main()
