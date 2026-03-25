from __future__ import annotations

import unittest

from crypto_trader.models import DriftReport, DriftStatus, PromotionGateDecision, PromotionStatus
from crypto_trader.operator.memo import OperatorDailyMemo


def _build_drift() -> DriftReport:
    return DriftReport(
        generated_at="2026-03-25T00:00:00Z",
        symbol="KRW-BTC",
        status=DriftStatus.ON_TRACK,
        reasons=["aligned"],
        backtest_total_return_pct=0.1,
        backtest_win_rate=0.6,
        backtest_max_drawdown=0.1,
        backtest_trade_count=5,
        paper_run_count=6,
        paper_error_rate=0.0,
        paper_buy_rate=0.2,
        paper_sell_rate=0.2,
        paper_hold_rate=0.6,
        paper_realized_pnl_pct=0.04,
    )


def _build_decision() -> PromotionGateDecision:
    return PromotionGateDecision(
        generated_at="2026-03-25T00:00:00Z",
        symbol="KRW-BTC",
        status=PromotionStatus.CANDIDATE_FOR_PROMOTION,
        reasons=["strong"],
        minimum_paper_runs_required=5,
        observed_paper_runs=6,
        backtest_total_return_pct=0.1,
        paper_realized_pnl_pct=0.04,
        drift_status=DriftStatus.ON_TRACK,
    )


class TestMemoWithMacro(unittest.TestCase):
    def test_memo_without_macro_still_works(self) -> None:
        memo = OperatorDailyMemo().render(
            latest_run=None,
            drift_report=_build_drift(),
            promotion_decision=_build_decision(),
        )
        self.assertIn("# Strategy Lab Daily Memo", memo)
        self.assertNotIn("## Macro Environment", memo)

    def test_memo_with_macro_summary(self) -> None:
        macro_summary = {
            "overall_regime": "expansionary",
            "overall_confidence": 0.72,
            "layers": {
                "US": {"regime": "expansionary", "confidence": 0.8},
                "Korea": {"regime": "neutral", "confidence": 0.5},
                "Crypto": {"regime": "expansionary", "confidence": 0.7},
            },
            "crypto_signals": {
                "btc_dominance": 58.3,
                "kimchi_premium": 2.1,
                "fear_greed_index": 65,
            },
        }
        memo = OperatorDailyMemo().render(
            latest_run=None,
            drift_report=_build_drift(),
            promotion_decision=_build_decision(),
            macro_summary=macro_summary,
        )
        self.assertIn("## Macro Environment", memo)
        self.assertIn("expansionary", memo)
        self.assertIn("72%", memo)
        self.assertIn("58.3%", memo)
        self.assertIn("2.1%", memo)
        self.assertIn("65", memo)

    def test_memo_macro_with_none_signals(self) -> None:
        macro_summary = {
            "overall_regime": "contractionary",
            "overall_confidence": 0.6,
            "layers": {
                "US": {"regime": "contractionary", "confidence": 0.7},
                "Korea": {"regime": "neutral", "confidence": 0.4},
                "Crypto": {"regime": "contractionary", "confidence": 0.5},
            },
            "crypto_signals": {
                "btc_dominance": None,
                "kimchi_premium": None,
                "fear_greed_index": None,
            },
        }
        memo = OperatorDailyMemo().render(
            latest_run=None,
            drift_report=_build_drift(),
            promotion_decision=_build_decision(),
            macro_summary=macro_summary,
        )
        self.assertIn("## Macro Environment", memo)
        self.assertIn("contractionary", memo)
        self.assertIn("N/A", memo)


if __name__ == "__main__":
    unittest.main()
