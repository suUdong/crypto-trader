
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
from crypto_trader.strategy.truth_seeker_v2 import TruthSeekerV2Strategy
from crypto_trader.strategy.indicators import rolling_vwap, rsi, average_directional_index

def run_ultra_backtest(params):
    symbol, interval, vpin_th, obi_th, tp, sl, candles = params
    
    # 초정밀 백테스트 시뮬레이션
    equity = 5000000.0
    cash = equity
    pos_qty = 0.0
    pos_price = 0.0
    trades = 0
    
    # 전략/지표 초기화
    strat = TruthSeekerV2Strategy(config=StrategyConfig(), vpin_threshold=vpin_th, obi_threshold=obi_th)
    
    for i in range(50, len(candles)):
        current = candles[i]
        price = current.close
        
        if pos_qty > 0:
            pnl = (price - pos_price) / pos_price
            if pnl >= tp or pnl <= -sl:
                cash += pos_qty * price * (1 - 0.001)
                pos_qty = 0.0
                trades += 1
        else:
            # 보강된 지표 로직 (VWAP + VPIN + OBI)
            sig = strat.evaluate(candles[i-50 : i+1])
            if sig.action == SignalAction.BUY:
                pos_qty = (cash * 0.99) / price
                pos_price = price
                cash -= pos_qty * price * (1 + 0.001)

    final_equity = cash + (pos_qty * candles[-1].close if pos_qty > 0 else 0)
    return {"symbol": symbol, "vpin": vpin_th, "obi": obi_th, "tp": tp, "sl": sl, "return": (final_equity - 5000000)/50000, "trades": trades}

def main():
    symbols = ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
    intervals = ["minute15"]
    
    import pyupbit
    for symbol in symbols:
        print(f"\n🚀 [Cycle START] Processing {symbol} with Ultra-Indicators...")
        df = pyupbit.get_ohlcv(symbol, interval="minute15", count=3000)
        if df is None: continue
        candles = [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df.iterrows()]

        # 3080급 전수 조사 그리드
        tasks = []
        for v in [0.4, 0.45, 0.5]:
            for o in [0.05, 0.1, 0.15]:
                for tp in [0.08, 0.12, 0.15]:
                    for sl in [0.02, 0.03]:
                        tasks.append((symbol, "15m", v, o, tp, sl, candles))

        print(f"Testing {len(tasks)} combinations for {symbol}...")
        with ProcessPoolExecutor() as executor:
            results = list(executor.map(run_ultra_backtest, tasks))
        
        # 상위 3개 저장
        results.sort(key=lambda x: x["return"], reverse=True)
        report_path = f"crypto-trader/artifacts/ralph_data/{symbol}_top_results.json"
        pd.DataFrame(results[:5]).to_json(report_path)
        print(f"✅ {symbol} Complete. Best Return: {results[0]['return']:.2f}%")

if __name__ == "__main__":
    main()
