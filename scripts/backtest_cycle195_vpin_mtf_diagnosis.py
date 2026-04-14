"""c195 진단: 1h 필터별 통과율 분석 — 어떤 필터가 신호를 죽이는지 확인"""
from __future__ import annotations
import math, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from historical_loader import load_historical

# Import indicator functions from main script
from backtest_cycle195_vpin_multi_timeframe_1h_entry_4h_trend import (
    ema_calc, sma_calc, rsi_calc, compute_vpin_bvc, compute_momentum,
    compute_atr, compute_atr_percentile, compute_body_ratio,
    compute_vol_percentile, compute_ema_slope_percentile,
    compute_vol_momentum, precompute_4h_indicators, map_4h_to_1h,
    VPIN_LOW, MOM_THRESH, RSI_PERIOD, RSI_CEILING, RSI_FLOOR,
    EMA_PERIOD_1H, ATR_PERIOD_1H, VOL_SMA_PERIOD_1H,
    VOL_MULT, BODY_RATIO_MIN, VOL_PCTILE_TH, VOL_PCTILE_LB_1H,
    RSI_DELTA_LB, RSI_DELTA_MIN, VOL_MOM_LB_1H, VOL_MOM_MIN,
    EMA_SLOPE_PCTILE_TH_4H, ATR_TH_4H, BTC_SMA_PERIOD_4H,
)


def diagnose_filters(sym: str, period: str = "2024-04-01/2025-01-31"):
    start, end = period.split("/")
    df_1h = load_historical(sym, "60m", "2022-01-01", "2026-04-05")
    df_4h = load_historical(sym, "240m", "2022-01-01", "2026-04-05")
    btc_4h = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-04-05")

    # 1h indicators
    c = df_1h["close"].values
    o = df_1h["open"].values
    h = df_1h["high"].values
    lo = df_1h["low"].values
    v = df_1h["volume"].values

    rsi_arr = rsi_calc(c, RSI_PERIOD)
    ema_arr = ema_calc(c, EMA_PERIOD_1H)
    vpin_arr = compute_vpin_bvc(c, o, h, lo, v, 48)
    mom_arr = compute_momentum(c, 8)
    atr_arr = compute_atr(h, lo, c, ATR_PERIOD_1H)
    vol_sma = sma_calc(v, VOL_SMA_PERIOD_1H)
    body_arr = compute_body_ratio(o, c, h, lo)
    vol_pctile = compute_vol_percentile(v, VOL_PCTILE_LB_1H)
    vol_mom = compute_vol_momentum(v, ema_period=VOL_MOM_LB_1H)

    # 4h indicators mapped
    esp_4h, atp_4h = precompute_4h_indicators(df_4h)
    esp_mapped = map_4h_to_1h(df_4h, esp_4h, df_1h)
    atp_mapped = map_4h_to_1h(df_4h, atp_4h, df_1h)
    btc_c = pd.Series(btc_4h["close"].values, index=btc_4h.index)
    btc_s = pd.Series(sma_calc(btc_4h["close"].values, BTC_SMA_PERIOD_4H),
                       index=btc_4h.index)
    btc_c_m = btc_c.reindex(df_1h.index, method="ffill").values
    btc_s_m = btc_s.reindex(df_1h.index, method="ffill").values

    # Test period mask
    mask = (df_1h.index >= start) & (df_1h.index <= end)
    indices = np.where(mask)[0]
    warmup = 305

    total = 0
    filters = {
        "vpin_low": 0, "mom_thresh": 0, "rsi_range": 0, "price_above_ema": 0,
        "vol_ok": 0, "rsi_velocity": 0, "body_ok": 0, "vol_pctile": 0,
        "vol_mom": 0, "btc_sma": 0, "ema_slope_4h": 0, "atr_pctile_4h": 0,
        "all_pass": 0,
    }

    for i in indices:
        if i < warmup or i >= len(c) - 1:
            continue
        if any(np.isnan(x) for x in [vpin_arr[i], mom_arr[i], rsi_arr[i],
                                       ema_arr[i], atr_arr[i]]):
            continue
        if atr_arr[i] <= 0 or np.isnan(vol_sma[i]) or vol_sma[i] <= 0:
            continue

        total += 1

        vpin_ok = vpin_arr[i] < VPIN_LOW
        mom_ok = mom_arr[i] >= MOM_THRESH
        rsi_ok = RSI_FLOOR < rsi_arr[i] < RSI_CEILING
        ema_ok = c[i] > ema_arr[i]
        v_ok = v[i] >= vol_sma[i] * VOL_MULT

        rsi_prev = i - RSI_DELTA_LB
        rsi_vel_ok = (rsi_prev >= 0 and not np.isnan(rsi_arr[rsi_prev])
                      and (rsi_arr[i] - rsi_arr[rsi_prev]) >= RSI_DELTA_MIN)

        b_ok = body_arr[i] >= BODY_RATIO_MIN and c[i] >= o[i]
        vp_ok = not np.isnan(vol_pctile[i]) and vol_pctile[i] >= VOL_PCTILE_TH
        vm_ok = not np.isnan(vol_mom[i]) and vol_mom[i] >= VOL_MOM_MIN

        btc_ok = (not np.isnan(btc_c_m[i]) and not np.isnan(btc_s_m[i])
                  and btc_c_m[i] > btc_s_m[i])
        esp_ok = not np.isnan(esp_mapped[i]) and esp_mapped[i] >= EMA_SLOPE_PCTILE_TH_4H
        atp_ok = not np.isnan(atp_mapped[i]) and atp_mapped[i] >= ATR_TH_4H

        if vpin_ok: filters["vpin_low"] += 1
        if mom_ok: filters["mom_thresh"] += 1
        if rsi_ok: filters["rsi_range"] += 1
        if ema_ok: filters["price_above_ema"] += 1
        if v_ok: filters["vol_ok"] += 1
        if rsi_vel_ok: filters["rsi_velocity"] += 1
        if b_ok: filters["body_ok"] += 1
        if vp_ok: filters["vol_pctile"] += 1
        if vm_ok: filters["vol_mom"] += 1
        if btc_ok: filters["btc_sma"] += 1
        if esp_ok: filters["ema_slope_4h"] += 1
        if atp_ok: filters["atr_pctile_4h"] += 1

        if all([vpin_ok, mom_ok, rsi_ok, ema_ok, v_ok, rsi_vel_ok,
                b_ok, vp_ok, vm_ok, btc_ok, esp_ok, atp_ok]):
            filters["all_pass"] += 1

    print(f"\n=== {sym} 필터 통과율 ({start}~{end}) ===")
    print(f"총 바: {total}")
    for name, count in sorted(filters.items(), key=lambda x: x[1]):
        pct = count / total * 100 if total > 0 else 0
        print(f"  {name:20s}: {count:5d} ({pct:5.1f}%)")

    # Also check with relaxed 1h params
    print(f"\n=== {sym} 완화된 1h 파라미터 통과율 ===")
    vol_pctile_60 = compute_vol_percentile(v, 60)
    vol_mom_10 = compute_vol_momentum(v, ema_period=10)
    vpin_24 = compute_vpin_bvc(c, o, h, lo, v, 24)

    relaxed = 0
    for i in indices:
        if i < warmup or i >= len(c) - 1:
            continue
        if any(np.isnan(x) for x in [vpin_24[i], mom_arr[i], rsi_arr[i],
                                       ema_arr[i]]):
            continue

        vpin_ok = vpin_24[i] < VPIN_LOW
        mom_ok = mom_arr[i] >= MOM_THRESH
        rsi_ok = RSI_FLOOR < rsi_arr[i] < RSI_CEILING
        ema_ok = c[i] > ema_arr[i]
        v_ok = v[i] >= vol_sma[i] * VOL_MULT if not np.isnan(vol_sma[i]) else False

        rsi_prev = i - 3  # relaxed to 3 bars
        rsi_vel_ok = (rsi_prev >= 0 and not np.isnan(rsi_arr[rsi_prev])
                      and (rsi_arr[i] - rsi_arr[rsi_prev]) >= 3)  # relaxed

        b_ok = body_arr[i] >= 0.3 and c[i] >= o[i]  # relaxed
        vp_ok = (not np.isnan(vol_pctile_60[i])
                 and vol_pctile_60[i] >= 40)  # relaxed lb=60, th=40
        vm_ok = not np.isnan(vol_mom_10[i]) and vol_mom_10[i] >= 0.02  # relaxed

        btc_ok = (not np.isnan(btc_c_m[i]) and not np.isnan(btc_s_m[i])
                  and btc_c_m[i] > btc_s_m[i])
        esp_ok = not np.isnan(esp_mapped[i]) and esp_mapped[i] >= 50
        atp_ok = not np.isnan(atp_mapped[i]) and atp_mapped[i] >= 30

        if all([vpin_ok, mom_ok, rsi_ok, ema_ok, v_ok, rsi_vel_ok,
                b_ok, vp_ok, vm_ok, btc_ok, esp_ok, atp_ok]):
            relaxed += 1

    print(f"  완화 필터 통과: {relaxed} ({relaxed / total * 100:.1f}%)" if total > 0
          else "  데이터 없음")


if __name__ == "__main__":
    for sym in ["KRW-ETH", "KRW-SOL", "KRW-XRP"]:
        diagnose_filters(sym)
