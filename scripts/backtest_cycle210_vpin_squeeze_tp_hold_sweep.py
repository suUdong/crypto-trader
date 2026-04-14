"""
vpin_multi 사이클 210 — c209 best 파라미터 고정 후 TP/Hold 차원 확장

- 출발점: c209 OOS 최적 (sqM=2 sqTP=0.5 vsM=0 vsTh=1.5 vsLB=5 comb=0.0)
  → avg_OOS=+37.473 (c199 대비 -13.952 악화)
- 가설: c209는 squeeze/surge 필터 탐색에만 집중했고 TP/Hold 측은
  c164~c199 체인에서 상속한 TP=4.0+2.0, minP=1.5, Hold=20 고정.
  squeeze hard-gate entry + 낮은 sqTP 조합 특성상 TP/Hold 재조정이
  필요하다. c199 +51.425 베이스라인을 다시 넘는 것이 목표.
- 차원:
  TP_BASE_ATR:  [3.0, 3.5, 4.0, 4.5, 5.0]
  MIN_PROFIT_ATR: [1.0, 1.5, 2.0]
  MAX_HOLD_BASE:  [16, 20, 24, 28]
  = 5 × 3 × 4 = 60 combos
- c209 그리드는 그 best 근방 (3 x 2 = 6)으로 좁혀 탐색량 억제:
  sqTP ∈ {0.5, 1.0}, 나머지 벡터는 c209 best 단일값
  → 총 60 × 6 ≈ 360 grid 재평가
- 출력 형식: c209와 동일 (Sharpe/WR/trades 포함)
"""
from __future__ import annotations

import importlib
import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

c209 = importlib.import_module("backtest_cycle209_vpin_squeeze_soft_gate_vol_surge")

# c209 best 근방으로 grid 축소
c209.SQUEEZE_MODE_LIST = [2]
c209.SQUEEZE_TP_BONUS_LIST = [0.5, 1.0]
c209.VOL_SURGE_MODE_LIST = [0]
c209.VOL_SURGE_TH_LIST = [1.5]
c209.VOL_SURGE_LB_LIST = [5]
c209.COMBO_BONUS_LIST = [0.0]

TP_BASE_SWEEP = [3.0, 3.5, 4.0, 4.5, 5.0]
MIN_PROFIT_SWEEP = [1.0, 1.5, 2.0]
MAX_HOLD_SWEEP = [16, 20, 24, 28]

PATTERN = re.compile(
    r"Sharpe:\s*([+-]?\d+(?:\.\d+)?).*?"
    r"WR:\s*([\d.]+)%.*?"
    r"trades:\s*(\d+)",
    re.DOTALL,
)


def run_once(tp_base: float, min_profit: float, max_hold: int) -> tuple[float, float, int, str]:
    c209.TP_BASE_ATR = tp_base
    c209.MIN_PROFIT_ATR = min_profit
    c209.MAX_HOLD_BASE = max_hold
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            c209.main()
    except Exception as exc:  # noqa: BLE001
        return float("-inf"), 0.0, 0, f"ERROR {exc}"
    out = buf.getvalue()
    m = PATTERN.search(out)
    if not m:
        return float("-inf"), 0.0, 0, "NO_MATCH"
    sharpe = float(m.group(1))
    wr = float(m.group(2))
    trades = int(m.group(3))
    return sharpe, wr, trades, out


def main() -> None:
    print("=" * 80)
    print("c210 TP/Hold 확장 스윕 (c209 best 근방 고정)")
    print(f"TP_BASE: {TP_BASE_SWEEP}")
    print(f"MIN_PROFIT: {MIN_PROFIT_SWEEP}")
    print(f"MAX_HOLD: {MAX_HOLD_SWEEP}")
    print("=" * 80)

    results: list[dict] = []
    for tp in TP_BASE_SWEEP:
        for mp in MIN_PROFIT_SWEEP:
            for mh in MAX_HOLD_SWEEP:
                sharpe, wr, trades, _out = run_once(tp, mp, mh)
                tag = "PASS" if sharpe >= 5.0 and trades >= 10 else "fail"
                print(
                    f"  TP={tp:.1f} minP={mp:.1f} Hold={mh}: "
                    f"Sharpe={sharpe:+.3f} WR={wr:.1f}% trades={trades} {tag}"
                )
                results.append({
                    "tp": tp, "mp": mp, "hold": mh,
                    "sharpe": sharpe, "wr": wr, "trades": trades,
                })

    results.sort(key=lambda r: r["sharpe"], reverse=True)
    best = results[0]

    print("\n" + "=" * 80)
    print("=== c210 최종 요약 ===")
    print(
        f"★ Best: TP_BASE_ATR={best['tp']} MIN_PROFIT_ATR={best['mp']} "
        f"MAX_HOLD_BASE={best['hold']}"
    )
    print(f"  (c209 grid 고정: sqM=2 sqTP=0.5/1.0 vsM=0 vsTh=1.5 vsLB=5 comb=0.0)")

    c199_baseline = 51.425
    c209_baseline = 37.473
    delta199 = best["sharpe"] - c199_baseline
    delta209 = best["sharpe"] - c209_baseline
    print(f"  vs c199 (+{c199_baseline}): Δ={delta199:+.3f}")
    print(f"  vs c209 (+{c209_baseline}): Δ={delta209:+.3f}")

    print(f"\nSharpe: {best['sharpe']:+.3f}")
    print(f"WR: {best['wr']:.1f}%")
    print(f"trades: {best['trades']}")


if __name__ == "__main__":
    main()
