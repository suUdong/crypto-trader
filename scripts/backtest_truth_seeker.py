
import pandas as pd
from datetime import datetime, timedelta
from crypto_trader.config import StrategyConfig, RiskConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.backtest.engine import BacktestEngine

def run_profitability_test():
    # 1. 설정 (수익 극대화 타겟)
    strat_config = StrategyConfig(
        rsi_period=14,
        momentum_lookback=12,
        max_holding_bars=24
    )
    risk_config = RiskConfig(
        stop_loss_pct=0.02,
        take_profit_pct=0.06
    )
    
    # 2. 전략 인스턴스
    strategy = TruthSeekerStrategy(
        config=strat_config,
        vpin_threshold=0.65,
        obi_threshold=0.45
    )

    # 3. 백테스트 엔진 설정 (ETH 60분봉 데이터 사용 가정)
    # 실제 환경의 candle_cache에서 데이터를 가져와야 함
    print("--- Starting Full Profitability Backtest: Truth-Seeker (ETH) ---")
    
    # (참고: 실제 백테스트 엔진을 돌리려면 데이터 로딩 로직이 필요함)
    # 여기서는 엔진의 구조를 활용해 시뮬레이션을 수행하거나, 
    # 기존 엔진 스크립트를 직접 호출하는 방식으로 진행합니다.
    
    # 우선 엔진이 어떻게 데이터를 받는지 확인하기 위해 engine.py를 살짝 봅니다.
    print("Initializing backtest engine...")

if __name__ == "__main__":
    run_profitability_test()
