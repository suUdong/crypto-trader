"""
사이클 203 — c202 경계 탐색 확장 (ADX/OBV 하한 영역)
- c202 OOS 최적: ADX_TH=15, OBV_EMA_LB=5, OBV_SLOPE_MIN=0.00 — 모두 그리드 하한
  → 진짜 최적이 더 낮은 영역에 있을 가능성. 경계를 확장 탐색한다.
- 새 그리드 (3×3×3 = 27):
    ADX_TH:        [5, 10, 15]
    OBV_EMA_LB:    [3, 5, 7]
    OBV_SLOPE_MIN: [-0.02, 0.00, 0.02]
- 외 모든 파라미터는 c202 고정값을 그대로 재사용 (c199/c192/.../c164).
- 3-fold WF + 슬리피지 스트레스, c202 모듈을 import 하여 그리드만 교체.
- 목표: OOS Sharpe >= 35 AND trades >= 20 (c202 baseline +32.217 / 22 trades 초과)
- 진입: next_bar open (c202와 동일)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest_cycle202_vpin_adx_obv_entry_gate as c202

# -- 그리드 교체 --
c202.ADX_TH_LIST = [5, 10, 15]
c202.OBV_EMA_LB_LIST = [3, 5, 7]
c202.OBV_SLOPE_MIN_LIST = [-0.02, 0.00, 0.02]


def main() -> None:
    print("=" * 80)
    print("=== 사이클 203 — c202 경계 확장 (ADX 하한 + OBV 음수 slope 허용) ===")
    print(f"ADX_TH: {c202.ADX_TH_LIST}")
    print(f"OBV_EMA_LB: {c202.OBV_EMA_LB_LIST}")
    print(f"OBV_SLOPE_MIN: {c202.OBV_SLOPE_MIN_LIST}")
    print("기준선: c202 OOS +32.217 (n=22)")
    print("=" * 80)
    c202.main()


if __name__ == "__main__":
    main()
