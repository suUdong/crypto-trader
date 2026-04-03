
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트 설정
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from crypto_trader.config import BacktestConfig, StrategyConfig, RiskConfig, TradingConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.risk.manager import RiskManager
from scripts.grid_search import fetch_candles # (symbol, days) 인자 확인됨

def run_real_data_test():
    # 1. 실제 데이터 로드 (최근 7일분, KRW-ETH)
    print("Fetching real market data for KRW-ETH (7 days)...")
    try:
        candles = fetch_candles("KRW-ETH", 7)
    except Exception as e:
        print(f"Error fetching candles: {e}")
        return
    
    if not candles:
        print("No candles fetched.")
        return

    # 2. 설정 (수익 극대화 타겟)
    strat_cfg = StrategyConfig(max_holding_bars=24, rsi_period=14)
    risk_cfg = RiskConfig(take_profit_pct=0.06, stop_loss_pct=0.02)
    backtest_cfg = BacktestConfig(initial_capital=5000000, fee_rate=0.0005, slippage_pct=0.0005)
    
    # 3. Truth-Seeker 전략 (더 많은 기회를 보기 위해 대폭 완화)
    strategy = TruthSeekerStrategy(
        config=strat_cfg,
        vpin_threshold=0.4, # 대폭 완화
        obi_threshold=0.15,  # 대폭 완화
        anti_spoof_buffer=0.25
    )
    risk_manager = RiskManager(risk_cfg)
    engine = BacktestEngine(strategy, risk_manager, backtest_cfg, symbol="KRW-ETH")
    
    # 4. 실행
    result = engine.run(candles)
    
    # 5. 결과 출력
    print("\n" + "="*45)
    print("  TRUTH-SEEKER REAL DATA REPORT (7 DAYS)")
    print("="*45)
    print(f"Total Return:     {result.total_return_pct:>7.2f}%")
    print(f"Win Rate:         {result.win_rate:>7.2f}%")
    print(f"Max Drawdown:     {result.max_drawdown:>7.2f}%")
    print(f"Trade Count:      {len(result.trade_log):>7d}")
    print(f"Final Equity:     {result.final_equity:,.0f} KRW")
    print("="*45)

if __name__ == "__main__":
    run_real_data_test()
