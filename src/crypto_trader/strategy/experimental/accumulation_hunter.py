from __future__ import annotations

import numpy as np

from crypto_trader.config import StrategyConfig
from crypto_trader.models import (
    Candle,
    Position,
    Signal,
    SignalAction,
)
from crypto_trader.strategy.indicators import rsi
from crypto_trader.strategy.vpin import VPINStrategy


class AccumulationBreakoutStrategy:
    """
    [Lab Mode Prototype v1.0]
    Accumulation Breakout Strategy: Focuses on low-volatility periods
    where hidden buying pressure (CVD) and informed trading (VPIN) spike.
    
    Target: 'The Next Solana' (High potential low-cap/mid-cap coins)
    """

    def __init__(
        self,
        config: StrategyConfig,
        vpin_threshold: float = 0.55,
        cvd_slope_threshold: float = 10.0,
        volatility_ceiling: float = 0.015,  # 1.5% max volatility for accumulation
        stealth_lookback: int = 36,  # backtest 최적값 W=36 (Sharpe +4.682)
        stealth_rs_low: float = 0.5,  # RS 하한: 너무 약한 종목 제외
        stealth_rs_high: float = 1.0,  # RS 상한: 이미 오른 종목 제외 (< high)
    ) -> None:
        self._config = config
        self._vpin_threshold = vpin_threshold
        self._cvd_slope_threshold = cvd_slope_threshold
        self._volatility_ceiling = volatility_ceiling
        self._stealth_lookback = stealth_lookback
        self._stealth_rs_low = stealth_rs_low
        self._stealth_rs_high = stealth_rs_high
        self._vpin_strategy = VPINStrategy(config=config, vpin_high_threshold=vpin_threshold, bucket_count=24)

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
    ) -> Signal:
        if len(candles) < 48:
            return Signal(action=SignalAction.HOLD, reason="insufficient_data", confidence=0.0)

        closes = [c.close for c in candles]
        volatility = np.std(closes[-24:]) / (closes[-1] + 1e-9)
        vpin_val = self._vpin_strategy._calculate_vpin(candles)
        cvd_val = self._calculate_cvd_slope(candles)
        rsi_val = rsi(closes, self._config.rsi_period)

        # RS 게이트: W봉 수익률 정규화 (시그마 단위). rs_low~rs_high 범위만 진입
        # 백테스트 RS[0.5,1.0) ≈ 이미 강하게 오르지 않았지만 완전히 약하지도 않은 종목
        rs_score = self._calc_rs_score(closes)
        indicators = {
            "volatility": volatility,
            "vpin": vpin_val,
            "cvd_slope": cvd_val,
            "rsi": rsi_val,
            "rs_score": rs_score,
        }

        if not (self._stealth_rs_low <= rs_score < self._stealth_rs_high):
            return Signal(
                action=SignalAction.HOLD,
                reason=f"rs_out_of_range_{rs_score:.2f}",
                confidence=0.0,
                indicators=indicators,
            )

        # VPIN 독성 게이트: 높은 VPIN = 독성 오더플로우 → 진입 차단
        if vpin_val > self._vpin_threshold:
            return Signal(
                action=SignalAction.HOLD,
                reason="vpin_high_toxicity",
                confidence=0.0,
                indicators=indicators,
            )

        if position is not None:
            return self._evaluate_exit(position, indicators, candles)

        # --- v2 Scoring-based Logic ---
        score = 0.0
        # 1. 수급 점수 (CVD)
        if cvd_val > self._cvd_slope_threshold: score += 0.5
        elif cvd_val > 5.0: score += 0.2

        # 2. 정보 거래 점수 (VPIN) - 낮을수록 안전한 진입
        if vpin_val < 0.3: score += 0.4
        elif vpin_val < 0.4: score += 0.1

        # 3. 변동성 점수 (응축도)
        if volatility < self._volatility_ceiling: score += 0.3
        elif volatility < 0.03: score += 0.1

        # 가중치 합산이 0.7 이상이고 RSI가 과매수가 아닐 때 진입
        if score >= 0.7 and rsi_val < 65:
            return Signal(
                action=SignalAction.BUY,
                reason=f"accumulation_score_hit_{score:.1f}",
                confidence=score,
                indicators=indicators
            )

        return Signal(action=SignalAction.HOLD, reason=f"low_score_{score:.1f}", confidence=0.0, indicators=indicators)

    def _calc_rs_score(self, closes: list[float]) -> float:
        """W봉 수익률을 [0,1] 범위로 정규화한 RS 프록시.

        0.0 = 완전 하락, 1.0 = 최근 최고점 갱신 중.
        백테스트 RS[0.5,1.0) 기준: 적당히 오른 종목만 진입.
        """
        w = min(self._stealth_lookback, len(closes) - 1)
        if w < 2:
            return 0.5  # 데이터 부족 시 중간값으로 통과
        window = closes[-w - 1:]
        lo, hi = min(window), max(window)
        if hi <= lo:
            return 0.5
        return (closes[-1] - lo) / (hi - lo)

    def _calculate_cvd_slope(self, candles: list[Candle]) -> float:
        """Measure the acceleration of net buying volume."""
        recent = candles[-self._stealth_lookback:]
        deltas = [c.volume if c.close >= c.open else -c.volume for c in recent]
        cvd = np.cumsum(deltas)
        slope = (cvd[-1] - cvd[0]) / (np.mean([c.volume for c in recent]) + 1e-9)
        return slope

    def _evaluate_exit(self, position: Position, ind: dict[str, float], candles: list[Candle]) -> Signal:
        # Exit if RSI is overbought (Blow-off top)
        if ind["rsi"] > 75.0:
            return Signal(action=SignalAction.SELL, reason="rsi_overbought_peak", confidence=1.0)
        
        # Standard time-based exit
        holding_bars = len(candles) - (position.entry_index or 0)
        if holding_bars > self._config.max_holding_bars:
            return Signal(action=SignalAction.SELL, reason="max_holding_reached", confidence=1.0)
            
        return Signal(action=SignalAction.HOLD, reason="waiting_for_breakout_peak", confidence=0.0)
