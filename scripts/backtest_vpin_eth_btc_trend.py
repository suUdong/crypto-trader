"""
vpin_eth + btc_trend_pos 필터 슬라이딩 WF 검증 (사이클 101)
- 목적: vpin_eth W2(2025) WR 23.1% 개선 — btc_trend_pos 필터로 BEAR 환경 진입 억제
- stealth_3gate에서 검증된 btc_trend_pos(BTC 10봉 수익률 > 0)를 vpin_eth에 적용
- 3개 슬라이딩 윈도우 비교: btc_trend_pos ON vs OFF (daemon 기준)
  W1: IS=2022-01~2023-12 / OOS=2024-01~2024-12
  W2: IS=2023-01~2024-12 / OOS=2025-01~2025-12
  W3: IS=2024-01~2025-12 / OOS=2026-01~2026-04
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

ETH_SYMBOL = "KRW-ETH"
BTC_SYMBOL = "KRW-BTC"
FEE = 0.0005

WINDOWS = [
    {"name": "W1", "is_start": "2022-01-01", "is_end": "2023-12-31",
     "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"name": "W2", "is_start": "2023-01-01", "is_end": "2024-12-31",
     "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"name": "W3", "is_start": "2024-01-01", "is_end": "2025-12-31",
     "oos_start": "2026-01-01", "oos_end": "2026-04-04"},
]

# daemon 파라미터 고정
VPIN_HIGH     = 0.55
VPIN_MOM      = 0.0005
MAX_HOLD      = 18
TP            = 0.06
SL            = 0.008
RSI_PERIOD    = 14
RSI_CEILING   = 65.0
RSI_FLOOR     = 20.0
BUCKET_COUNT  = 24
EMA_PERIOD    = 20
MOM_LOOKBACK  = 8
BTC_TREND_WIN = 10  # stealth_3gate 검증값

OOS_SHARPE_MIN = 3.0
OOS_WR_MIN     = 0.30
OOS_TRADES_MIN = 8


def ema(series: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    result[period - 1] = series[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.full(len(closes), np.nan)
    avg_loss = np.full(len(closes), np.nan)
    if len(gains) < period:
        return avg_gain
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    return 100.0 - 100.0 / (1.0 + rs)


def compute_vpin(closes: np.ndarray, opens: np.ndarray, volumes: np.ndarray,
                 bucket_count: int = 24) -> np.ndarray:
    """Simplified VPIN: |close-open|/range proxy."""
    price_range = np.abs(closes - opens) + 1e-9
    vpin_proxy  = np.abs(closes - opens) / (price_range + 1e-9)
    result = np.full(len(closes), np.nan)
    for i in range(bucket_count, len(closes)):
        result[i] = vpin_proxy[i - bucket_count:i].mean()
    return result


def compute_vpin_momentum(closes: np.ndarray, lookback: int = 8) -> np.ndarray:
    mom = np.full(len(closes), np.nan)
    for i in range(lookback, len(closes)):
        mom[i] = closes[i] / closes[i - lookback] - 1
    return mom


def compute_btc_trend_pos(btc_closes: np.ndarray, window: int = 10) -> np.ndarray:
    """BTC trend: close[i] > close[i-window] → True."""
    result = np.full(len(btc_closes), False)
    for i in range(window, len(btc_closes)):
        result[i] = btc_closes[i] > btc_closes[i - window]
    return result


def align_btc_to_eth(df_eth: pd.DataFrame, df_btc: pd.DataFrame) -> np.ndarray:
    """ETH candle timestamp 기준으로 BTC btc_trend_pos 배열을 정렬."""
    btc_closes = df_btc["close"].values
    btc_trend  = compute_btc_trend_pos(btc_closes, BTC_TREND_WIN)

    eth_ts  = df_eth["timestamp"].values if "timestamp" in df_eth.columns else df_eth.index.values
    btc_ts  = df_btc["timestamp"].values if "timestamp" in df_btc.columns else df_btc.index.values

    # ETH 각 캔들에 대해 BTC에서 가장 가까운(≤) 타임스탬프 인덱스 찾기
    aligned = np.full(len(df_eth), False)
    btc_idx = 0
    for i, t in enumerate(eth_ts):
        # BTC에서 t 이하의 마지막 인덱스
        idx = np.searchsorted(btc_ts, t, side="right") - 1
        if idx >= 0:
            aligned[i] = btc_trend[idx]
    return aligned


def backtest(df_eth: pd.DataFrame, df_btc: pd.DataFrame | None,
             use_btc_trend: bool) -> dict:
    c = df_eth["close"].values
    o = df_eth["open"].values
    v = df_eth["volume"].values
    n = len(c)

    rsi_arr  = rsi(c, RSI_PERIOD)
    ema_arr  = ema(c, EMA_PERIOD)
    vpin_arr = compute_vpin(c, o, v, BUCKET_COUNT)
    mom_arr  = compute_vpin_momentum(c, MOM_LOOKBACK)

    btc_trend_arr: np.ndarray | None = None
    if use_btc_trend and df_btc is not None:
        btc_trend_arr = align_btc_to_eth(df_eth, df_btc)

    returns: list[float] = []
    warmup = max(BUCKET_COUNT, EMA_PERIOD, RSI_PERIOD + 1, MOM_LOOKBACK, BTC_TREND_WIN) + 5
    i = warmup
    while i < n - 1:
        rsi_val  = rsi_arr[i]
        ema_val  = ema_arr[i]
        vpin_val = vpin_arr[i]
        mom_val  = mom_arr[i]

        entry_ok = (
            not np.isnan(vpin_val) and vpin_val > VPIN_HIGH
            and not np.isnan(mom_val) and mom_val > VPIN_MOM
            and not np.isnan(rsi_val) and RSI_FLOOR < rsi_val < RSI_CEILING
            and not np.isnan(ema_val) and c[i] > ema_val
        )

        if entry_ok and use_btc_trend and btc_trend_arr is not None:
            entry_ok = entry_ok and bool(btc_trend_arr[i])

        if entry_ok:
            buy = c[i + 1] * (1 + FEE)
            for j in range(i + 2, min(i + 1 + MAX_HOLD, n)):
                ret = c[j] / buy - 1
                if ret >= TP:
                    returns.append(TP - FEE)
                    i = j
                    break
                if ret <= -SL:
                    returns.append(-SL - FEE)
                    i = j
                    break
            else:
                hold_end = min(i + MAX_HOLD, n - 1)
                returns.append(c[hold_end] / buy - 1 - FEE)
                i = hold_end
        else:
            i += 1

    if len(returns) < 3:
        return {"sharpe": float("nan"), "wr": 0.0, "avg_ret": 0.0, "trades": 0}
    arr = np.array(returns)
    sh  = float(arr.mean() / (arr.std() + 1e-9) * np.sqrt(252 * 6))
    wr  = float((arr > 0).mean())
    return {"sharpe": sh, "wr": wr, "avg_ret": float(arr.mean()), "trades": len(arr)}


def print_result(label: str, wname: str, r: dict, is_oos: str = "OOS") -> None:
    sh = r["sharpe"]
    sh_str = f"{sh:+.3f}" if not np.isnan(sh) else "N/A"
    print(f"  {wname} {is_oos} | {label:45s} | "
          f"Sh={sh_str:>8} | WR={r['wr']:.1%} | "
          f"avg={r['avg_ret']:+.3%} | T={r['trades']}")


def main() -> None:
    print("=" * 100)
    print("vpin_eth + btc_trend_pos 필터 슬라이딩 WF 검증 (사이클 101)")
    print("목적: W2(2025) WR 23.1% 개선 — BTC 추세 필터(stealth_3gate 검증 기법) 적용")
    print(f"daemon 파라미터: vh={VPIN_HIGH} vm={VPIN_MOM} hold={MAX_HOLD} TP={TP:.0%} SL={SL:.1%}")
    print(f"btc_trend_win={BTC_TREND_WIN} (BTC 10봉 수익률 > 0)")
    print("=" * 100)

    # 데이터 로드
    print("\n데이터 로드 중...")
    eth_cache: dict[str, pd.DataFrame] = {}
    btc_cache: dict[str, pd.DataFrame] = {}

    for w in WINDOWS:
        for key, start, end in [("is", w["is_start"], w["is_end"]),
                                  ("oos", w["oos_start"], w["oos_end"])]:
            tag = f"{w['name']}_{key}"
            eth_cache[tag] = load_historical(ETH_SYMBOL, "240m", start, end)
            btc_cache[tag] = load_historical(BTC_SYMBOL, "240m", start, end)
            print(f"  {tag}: ETH={len(eth_cache[tag])}행  BTC={len(btc_cache[tag])}행")

    print(f"\n기준: OOS Sharpe > {OOS_SHARPE_MIN} && WR > {OOS_WR_MIN:.0%} && trades >= {OOS_TRADES_MIN}")
    print()

    results: dict[str, list] = {"OFF": [], "ON": []}

    for mode, use_btc in [("OFF (daemon 기준)", False), ("ON  (btc_trend_pos 추가)", True)]:
        label = mode
        passed = 0
        print(f"\n{'='*60}")
        print(f"btc_trend_pos={label}")
        print(f"{'='*60}")

        for w in WINDOWS:
            wn = w["name"]
            r_oos = backtest(eth_cache[f"{wn}_oos"], btc_cache[f"{wn}_oos"], use_btc)
            print_result(label, wn, r_oos)

            ok = (
                not np.isnan(r_oos["sharpe"])
                and r_oos["sharpe"] >= OOS_SHARPE_MIN
                and r_oos["wr"] >= OOS_WR_MIN
                and r_oos["trades"] >= OOS_TRADES_MIN
            )
            if ok:
                passed += 1
                print(f"    ✅ 통과")
            else:
                reasons = []
                if np.isnan(r_oos["sharpe"]) or r_oos["sharpe"] < OOS_SHARPE_MIN:
                    reasons.append(f"Sh<{OOS_SHARPE_MIN}")
                if r_oos["wr"] < OOS_WR_MIN:
                    reasons.append(f"WR<{OOS_WR_MIN:.0%}")
                if r_oos["trades"] < OOS_TRADES_MIN:
                    reasons.append(f"T<{OOS_TRADES_MIN}")
                print(f"    ❌ 탈락: {', '.join(reasons)}")

            key = "ON" if use_btc else "OFF"
            results[key].append({"window": wn, "result": r_oos, "pass": ok})

        print(f"\n  → {passed}/3 통과")

    # 비교 요약
    print("\n" + "=" * 100)
    print("비교 요약 (OFF = daemon 기준, ON = btc_trend_pos 추가)")
    print("=" * 100)
    print(f"{'윈도우':>4} | {'항목':>8} | {'OFF (daemon)':>14} | {'ON (btc_trend)':>16} | {'개선':>8}")
    print("-" * 70)
    for i, w in enumerate(WINDOWS):
        wn = w["name"]
        r_off = results["OFF"][i]["result"]
        r_on  = results["ON"][i]["result"]
        sh_off = r_off["sharpe"]
        sh_on  = r_on["sharpe"]
        wr_off = r_off["wr"]
        wr_on  = r_on["wr"]
        delta_sh = sh_on - sh_off if not (np.isnan(sh_off) or np.isnan(sh_on)) else float("nan")
        delta_wr = wr_on - wr_off

        sh_off_s = f"{sh_off:+.3f}" if not np.isnan(sh_off) else "N/A"
        sh_on_s  = f"{sh_on:+.3f}"  if not np.isnan(sh_on)  else "N/A"
        delta_s  = f"{delta_sh:+.3f}" if not np.isnan(delta_sh) else "N/A"

        print(f"  {wn} | Sharpe   | {sh_off_s:>14} | {sh_on_s:>16} | {delta_s:>8}")
        print(f"     | WR       | {wr_off:>13.1%} | {wr_on:>15.1%} | {delta_wr:>+7.1%}")
        print(f"     | Trades   | {r_off['trades']:>14} | {r_on['trades']:>16} |")
        print()

    off_pass = sum(1 for x in results["OFF"] if x["pass"])
    on_pass  = sum(1 for x in results["ON"]  if x["pass"])
    print(f"통과 합계: OFF={off_pass}/3  ON={on_pass}/3")

    if on_pass > off_pass:
        print("\n✅ btc_trend_pos 필터가 성과 개선 — daemon 반영 검토")
    elif on_pass == off_pass:
        print("\n◆ btc_trend_pos 필터 효과 중립 — 트레이드 수 감소 고려 필요")
    else:
        print("\n❌ btc_trend_pos 필터 역효과 — 미반영")


if __name__ == "__main__":
    main()
