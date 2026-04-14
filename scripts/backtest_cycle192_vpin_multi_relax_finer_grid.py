"""vpin_multi 사이클 192 — c191 최적점 주변 미세 그리드 + 완화범위 확장.

기반: c191 OOS 최적 slB=0.1 rTh=0.20 rF=0.7 → avg_OOS=+22.881 trades=33
     (c190 baseline +29.342 trades=26 대비 trades↑ Sharpe↓)

가설:
  1) c191 그리드는 RELAX_VOL_MOM_TH 상한이 0.20이라 강모멘텀에서만 완화.
     문턱을 더 높이면(완화 트리거 적게 발생) c190 Sharpe에 근접하면서
     추가 trades 일부 유지 가능할 것.
  2) RELAX_FACTOR=0.7이 최적이었음 → 0.6~0.9 미세 탐색으로 sweet spot 확인.
  3) SL_SLOPE_BONUS=0.1이 최적 → 0.05~0.20 미세 탐색.

탐색 그리드 (c191 모듈 재사용, 그리드 상수만 override):
  SL_SLOPE_BONUS:    [0.05, 0.10, 0.15, 0.20]
  RELAX_VOL_MOM_TH:  [0.15, 0.20, 0.25, 0.30, 0.40]
  RELAX_FACTOR:      [0.6, 0.7, 0.8, 0.9]
  = 4×5×4 = 80 combos

목표: avg_OOS Sharpe >= 25 AND trades >= 30
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_cycle191_vpin_multi_adaptive_sl_relaxed_entry as c191

# -- 그리드 override --
c191.SL_SLOPE_BONUS_LIST = [0.05, 0.10, 0.15, 0.20]
c191.RELAX_VOL_MOM_TH_LIST = [0.15, 0.20, 0.25, 0.30, 0.40]
c191.RELAX_FACTOR_LIST = [0.6, 0.7, 0.8, 0.9]


if __name__ == "__main__":
    print("=" * 80)
    print("=== 사이클 192 — c191 미세 그리드 (slB×rTh×rF = 4×5×4 = 80) ===")
    print("기반: c191 최적 slB=0.10 rTh=0.20 rF=0.70 avg_OOS=+22.881 n=33")
    print("목표: avg_OOS Sharpe >= 25 AND trades >= 30")
    print("=" * 80)
    c191.main()
