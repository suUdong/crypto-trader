
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
START    = "2025-01-01"
END      = "2025-04-01"

def fetch_historical(symbol, start=START, end=END):
    try:
        print(f"Loading historical data for {symbol} ({start}~{end})...")
        df = load_historical(symbol, INTERVAL, start, end)
        if df is None or df.empty: return []
        return [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df.iterrows()]
    except: return []

def run_test():
    symbol = "KRW-ETH"
    candles = fetch_historical(symbol) # 2025 Q1
    if not candles: return

    # 공격적인 전략 설정 (거래 기회 확보)
    strat_cfg = StrategyConfig(max_holding_bars=24)
    risk_cfg = RiskConfig(take_profit_pct=0.08, stop_loss_pct=0.03)
    backtest_cfg = BacktestConfig(initial_capital=5000000, fee_rate=0.0005, slippage_pct=0.001)
    
    # 임계값을 현실적으로 낮춤 (VPIN 0.4, OBI 0.1)
    strategy = TruthSeekerStrategy(config=strat_cfg, vpin_threshold=0.4, obi_threshold=0.1)
    risk_manager = RiskManager(risk_cfg)
    engine = BacktestEngine(strategy, risk_manager, backtest_cfg, symbol=symbol)
    
    result = engine.run(candles)
    
    print("\n" + "="*45)
    print(f"  TRUTH-SEEKER HISTORICAL REPORT (2025 BULL)")
    print("="*45)
    print(f"Total Return:     {result.total_return_pct:>7.2f}%")
    print(f"Win Rate:         {result.win_rate:>7.2f}%")
    print(f"Max Drawdown:     {result.max_drawdown:>7.2f}%")
    print(f"Trade Count:      {len(result.trade_log):>7d}")
    print(f"Final Equity:     {result.final_equity:,.0f} KRW")
    print("="*45)

if __name__ == "__main__":
    run_test()
