
import sys
import torch
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root / "scripts"))
from historical_loader import load_historical

INTERVAL = "15m"
START    = "2024-01-01"
END      = "2026-12-31"

from crypto_trader.config import StrategyConfig, BacktestConfig, RiskConfig
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.strategy.truth_seeker_v2 import TruthSeekerV2Strategy
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.risk.manager import RiskManager

def run_comparison():
    symbol = "KRW-SOL"
    print(f"Loading historical data for {symbol} ({START}~{END})...")
    df = load_historical(symbol, INTERVAL, START, END)
    if df is None or df.empty: return
    
    from crypto_trader.models import Candle
    candles = [Candle(timestamp=t.to_pydatetime(), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']), volume=float(r['volume'])) for t, r in df.iterrows()]

    backtest_cfg = BacktestConfig(initial_capital=5000000, fee_rate=0.0005, slippage_pct=0.0005)
    strat_cfg = StrategyConfig(max_holding_bars=48)
    risk_manager = RiskManager(RiskConfig(take_profit_pct=0.12, stop_loss_pct=0.03))

    # Test v1
    s1 = TruthSeekerStrategy(config=strat_cfg, vpin_threshold=0.42, obi_threshold=0.12)
    e1 = BacktestEngine(s1, risk_manager, backtest_cfg, symbol=symbol)
    r1 = e1.run(candles)

    # Test v2
    s2 = TruthSeekerV2Strategy(config=strat_cfg, vpin_threshold=0.42, obi_threshold=0.12, toxic_vpin_threshold=0.80)
    e2 = BacktestEngine(s2, risk_manager, backtest_cfg, symbol=symbol)
    r2 = e2.run(candles)

    print("\n" + "="*50)
    print("  RALPH LOOP CYCLE 2: V1 vs V2 COMPARISON")
    print("="*50)
    print(f"Strategy | Return (%) | Trades | Win Rate")
    print("-" * 50)
    print(f"v1 (Orig) | {r1.total_return_pct:9.2f}% | {len(r1.trade_log):6d} | {r1.win_rate:7.1f}%")
    print(f"v2 (Ice)  | {r2.total_return_pct:9.2f}% | {len(r2.trade_log):6d} | {r2.win_rate:7.1f}%")
    print("="*50)
    
    improvement = r2.total_return_pct - r1.total_return_pct
    print(f"📈 ROI Improvement: {improvement:+.2f}%")

if __name__ == "__main__":
    run_comparison()
