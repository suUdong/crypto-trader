
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트 설정
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

from crypto_trader.config import BacktestConfig, StrategyConfig, RiskConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.risk.manager import RiskManager

def fetch_historical(symbol, count=1000, to_date="2025-01-15 00:00:00"):
    try:
        import pyupbit
        print(f"Fetching {count} candles for {symbol} up to {to_date}...")
        df = pyupbit.get_ohlcv(symbol, interval="minute60", count=count, to=to_date)
        if df is None: return []
        return [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df.iterrows()]
    except: return []

def run_sol_test():
    symbol = "KRW-SOL"
    candles = fetch_historical(symbol, count=1000) # 불장 한가운데
    if not candles: return

    # 널널한 익절/손절 (추세를 끝까지 먹기 위해)
    strat_cfg = StrategyConfig(max_holding_bars=48)
    risk_cfg = RiskConfig(take_profit_pct=0.15, stop_loss_pct=0.04)
    backtest_cfg = BacktestConfig(initial_capital=5000000, fee_rate=0.0005, slippage_pct=0.001)
    
    # Truth-Seeker 전략 (공격적 설정)
    strategy = TruthSeekerStrategy(config=strat_cfg, vpin_threshold=0.35, obi_threshold=0.05)
    risk_manager = RiskManager(risk_cfg)
    engine = BacktestEngine(strategy, risk_manager, backtest_cfg, symbol=symbol)
    
    result = engine.run(candles)
    
    print("\n" + "="*45)
    print(f"  SOLANA BULL MARKET TEST (2024-2025)")
    print("="*45)
    print(f"Total Return:     {result.total_return_pct:>7.2f}%")
    print(f"Win Rate:         {result.win_rate:>7.2f}%")
    print(f"Max Drawdown:     {result.max_drawdown:>7.2f}%")
    print(f"Trade Count:      {len(result.trade_log):>7d}")
    print(f"Final Equity:     {result.final_equity:,.0f} KRW")
    print("="*45)

if __name__ == "__main__":
    run_sol_test()
