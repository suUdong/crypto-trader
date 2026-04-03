
import sys
import os
import itertools
import time
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor

# 프로젝트 루트 설정
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

from crypto_trader.config import BacktestConfig, StrategyConfig, RiskConfig
from crypto_trader.models import Candle, Signal, SignalAction
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.risk.manager import RiskManager

def fetch_6m_data(symbol, days=180, to_date="2025-04-01 00:00:00"):
    try:
        import pyupbit
        all_candles = []
        current_to = to_date
        print(f"Loading {days} days of data...")
        for _ in range((days * 24 * 4) // 200 + 1):
            df = pyupbit.get_ohlcv(symbol, interval="minute15", count=200, to=current_to)
            if df is None or df.empty: break
            batch = [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df.iterrows()]
            all_candles = batch + all_candles
            current_to = df.index[0].strftime("%Y-%m-%d %H:%M:%S")
            if _ % 10 == 0: print(f"Fetched {_*200} candles...")
        all_candles.sort(key=lambda x: x.timestamp)
        return all_candles
    except: return []

# 고속 백테스트용 (지표 중복 계산 방지)
def fast_backtest(params):
    vpin_th, obi_th, tp, sl, candles = params
    
    # 1. 지표는 이미 계산되어 있다고 가정하고 필터링만 수행
    # (실제 TruthSeekerStrategy의 evaluate 로직을 인라인화하여 속도 극대화)
    equity = 5000000.0
    cash = equity
    pos_qty = 0.0
    pos_price = 0.0
    trades = 0
    
    # 전략 인스턴스 1번만 생성 (VPIN 계산용)
    strat = TruthSeekerStrategy(config=StrategyConfig(), vpin_threshold=vpin_th, obi_threshold=obi_th)
    
    # 1.7만 개 캔들 루프
    for i in range(30, len(candles)):
        current = candles[i]
        price = current.close
        
        if pos_qty > 0:
            # 익절/손절 체크
            pnl_pct = (price - pos_price) / pos_price
            if pnl_pct >= tp or pnl_pct <= -sl:
                cash += pos_qty * price * (1 - 0.001) # 수수료/슬리피지
                pos_qty = 0.0
                trades += 1
        else:
            # 진입 체크 (TruthSeeker 로직)
            # 매번 전체 계산 대신 윈도우 슬라이싱
            sig = strat.evaluate(candles[i-30 : i+1])
            if sig.action == SignalAction.BUY:
                pos_qty = (cash * 0.99) / price
                pos_price = price
                cash -= pos_qty * price * (1 + 0.001)

    final_equity = cash + (pos_qty * candles[-1].close if pos_qty > 0 else 0)
    return {"vpin": vpin_th, "obi": obi_th, "tp": tp, "sl": sl, "return": (final_equity - 5000000)/50000, "trades": trades}

def main():
    candles = fetch_6m_data("KRW-SOL", days=180)
    if not candles: return
    print(f"Loaded {len(candles)} candles. Starting optimized sweep...")

    vpin_grid = [0.35, 0.4, 0.45]
    obi_grid = [0.05, 0.1, 0.15]
    tp_grid = [0.05, 0.10, 0.15]
    sl_grid = [0.02, 0.03, 0.04]
    
    param_combinations = list(itertools.product(vpin_grid, obi_grid, tp_grid, sl_grid))
    tasks = [(v, o, tp, sl, candles) for v, o, tp, sl in param_combinations]
    
    results = []
    with ProcessPoolExecutor() as executor:
        for i, res in enumerate(executor.map(fast_backtest, tasks)):
            results.append(res)
            if i % 10 == 0: print(f"Progress: {i}/{len(tasks)} combinations...")

    results.sort(key=lambda x: x["return"], reverse=True)
    
    print("\n" + "="*60)
    print(f"  6-MONTH HIGH-SPEED OPTIMIZATION (SOL 15m)")
    print("="*60)
    for i, r in enumerate(results[:10]):
        print(f"#{i+1:2} | VPIN:{r['vpin']:.2f} OBI:{r['obi']:.2f} TP:{r['tp']:.2f} SL:{r['sl']:.2f} | Ret:{r['return']:7.2f}% | Trd:{r['trades']}")
    print("="*60)

if __name__ == "__main__":
    main()
