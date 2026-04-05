"""
simulate_kelly_sizing.py
사이클 211 포트폴리오 분석 후속 — half-Kelly 포지션 사이징 시뮬레이션

c179 (vol_regime_adaptive, avg OOS +42.878)
c199 (BB squeeze, avg OOS +51.425)
현재 배포 전략 6종 Kelly fraction 계산 + 몬테카를로 시뮬레이션
"""

import json
import math
import random
from pathlib import Path

import numpy as np

# ─────────────────────────────────────────────
# 1. 전략 메타데이터 (배포 전략 + c179/c199)
# ─────────────────────────────────────────────
STRATEGIES = {
    "vpin_eth": {
        "label": "vpin_eth (c168)",
        "wr": 0.55,
        "avg_ret": 0.018,   # +1.8%
        "sharpe": 14.1,
        "mdd_approx": -0.05,
        "capital": 1_800_000,
    },
    "vpin_sol": {
        "label": "vpin_sol (c165)",
        "wr": 0.56,
        "avg_ret": 0.017,
        "sharpe": 13.3,
        "mdd_approx": -0.05,
        "capital": 1_500_000,
    },
    "bb_squeeze_eth": {
        "label": "bb_squeeze_eth (c185)",
        "wr": 0.61,
        "avg_ret": 0.015,
        "sharpe": 12.3,
        "mdd_approx": -0.04,
        "capital": 1_500_000,
    },
    "vpin_doge": {
        "label": "vpin_doge (c171)",
        "wr": 0.55,
        "avg_ret": 0.016,
        "sharpe": 13.9,
        "mdd_approx": -0.04,
        "capital": 1_200_000,
    },
    "vpin_avax": {
        "label": "vpin_avax (c171)",
        "wr": 0.60,
        "avg_ret": 0.020,
        "sharpe": 16.9,
        "mdd_approx": -0.04,
        "capital": 1_200_000,
    },
    "bb_squeeze_doge": {
        "label": "bb_squeeze_doge (c185)",
        "wr": 0.61,
        "avg_ret": 0.015,
        "sharpe": 12.3,
        "mdd_approx": -0.04,
        "capital": 1_000_000,
    },
}

# c179 / c199 OOS 결과 (backtest_history.md 기반)
C179_META = {
    "label": "vol_regime_adaptive (c179)",
    "wr": 0.55,       # 대표값 (WF 평균)
    "avg_ret": 0.018,
    "sharpe": 42.878, # avg OOS Sharpe
    "mdd_approx": -0.03,
}
C199_META = {
    "label": "bb_squeeze_multi (c199)",
    "wr": 0.61,
    "avg_ret": 0.015,
    "sharpe": 51.425,
    "mdd_approx": -0.03,
}


# ─────────────────────────────────────────────
# 2. Kelly Criterion 계산
# ─────────────────────────────────────────────
def compute_kelly(wr: float, avg_ret: float) -> dict:
    """
    Kelly fraction 계산.
    avg_loss = avg_ret * 2 근사 (손익비 대칭+보수적 가정은 avg_loss = avg_win으로 조정)
    b = avg_win / avg_loss
    f* = (p*b - q) / b
    """
    p = wr
    q = 1.0 - p

    # avg_win / avg_loss 계산
    # WR * avg_win - (1-WR) * avg_loss = avg_ret
    # 보수적 근사: avg_loss = 0.5 * avg_win
    # → WR * avg_win - (1-WR) * 0.5 * avg_win = avg_ret
    # → avg_win * (WR - 0.5*(1-WR)) = avg_ret
    # → avg_win * (WR - 0.5 + 0.5*WR) = avg_ret
    # → avg_win * (1.5*WR - 0.5) = avg_ret
    denom = 1.5 * p - 0.5
    if denom <= 0:
        avg_win = avg_ret / max(p, 0.01)
    else:
        avg_win = avg_ret / denom

    avg_loss = 0.5 * avg_win   # 손실 = 수익의 절반 (보수적 근사)
    b = avg_win / avg_loss     # = 2.0

    kelly = (p * b - q) / b
    half_kelly = kelly / 2.0

    return {
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "b_ratio": b,
        "kelly": max(0.0, kelly),
        "half_kelly": max(0.0, half_kelly),
    }


# ─────────────────────────────────────────────
# 3. 몬테카를로 시뮬레이션
# ─────────────────────────────────────────────
def simulate_portfolio(
    strategies: list[dict],
    position_mode: str,  # "fixed", "half_kelly", "full_kelly"
    initial_capital: float = 10_000_000,
    n_trades: int = 100,
    n_sim: int = 1000,
    fixed_frac: float = 0.05,
    trades_per_year: int = 100,
    random_seed: int = 42,
) -> dict:
    """
    strategies: list of {wr, avg_win, avg_loss, kelly, half_kelly, capital_weight}
    position_mode: "fixed" | "half_kelly" | "full_kelly"
    Returns aggregated stats across all simulations.
    """
    rng = np.random.default_rng(random_seed)

    final_values = []
    mdds = []
    sharpes = []

    total_weight = sum(s["capital_weight"] for s in strategies)

    for _ in range(n_sim):
        equity = initial_capital
        peak = equity
        mdd = 0.0
        log_returns = []

        for _t in range(n_trades):
            trade_pnl_total = 0.0

            for s in strategies:
                w = s["capital_weight"] / total_weight  # 포트폴리오 내 비중

                if position_mode == "fixed":
                    frac = fixed_frac
                elif position_mode == "half_kelly":
                    frac = s["half_kelly"]
                else:  # full_kelly
                    frac = s["kelly"]

                # 한 전략당 포지션 크기
                pos_size = equity * w * frac

                # 승패 결정
                if rng.random() < s["wr"]:
                    pnl = pos_size * s["avg_win"]
                else:
                    pnl = -pos_size * s["avg_loss"]

                trade_pnl_total += pnl

            equity += trade_pnl_total
            if equity <= 0:
                equity = 1  # 파산 처리

            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            mdd = max(mdd, dd)

            log_returns.append(math.log(max(equity, 1) / max(equity - trade_pnl_total, 1)) if (equity - trade_pnl_total) > 0 else 0.0)

        # CAGR 계산 (n_trades = trades_per_year 가정)
        years = n_trades / trades_per_year
        cagr = (equity / initial_capital) ** (1.0 / max(years, 1e-6)) - 1.0

        # Sharpe 계산 (연환산)
        lr = np.array(log_returns)
        if lr.std() > 0:
            sharpe = (lr.mean() / lr.std()) * math.sqrt(trades_per_year)
        else:
            sharpe = 0.0

        final_values.append(equity)
        mdds.append(mdd)
        sharpes.append(sharpe)

    final_arr = np.array(final_values)
    mdd_arr = np.array(mdds)
    sharpe_arr = np.array(sharpes)

    cagrs = (final_arr / initial_capital) ** (trades_per_year / n_trades) - 1.0
    bankruptcy_rate = (final_arr <= initial_capital * 0.01).mean()

    return {
        "mean_cagr": float(np.mean(cagrs)),
        "median_cagr": float(np.median(cagrs)),
        "mean_mdd": float(np.mean(mdd_arr)),
        "p95_mdd": float(np.percentile(mdd_arr, 95)),   # 5% worst-case MDD
        "mean_sharpe": float(np.mean(sharpe_arr)),
        "bankruptcy_rate": float(bankruptcy_rate),
        "p5_final": float(np.percentile(final_arr, 5)),
        "p50_final": float(np.median(final_arr)),
        "p95_final": float(np.percentile(final_arr, 95)),
    }


# ─────────────────────────────────────────────
# 4. 메인
# ─────────────────────────────────────────────
def main():
    print("\n" + "=" * 65)
    print("=== Kelly Fraction 분석 ===")
    print("=" * 65)

    kelly_results = {}
    strat_list_for_sim = []

    header = f"{'전략':<28} {'WR':>6} {'avg_ret':>8} {'b-ratio':>8} {'Kelly':>8} {'Half-K':>8}"
    print(header)
    print("-" * 65)

    for key, meta in STRATEGIES.items():
        k = compute_kelly(meta["wr"], meta["avg_ret"])
        kelly_results[key] = {**meta, **k}
        strat_list_for_sim.append({
            "name": key,
            "label": meta["label"],
            "wr": meta["wr"],
            "avg_win": k["avg_win"],
            "avg_loss": k["avg_loss"],
            "kelly": k["kelly"],
            "half_kelly": k["half_kelly"],
            "capital_weight": meta["capital"],
        })
        print(
            f"{meta['label']:<28} {meta['wr']*100:>5.1f}%"
            f"  {meta['avg_ret']*100:>+6.2f}%"
            f"  {k['b_ratio']:>6.2f}x"
            f"  {k['kelly']*100:>6.1f}%"
            f"  {k['half_kelly']*100:>6.1f}%"
        )

    # c179 / c199 참고용
    print()
    print("--- 참고: 백테스트 최적 전략 (미배포) ---")
    for meta in [C179_META, C199_META]:
        k = compute_kelly(meta["wr"], meta["avg_ret"])
        print(
            f"{meta['label']:<28} {meta['wr']*100:>5.1f}%"
            f"  {meta['avg_ret']*100:>+6.2f}%"
            f"  {k['b_ratio']:>6.2f}x"
            f"  {k['kelly']*100:>6.1f}%"
            f"  {k['half_kelly']*100:>6.1f}%"
        )

    # ─── 시뮬레이션 ───
    INITIAL_CAPITAL = 10_000_000
    N_TRADES = 100
    N_SIM = 1000

    print()
    print("=" * 65)
    print(f"=== 포트폴리오 시뮬레이션 ===")
    print(f"    초기자본 {INITIAL_CAPITAL:,}원 | {N_TRADES}거래 | {N_SIM}회 MC")
    print("=" * 65)

    modes = [
        ("현재 고정(5%)", "fixed"),
        ("Half-Kelly",    "half_kelly"),
        ("Full-Kelly",    "full_kelly"),
    ]

    sim_results = {}
    header2 = f"{'방식':<16} {'평균CAGR':>9} {'중간CAGR':>9} {'평균MDD':>8} {'5%VaR MDD':>10} {'평균Sharpe':>10} {'파산확률':>8}"
    print(header2)
    print("-" * 75)

    for label, mode in modes:
        res = simulate_portfolio(
            strategies=strat_list_for_sim,
            position_mode=mode,
            initial_capital=INITIAL_CAPITAL,
            n_trades=N_TRADES,
            n_sim=N_SIM,
        )
        sim_results[mode] = {"label": label, **res}
        print(
            f"{label:<16}"
            f"  {res['mean_cagr']*100:>+7.1f}%"
            f"  {res['median_cagr']*100:>+7.1f}%"
            f"  {res['mean_mdd']*100:>6.1f}%"
            f"  {res['p95_mdd']*100:>8.1f}%"
            f"  {res['mean_sharpe']:>8.2f}"
            f"  {res['bankruptcy_rate']*100:>6.2f}%"
        )

    # ─── 자산 분포 ───
    print()
    print("--- 최종 자산 분포 (원) ---")
    hdr3 = f"{'방식':<16} {'5%tile':>14} {'중간':>14} {'95%tile':>14}"
    print(hdr3)
    print("-" * 60)
    for label, mode in modes:
        r = sim_results[mode]
        print(
            f"{label:<16}"
            f"  {r['p5_final']:>13,.0f}"
            f"  {r['p50_final']:>13,.0f}"
            f"  {r['p95_final']:>13,.0f}"
        )

    # ─── Kelly fraction 요약 ───
    kelly_fracs = [s["half_kelly"] * 100 for s in strat_list_for_sim]
    avg_hk = sum(kelly_fracs) / len(kelly_fracs)
    max_hk = max(kelly_fracs)
    min_hk = min(kelly_fracs)

    print()
    print("=" * 65)
    print("=== 권고사항 ===")
    print(f"  Half-Kelly 범위: {min_hk:.1f}% ~ {max_hk:.1f}%  (평균 {avg_hk:.1f}%)")
    print(f"  현재 고정 5% 대비 Half-Kelly:")
    hk_cagr = sim_results["half_kelly"]["mean_cagr"] * 100
    fix_cagr = sim_results["fixed"]["mean_cagr"] * 100
    hk_mdd  = sim_results["half_kelly"]["mean_mdd"] * 100
    fix_mdd = sim_results["fixed"]["mean_mdd"] * 100
    print(f"    CAGR Δ = {hk_cagr - fix_cagr:+.1f}%p  |  MDD Δ = {hk_mdd - fix_mdd:+.1f}%p")

    if hk_cagr > fix_cagr and hk_mdd <= fix_mdd * 1.5:
        verdict = "Half-Kelly 채택 권고 — CAGR 개선, MDD 허용 범위"
    elif hk_cagr > fix_cagr:
        verdict = "Half-Kelly 검토 권고 — CAGR 개선, MDD 증가 모니터링 필요"
    else:
        verdict = "현재 고정 5% 유지 권고 — Half-Kelly 개선 없음"

    print(f"  결론: {verdict}")
    print("=" * 65)

    # ─── JSON 저장 ───
    report = {
        "generated_at": "2026-04-04",
        "cycle": "c211",
        "description": "half-Kelly 포지션 사이징 포트폴리오 시뮬레이션",
        "params": {
            "initial_capital": INITIAL_CAPITAL,
            "n_trades": N_TRADES,
            "n_simulations": N_SIM,
            "fixed_fraction": 0.05,
        },
        "kelly_fractions": {
            k: {
                "label": v["label"],
                "wr": v["wr"],
                "avg_ret": v["avg_ret"],
                "b_ratio": round(v["b_ratio"], 4),
                "kelly": round(v["kelly"], 4),
                "half_kelly": round(v["half_kelly"], 4),
            }
            for k, v in kelly_results.items()
        },
        "simulation_results": {
            mode: {k2: v2 for k2, v2 in res.items()}
            for mode, res in sim_results.items()
        },
        "recommendation": {
            "avg_half_kelly_pct": round(avg_hk, 2),
            "min_half_kelly_pct": round(min_hk, 2),
            "max_half_kelly_pct": round(max_hk, 2),
            "cagr_delta_vs_fixed": round(hk_cagr - fix_cagr, 2),
            "mdd_delta_vs_fixed": round(hk_mdd - fix_mdd, 2),
            "verdict": verdict,
        },
    }

    out_path = Path(__file__).parent.parent / "state" / "kelly_sizing_report.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n보고서 저장: {out_path}")


if __name__ == "__main__":
    main()
