
import sys
import os
import itertools
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor

# 프로젝트 루트 설정
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

from crypto_trader.config import BacktestConfig, StrategyConfig, RiskConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.risk.manager import RiskManager

def fetch_15m_data(symbol, count=2000, to_date="2025-01-10 00:00:00"):
    """15분봉 데이터를 대량으로 가져옵니다 (약 20일치)."""
    try:
        import pyupbit
        print(f"Fetching {count} candles (15m) for {symbol} up to {to_date}...")
        df = pyupbit.get_ohlcv(symbol, interval="minute15", count=count, to=to_date)
        if df is None: return []
        return [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df.iterrows()]
    except: return []

def run_single_test(params):
    """단일 조합에 대한 백테스트 실행 (병렬 처리용)"""
    vpin, obi, rsi_ob, adx_th, candles, backtest_cfg = params
    
    strat_cfg = StrategyConfig(
        max_holding_bars=48, # 15분봉이므로 약 12시간 보유
        rsi_overbought=rsi_ob,
        adx_threshold=adx_th
    )
    risk_cfg = RiskConfig(take_profit_pct=0.10, stop_loss_pct=0.03)
    
    strategy = TruthSeekerStrategy(config=strat_cfg, vpin_threshold=vpin, obi_threshold=obi)
    risk_manager = RiskManager(risk_cfg)
    engine = BacktestEngine(strategy, risk_manager, backtest_cfg, symbol="KRW-SOL")
    
    result = engine.run(candles)
    return {
        "vpin": vpin, "obi": obi, "rsi_ob": rsi_ob, "adx_th": adx_th,
        "return": result.total_return_pct,
        "win_rate": result.win_rate,
        "trades": len(result.trade_log),
        "mdd": result.max_drawdown
    }

def main():
    symbol = "KRW-SOL"
    candles = fetch_15m_data(symbol, count=1500) # 약 15일간의 15분봉
    if not candles: return

    backtest_cfg = BacktestConfig(initial_capital=5000000, fee_rate=0.0005, slippage_pct=0.0005)

    # 전수 조사 범위 설정 (Grid Search)
    vpin_grid = [0.35, 0.4, 0.45]
    obi_grid = [0.05, 0.1, 0.15]
    rsi_grid = [65.0, 70.0, 75.0]
    adx_grid = [15.0, 20.0, 25.0]
    
    param_combinations = list(itertools.product(vpin_grid, obi_grid, rsi_grid, adx_grid))
    tasks = [(v, o, r, a, candles, backtest_cfg) for v, o, r, a in param_combinations]
    
    print(f"Starting Grid Search with {len(tasks)} combinations on CPU...")
    
    results = []
    # CPU 코어 전체를 사용하여 병렬 처리
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(run_single_test, tasks))

    # 결과 분석
    # 1. 수익률 기준 정렬
    results.sort(key=lambda x: x["return"], reverse=True)
    
    print("\n" + "="*60)
    print(f"  TOP 5 PROFITABLE SETTINGS (15m SOLANA)")
    print("="*60)
    print(f"{'VPIN':>5} | {'OBI':>5} | {'RSI':>5} | {'ADX':>5} | {'Return':>8} | {'MDD':>6}")
    print("-"*60)
    for r in results[:5]:
        print(f"{r['vpin']:5.2f} | {r['obi']:5.2f} | {r['rsi_ob']:5.1f} | {r['adx_th']:5.1f} | {r['return']:7.2f}% | {r['mdd']:5.2f}%")
    print("="*60)

    best = results[0]
    if best['return'] > 0:
        print(f"\n🚀 FOUND WINNING SETTING! Use VPIN={best['vpin']}, OBI={best['obi']} for +{best['return']:.2f}% gain.")
    else:
        print("\n⚠️ No profitable settings found. Need to refine entry logic further.")

if __name__ == "__main__":
    main()
