"""
Alpha Score 예측력 검증 스크립트

Alpha Score가 실제 미래 수익률을 예측하는지 검증합니다.
롤링 윈도우로 매 시점 Alpha를 계산 → 이후 N봉 수익률과 상관관계 측정.

결론: Alpha > threshold 필터가 유의미하면 strategy 진입 조건에 추가.
"""
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import torch

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

INTERVAL = "minute240"   # 4시간봉 (lab loop와 동일)
COUNT = 500              # 약 83일치 (충분한 검증 구간)
LOOKBACK = 30            # Alpha 계산 윈도우 (30봉 = 5일)
RECENT_W = 6             # 최근 윈도우 (24시간)
FORWARD_BARS = [1, 3, 6, 12]  # 검증할 미래 구간 (4h 단위: 4h, 12h, 24h, 48h)
ALPHA_THRESHOLD = 1.0    # 필터 기준
TOP_N = 20               # 스캔 종목 수


def detect_btc_regime(btc_df: pd.DataFrame, sma_period: int = 20) -> pd.Series:
    """
    BTC 가격 기반 레짐 감지.
    Returns pd.Series[str]: 인덱스=시간, 값='bull'|'bear'|'pre_bull'|'post_bull'

    - bull: SMA 위 + SMA 기울기 양수
    - bear: SMA 아래 + SMA 기울기 음수
    - pre_bull: SMA 아래이지만 SMA 기울기가 최근 전환(기울기 > -0.5σ)
    - post_bull: SMA 위이지만 SMA 기울기 하락 전환
    """
    closes = btc_df['close']
    sma = closes.rolling(sma_period).mean()
    # SMA 기울기: sma 5봉 변화율
    sma_slope = sma.pct_change(5).fillna(0)
    slope_std = sma_slope.std()

    regime = pd.Series(index=closes.index, dtype=str)
    above_sma = closes > sma
    slope_pos = sma_slope > 0
    slope_recovering = sma_slope > -0.5 * slope_std  # 기울기가 바닥권 탈출 중

    regime[above_sma & slope_pos] = "bull"
    regime[above_sma & ~slope_pos] = "post_bull"
    regime[~above_sma & ~slope_recovering] = "bear"
    regime[~above_sma & slope_recovering] = "pre_bull"
    regime = regime.fillna("bear")
    return regime


def fetch_symbol(symbol: str) -> tuple[str, pd.DataFrame | None]:
    import time
    try:
        import pyupbit
        time.sleep(0.3)  # Upbit rate limit 방지
        df = pyupbit.get_ohlcv(symbol, interval=INTERVAL, count=COUNT)
        if df is None or len(df) < LOOKBACK + max(FORWARD_BARS) + 10:
            return symbol, None
        return symbol, df
    except Exception:
        return symbol, None


def compute_alpha_series(df: pd.DataFrame, btc_df: pd.DataFrame) -> pd.Series:
    """
    각 시점 t에서 과거 LOOKBACK봉의 Alpha Score를 계산합니다.
    Returns: pd.Series (index=df.index[LOOKBACK:])
    """
    common_len = min(len(df), len(btc_df))
    df = df.iloc[-common_len:]
    btc_df = btc_df.iloc[-common_len:]
    n = len(df)

    closes  = torch.tensor(df['close'].values,  device='cuda', dtype=torch.float32)
    opens   = torch.tensor(df['open'].values,   device='cuda', dtype=torch.float32)
    highs   = torch.tensor(df['high'].values,   device='cuda', dtype=torch.float32)
    lows    = torch.tensor(df['low'].values,    device='cuda', dtype=torch.float32)
    vols    = torch.tensor(df['volume'].values, device='cuda', dtype=torch.float32)
    btc_c   = torch.tensor(btc_df['close'].values, device='cuda', dtype=torch.float32)

    alpha_values = []
    for t in range(LOOKBACK, n):
        c  = closes[t - LOOKBACK: t]
        o  = opens [t - LOOKBACK: t]
        h  = highs [t - LOOKBACK: t]
        l  = lows  [t - LOOKBACK: t]
        v  = vols  [t - LOOKBACK: t]
        bc = btc_c [t - LOOKBACK: t]

        # RS
        rs = ((c[-1] / c[0].clamp(1e-9)) / (bc[-1] / bc[0].clamp(1e-9))).item()

        # Acc
        rng = (h - l).clamp(1e-9)
        vpin = (c - o).abs() / rng
        acc = (vpin[-RECENT_W:].mean() / vpin[:-RECENT_W].mean().clamp(1e-9)).item()

        # CVD slope
        direction = torch.where(c >= o, torch.ones_like(v), torch.full_like(v, -1.0))
        cvd = (v * direction).cumsum(0)
        cvd_slope = ((cvd[-1] - cvd[-RECENT_W]) / v.mean().clamp(1e-9)).item()

        alpha_values.append({"rs": rs, "acc": acc, "cvd": cvd_slope})

    df_alpha = pd.DataFrame(alpha_values, index=df.index[LOOKBACK:])

    # z-score 정규화
    for col in ["rs", "acc", "cvd"]:
        std = df_alpha[col].std()
        mean = df_alpha[col].mean()
        df_alpha[f"{col}_z"] = (df_alpha[col] - mean) / (std + 1e-9)

    # 컴포넌트 포함해서 반환 (가중치 최적화에 사용)
    df_alpha["alpha"] = (
        df_alpha["rs_z"] * 0.4 +
        df_alpha["acc_z"] * 0.3 +
        df_alpha["cvd_z"] * 0.3
    )
    return df_alpha  # DataFrame 반환 (rs_z, acc_z, cvd_z, alpha 포함)


def compute_edge(
    alpha_series: pd.Series,
    fwd_returns: pd.Series,
    threshold: float,
) -> tuple[float, float, int]:
    """Alpha > threshold 그룹 vs 나머지 수익률 차이 및 상관계수 반환."""
    common = alpha_series.index.intersection(fwd_returns.dropna().index)
    a, r = alpha_series[common], fwd_returns[common]
    if len(a) < 10:
        return 0.0, 0.0, 0
    corr = float(np.corrcoef(a.values, r.values)[0, 1]) if len(a) > 1 else 0.0
    mask = a > threshold
    edge = (r[mask].mean() - r[~mask].mean()) * 100 if mask.sum() >= 5 else 0.0
    return edge, corr, int(mask.sum())


def find_optimal_params(
    components_list: list[pd.DataFrame],  # each has rs_z, acc_z, cvd_z
    fwd_returns_list: list[pd.Series],
    fwd_bar: int = 6,
) -> tuple[float, float, float, float, float, float]:
    """가중치 + 임계값 그리드 서치로 최적 파라미터 반환.
    Returns: (rs_w, acc_w, cvd_w, threshold, best_edge, best_corr)
    """
    weight_combos = [
        (0.3, 0.35, 0.35),
        (0.4, 0.30, 0.30),
        (0.5, 0.25, 0.25),
        (0.6, 0.20, 0.20),
        (0.4, 0.40, 0.20),
        (0.4, 0.20, 0.40),
    ]
    thresholds = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75]

    best_edge = -999.0
    best_params = (0.4, 0.3, 0.3, 1.0, 0.0, 0.0)

    for rs_w, acc_w, cvd_w in weight_combos:
        # 이 가중치로 alpha 재계산
        alpha_series_list = []
        for comp_df in components_list:
            alpha = comp_df["rs_z"] * rs_w + comp_df["acc_z"] * acc_w + comp_df["cvd_z"] * cvd_w
            alpha_series_list.append(alpha)

        for th in thresholds:
            edges, corrs = [], []
            for alpha_s, fwd_r in zip(alpha_series_list, fwd_returns_list):
                edge, corr, n = compute_edge(alpha_s, fwd_r, th)
                if n >= 5:
                    edges.append(edge)
                    corrs.append(corr)
            if not edges:
                continue
            avg_edge = float(np.mean(edges))
            avg_corr = float(np.mean(corrs))
            if avg_edge > best_edge:
                best_edge = avg_edge
                best_params = (rs_w, acc_w, cvd_w, th, avg_edge, avg_corr)

    return best_params


def validate_alpha_predictiveness(
    df: pd.DataFrame,
    alpha_df: pd.DataFrame,
    symbol: str,
) -> dict:
    """Alpha Score vs 미래 N봉 수익률 상관관계 측정"""
    alpha_series = alpha_df["alpha"]
    closes = df['close'].reindex(alpha_series.index)
    results = {"symbol": symbol}

    for fwd in FORWARD_BARS:
        fwd_returns = closes.shift(-fwd) / closes - 1
        valid = alpha_series.align(fwd_returns, join='inner')
        a_v, r_v = valid[0].dropna(), valid[1].dropna()
        common_idx = a_v.index.intersection(r_v.index)
        a_v, r_v = a_v[common_idx], r_v[common_idx]

        if len(a_v) < 20:
            continue

        corr = float(np.corrcoef(a_v.values, r_v.values)[0, 1])

        # Alpha > threshold 그룹 vs 나머지 수익률 비교
        high_alpha_mask = a_v > ALPHA_THRESHOLD
        if high_alpha_mask.sum() >= 5:
            high_ret = r_v[high_alpha_mask].mean() * 100
            low_ret  = r_v[~high_alpha_mask].mean() * 100
            edge     = high_ret - low_ret
        else:
            high_ret, low_ret, edge = float('nan'), float('nan'), float('nan')

        results[f"corr_{fwd}b"] = round(corr, 3)
        results[f"high_alpha_ret_{fwd}b_%"] = round(high_ret, 3)
        results[f"low_alpha_ret_{fwd}b_%"]  = round(low_ret, 3)
        results[f"edge_{fwd}b_%"] = round(edge, 3)

    return results


def main() -> None:
    import pyupbit
    if not torch.cuda.is_available():
        print("ERROR: CUDA unavailable")
        sys.exit(1)

    print("=" * 70)
    print("  Alpha Score 예측력 검증 (RTX 3080)")
    print(f"  Interval: {INTERVAL} | Count: {COUNT} | Lookback: {LOOKBACK}봉")
    print(f"  Forward bars: {FORWARD_BARS} | Alpha threshold: {ALPHA_THRESHOLD}")
    print("=" * 70)

    symbols = pyupbit.get_tickers(fiat="KRW")
    btc_df = pyupbit.get_ohlcv("KRW-BTC", interval=INTERVAL, count=COUNT)
    btc_regime = detect_btc_regime(btc_df)
    regime_counts = btc_regime.value_counts().to_dict()
    print(f"레짐 분포: {regime_counts}")

    print(f"Fetching {len(symbols)} symbols in parallel...")
    t0 = time.time()
    all_data: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        for sym, df in ex.map(fetch_symbol, symbols):
            if df is not None:
                all_data[sym] = df
    print(f"Fetched {len(all_data)} symbols in {time.time()-t0:.1f}s")

    print("Computing rolling Alpha + forward return correlation...")
    summary = []
    components_list: list[pd.DataFrame] = []
    fwd_returns_list: list[pd.Series] = []

    # 레짐별 결과 수집
    REGIMES = ["bull", "pre_bull", "bear", "post_bull"]
    regime_summary: dict[str, list[dict]] = {r: [] for r in REGIMES}
    regime_components: dict[str, list] = {r: [] for r in REGIMES}
    regime_fwd: dict[str, list] = {r: [] for r in REGIMES}

    for sym, df in all_data.items():
        try:
            alpha_df = compute_alpha_series(df, btc_df)
            res = validate_alpha_predictiveness(df, alpha_df, sym)
            summary.append(res)
            print(f"  {sym}: corr_1b={res.get('corr_1b', 'N/A')}  edge_6b={res.get('edge_6b_%', 'N/A')}%")
            # 가중치 최적화용 전체 데이터 수집
            components_list.append(alpha_df[["rs_z", "acc_z", "cvd_z"]])
            closes = df['close'].reindex(alpha_df.index)
            fwd_returns_list.append(closes.shift(-6) / closes - 1)
            # 레짐별 분리 수집
            common_idx = alpha_df.index.intersection(btc_regime.index)
            for rname in REGIMES:
                ridx = common_idx[btc_regime.reindex(common_idx) == rname]
                if len(ridx) < 15:
                    continue
                r_alpha = alpha_df.loc[ridx, ["rs_z", "acc_z", "cvd_z"]]
                r_closes = df['close'].reindex(ridx)
                r_fwd = r_closes.shift(-6) / r_closes - 1
                # 간단 edge/corr 계산
                alpha_s = alpha_df.loc[ridx, "alpha"]
                r_fwd_aligned = r_fwd.reindex(alpha_s.index).dropna()
                alpha_aligned = alpha_s.reindex(r_fwd_aligned.index)
                if len(alpha_aligned) >= 10:
                    corr_val = float(np.corrcoef(alpha_aligned.values, r_fwd_aligned.values)[0, 1])
                    mask = alpha_aligned > ALPHA_THRESHOLD
                    edge_val = (r_fwd_aligned[mask].mean() - r_fwd_aligned[~mask].mean()) * 100 if mask.sum() >= 5 else float('nan')
                    regime_summary[rname].append({
                        "symbol": sym, "corr_6b": round(corr_val, 3), "edge_6b_%": round(edge_val, 3) if not np.isnan(edge_val) else None,
                    })
                regime_components[rname].append(r_alpha)
                regime_fwd[rname].append(r_fwd)
        except Exception as e:
            print(f"  {sym}: ERROR {e}")

    if not summary:
        print("No results.")
        return

    df_sum = pd.DataFrame(summary).set_index("symbol")

    print("\n" + "=" * 70)
    print("  검증 결과 요약")
    print("=" * 70)

    # 상관계수 요약
    corr_cols = [c for c in df_sum.columns if c.startswith("corr_")]
    if corr_cols:
        print("\n[Alpha Score ↔ 미래 수익률 상관계수]")
        print(df_sum[corr_cols].to_string())
        mean_corr = df_sum[corr_cols].mean()
        print(f"\n평균 상관계수: {mean_corr.to_dict()}")

    # Edge 요약
    edge_cols = [c for c in df_sum.columns if c.startswith("edge_")]
    if edge_cols:
        print("\n[Alpha > 1.0 진입 vs 나머지 수익률 차이 (%)]")
        print(df_sum[edge_cols].to_string())
        mean_edge = df_sum[edge_cols].mean()
        print(f"\n평균 엣지: {mean_edge.to_dict()}")

    # 최종 판정
    print("\n" + "=" * 70)
    print("  [결론]")
    best_corr_col = corr_cols[-1] if corr_cols else None
    if best_corr_col:
        avg_c = df_sum[best_corr_col].mean()
        best_edge_col = edge_cols[-1] if edge_cols else None
        avg_e = df_sum[best_edge_col].mean() if best_edge_col else 0

        if abs(avg_c) > 0.15 and avg_e > 0.1:
            verdict = "✅ Alpha Score는 유의미한 예측력 있음 → strategy 진입 필터로 추가 권장"
        elif abs(avg_c) > 0.08 or avg_e > 0.05:
            verdict = "⚠️  Alpha Score는 약한 예측력 → 보조 필터로만 활용 권장"
        else:
            verdict = "❌ Alpha Score 예측력 불충분 → 가중치 재조정 또는 다른 지표 검토 필요"
        print(verdict)
    print("=" * 70)

    # ── 가중치 + 임계값 최적화 ──────────────────────────────────────────────
    print("\n[Optimizer] Searching best weights + threshold on GPU components...")
    rs_w, acc_w, cvd_w, opt_th, opt_edge, opt_corr = find_optimal_params(
        components_list, fwd_returns_list, fwd_bar=6
    )
    print(f"  Best: rs={rs_w} acc={acc_w} cvd={cvd_w}  threshold={opt_th}  edge={opt_edge:+.3f}%  corr={opt_corr:.3f}")

    # verdict 결정 (최적화된 파라미터 기준)
    if abs(opt_corr) > 0.15 and opt_edge > 0.1:
        cal_verdict = "valid"
    elif abs(opt_corr) > 0.08 or opt_edge > 0.05:
        cal_verdict = "weak"
    else:
        cal_verdict = "invalid"

    # ── alpha-calibration.json 저장 ─────────────────────────────────────────
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from crypto_trader.strategy.alpha_calibrator import AlphaCalibration, save_calibration

    cal = AlphaCalibration(
        rs_weight=rs_w,
        acc_weight=acc_w,
        cvd_weight=cvd_w,
        threshold=opt_th,
        verdict=cal_verdict,
        avg_edge_6b_pct=round(opt_edge, 4),
        avg_corr_6b=round(opt_corr, 4),
        sample_size=sum(len(c) for c in components_list),
        updated_at=pd.Timestamp.now().isoformat(),
    )
    save_calibration(cal)
    print(f"  Calibration saved → artifacts/alpha-calibration.json  verdict={cal_verdict}")

    # ── 마크다운 리포트 저장 ─────────────────────────────────────────────────
    out_path = Path("artifacts/alpha-backtest-result.md")
    out_path.parent.mkdir(exist_ok=True)
    with out_path.open("w") as f:
        f.write("# Alpha Score 예측력 검증 결과\n\n")
        f.write(f"실행: {pd.Timestamp.now().isoformat()}\n\n")
        # 레짐 분포
        f.write(f"## 레짐 분포\n\n```\n{regime_counts}\n```\n\n")
        # 레짐별 성과
        f.write("## 레짐별 Alpha 성과 (6봉=24h 기준)\n\n")
        for rname in REGIMES:
            r_list = regime_summary[rname]
            if not r_list:
                f.write(f"### {rname}: 데이터 부족\n\n")
                continue
            rdf = pd.DataFrame(r_list)
            avg_corr = round(rdf["corr_6b"].mean(), 3) if "corr_6b" in rdf else None
            edge_vals = rdf["edge_6b_%"].dropna()
            avg_edge = round(edge_vals.mean(), 3) if len(edge_vals) > 0 else None
            f.write(f"### {rname}\n")
            f.write(f"- 종목 수: {len(rdf)}\n")
            f.write(f"- 평균 상관계수(6b): {avg_corr}\n")
            f.write(f"- 평균 엣지(6b): {avg_edge}%\n\n")
        # 기존 전체 요약
        f.write(f"## 전체 최적 파라미터\n\n")
        f.write(f"- 가중치: RS={rs_w} / Acc={acc_w} / CVD={cvd_w}\n")
        f.write(f"- 임계값: {opt_th}\n")
        f.write(f"- 평균 엣지 (6봉): {opt_edge:+.3f}%\n")
        f.write(f"- 평균 상관계수 (6봉): {opt_corr:.3f}\n")
        f.write(f"- **Verdict: {cal_verdict}**\n\n")
        f.write("## 전체 상관계수\n\n```\n")
        f.write(df_sum[corr_cols].to_string() if corr_cols else "N/A")
        f.write("\n```\n\n## Edge (Alpha > 1.0)\n\n```\n")
        f.write(df_sum[edge_cols].to_string() if edge_cols else "N/A")
        f.write("\n```\n")
    print(f"  Report saved → {out_path}")


if __name__ == "__main__":
    main()
