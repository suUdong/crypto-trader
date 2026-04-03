
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

def load_simulation_candles():
    """수익성 검증을 위한 500시간(약 21일) 분량의 시뮬레이션 데이터 생성"""
    import math
    import random
    candles = []
    base_price = 3000000
    random.seed(42) # 결과 재현성을 위해 시드 고정
    
    for i in range(500):
        # 1. 추세 형성 (사인파 + 점진적 상승)
        trend = 0.05 * math.sin(i / 20.0) + (i / 1000.0)
        # 2. 노이즈 및 변동성 추가
        noise = random.uniform(-0.01, 0.01)
        price = base_price * (1 + trend + noise)
        
        candles.append(Candle(
            timestamp=datetime.now() + timedelta(hours=i),
            open=price * (1 - random.uniform(0, 0.005)),
            high=price * (1 + random.uniform(0, 0.01)),
            low=price * (1 - random.uniform(0, 0.01)),
            close=price,
            volume=1000 + random.randint(0, 1000)
        ))
    return candles

def run_test():
    strat_cfg = StrategyConfig(
        max_holding_bars=24,
        rsi_period=14,
        rsi_overbought=70.0
    )
    risk_cfg = RiskConfig(
        take_profit_pct=0.08, 
        stop_loss_pct=0.03,
        risk_per_trade_pct=0.02 # 공격적 자산 배분
    )
    backtest_cfg = BacktestConfig(
        initial_capital=5000000, 
        fee_rate=0.0005, 
        slippage_pct=0.001
    )
    
    # 1. Truth-Seeker 전략 설정 (수익성 확인을 위해 문턱을 낮춤)
    strategy = TruthSeekerStrategy(
        config=strat_cfg,
        vpin_threshold=0.45, 
        obi_threshold=0.25
    )
    risk_manager = RiskManager(risk_cfg)
    engine = BacktestEngine(strategy, risk_manager, backtest_cfg, symbol="KRW-ETH")
    
    # 2. 데이터 로드 및 실행
    candles = load_simulation_candles()
    result = engine.run(candles)
    
    # 3. 결과 출력 (정확한 필드명 사용)
    print("\n" + "="*45)
    print("  TRUTH-SEEKER PROFITABILITY REPORT (SIM)")
    print("="*45)
    print(f"Initial Capital:  {result.initial_capital:,.0f} KRW")
    print(f"Final Equity:     {result.final_equity:,.0f} KRW")
    print(f"Total Return:     {result.total_return_pct:>7.2f}%")
    print(f"Win Rate:         {result.win_rate:>7.2f}%")
    print(f"Max Drawdown:     {result.max_drawdown:>7.2f}%")
    print(f"Profit Factor:    {result.profit_factor:>7.2f}")
    print(f"Trade Count:      {len(result.trade_log):>7d}")
    print(f"Recovery Factor:  {result.recovery_factor:>7.2f}")
    print("="*45)
    
    if result.total_return_pct > 0:
        print("\n💰 RESULT: This strategy IS PROFITABLE in this regime!")
    else:
        print("\n⚠️ RESULT: Strategy needs more tuning to cover fees/slippage.")

if __name__ == "__main__":
    run_test()
