
import json
from datetime import datetime, timedelta
from crypto_trader.config import StrategyConfig, RiskConfig
from crypto_trader.models import Candle
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy

def verify():
    # 1. 설정 초기화
    strat_config = StrategyConfig(
        rsi_period=14,
        momentum_lookback=12,
        max_holding_bars=24
    )
    
    # 2. 전략 초기화 (허수아비 필터 강화 버전)
    strategy = TruthSeekerStrategy(
        config=strat_config,
        vpin_threshold=0.65,
        obi_threshold=0.45,
        anti_spoof_buffer=0.15 
    )

    # 3. 테스트 케이스 시뮬레이션
    print("--- Truth-Seeker Anti-Spoofing Verification ---")
    
    # 사례 1: [TRAP] VPIN은 높은데(0.72), 호가창(OBI)이 매도 우위(-0.2)인 경우
    # 기존 VPIN 전략은 여기서 샀겠지만, TruthSeeker는 '가짜 매수세'로 판정해야 함.
    indicators_trap = {"vpin": 0.72, "obi": -0.2, "rsi": 60.0, "adx": 25.0}
    signal_trap = strategy._evaluate_entry(indicators_trap)
    print(f"[TRAP TEST] VPIN: 0.72, OBI: -0.2 => Result: {signal_trap.action} (Reason: {signal_trap.reason})")

    # 사례 2: [REAL] VPIN도 높고(0.72), 호가창도 진짜 매수 우위(0.6)인 경우
    # 실제 수급이 동반된 상승세로 판정하고 진입해야 함.
    indicators_real = {"vpin": 0.72, "obi": 0.6, "rsi": 60.0, "adx": 25.0}
    signal_real = strategy._evaluate_entry(indicators_real)
    print(f"[REAL TEST] VPIN: 0.72, OBI: 0.6 => Result: {signal_real.action} (Reason: {signal_real.reason})")

    # 4. 결과 요약
    print("\n--- Summary ---")
    if signal_trap.action == "hold" and signal_real.action == "buy":
        print("✅ SUCCESS: TruthSeeker successfully filtered the fake pressure trap!")
        print("   (This would have saved us from the March 28th loss)")
    else:
        print("❌ FAILURE: Strategy logic error.")

if __name__ == "__main__":
    verify()
