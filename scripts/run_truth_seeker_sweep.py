
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트 설정
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root / "scripts"))
from historical_loader import load_historical

from crypto_trader.config import BacktestConfig, StrategyConfig, RiskConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.risk.manager import RiskManager

INTERVAL = "60m"
START    = "2024-01-01"
END      = "2025-06-01"

def fetch_historical(symbol, start=START, end=END):
    try:
        print(f"Loading historical data for {symbol} ({start}~{end})...")
        df = load_historical(symbol, INTERVAL, start, end)
        if df is None or df.empty: return []
        return [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df.iterrows()]
    except: return []

def run_sweep():
    symbol = "KRW-ETH"
    candles = fetch_historical(symbol) # 2024~2025 전체
    if not candles: return

    results = []
    
    # 파라미터 스윕 범위
    vpin_range = [0.35, 0.4, 0.45]
    obi_range = [0.05, 0.1, 0.15]
    
    backtest_cfg = BacktestConfig(initial_capital=5000000, fee_rate=0.0005, slippage_pct=0.001)
    risk_cfg = RiskConfig(take_profit_pct=0.08, stop_loss_pct=0.03)
    strat_cfg = StrategyConfig(max_holding_bars=24)

    print("\n" + "-"*60)
    print(f"{'VPIN':>6} | {'OBI':>6} | {'Return':>10} | {'Trades':>8} | {'WinRate':>8}")
    print("-"*60)

    for vpin in vpin_range:
        for obi in obi_range:
            strategy = TruthSeekerStrategy(config=strat_cfg, vpin_threshold=vpin, obi_threshold=obi)
            risk_manager = RiskManager(risk_cfg)
            engine = BacktestEngine(strategy, risk_manager, backtest_cfg, symbol=symbol)
            
            res = engine.run(candles)
            results.append({
                "vpin": vpin,
                "obi": obi,
                "return": res.total_return_pct,
                "trades": len(res.trade_log),
                "win_rate": res.win_rate
            })
            print(f"{vpin:6.2f} | {obi:6.2f} | {res.total_return_pct:9.2f}% | {len(res.trade_log):8d} | {res.win_rate:7.1f}%")

    # 최적 결과 정렬
    best = max(results, key=lambda x: x["return"])
    print("-"*60)
    print(f"BEST SETTING: VPIN={best['vpin']}, OBI={best['obi']} => Return: {best['return']:.2f}%")
    print("-"*60)

if __name__ == "__main__":
    run_sweep()
