
import sys
import torch
import itertools
import pandas as pd
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

from crypto_trader.config import StrategyConfig, BacktestConfig, RiskConfig
from crypto_trader.models import Candle, SignalAction
from crypto_trader.strategy.experimental.accumulation_hunter import AccumulationBreakoutStrategy
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.risk.manager import RiskManager

def run_lab_backtest(params):
    symbol, v_ceil, cvd_th, tp, sl, candles = params
    
    equity = 5000000.0
    cash = equity
    pos_qty = 0.0
    pos_price = 0.0
    trades = 0
    
    strat = AccumulationBreakoutStrategy(
        config=StrategyConfig(), 
        volatility_ceiling=v_ceil, 
        cvd_slope_threshold=cvd_th
    )
    
    for i in range(48, len(candles)):
        current = candles[i]
        price = current.close
        
        if pos_qty > 0:
            pnl = (price - pos_price) / pos_price
            if pnl >= tp or pnl <= -sl:
                cash += pos_qty * price * (1 - 0.001)
                pos_qty = 0.0
                trades += 1
        else:
            sig = strat.evaluate(candles[i-48 : i+1])
            if sig.action == SignalAction.BUY:
                pos_qty = (cash * 0.99) / price
                pos_price = price
                cash -= pos_qty * price * (1 + 0.001)

    final_equity = cash + (pos_qty * candles[-1].close if pos_qty > 0 else 0)
    return {"v_ceil": v_ceil, "cvd_th": cvd_th, "tp": tp, "sl": sl, "return": (final_equity - 5000000)/5000000 * 100, "trades": trades}

def main():
    import pyupbit
    targets = ["KRW-ARKM", "KRW-SOL", "KRW-DOOD"]
    
    for symbol in targets:
        print(f"\n🧪 [Lab Scan v2] Testing dynamic patterns on {symbol} (15m)...")
        # 15분봉으로 더 정밀하게 스캔
        df = pyupbit.get_ohlcv(symbol, interval="minute15", count=2000)
        if df is None: continue
        candles = [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df.iterrows()]

        tasks = []
        for vc in [0.02, 0.03, 0.05]: # 변동성 한도 완화
            for cvd in [3.0, 7.0, 12.0]: # CVD 문턱 조정
                for tp in [0.05, 0.10]: # 현실적인 익절선
                    tasks.append((symbol, vc, cvd, tp, 0.02, candles))

        with ProcessPoolExecutor() as executor:
            results = list(executor.map(run_lab_backtest, tasks))
        
        results.sort(key=lambda x: x["return"], reverse=True)
        best = results[0]
        print(f"✅ {symbol} Result: ROI {best['return']:.2f}% | VolCeil: {best['v_ceil']} | CVD_Th: {best['cvd_th']} | Trades: {best['trades']}")

if __name__ == "__main__":
    main()
