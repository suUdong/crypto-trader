#!/usr/bin/env python3
"""
사이클 113: SUI vs 기존 7심볼 상관관계 분석 + daemon.toml 초안 검토
- 분석 기간: 2024-01-01 ~ 2026-04-03 (BULL 레짐 포함 2년)
- 심볼: AVAX/LINK/APT/XRP/ADA/DOT/ATOM (현재 stealth_3gate_wallet_1) + SUI
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np
import pandas as pd

from historical_loader import load_historical

SYMBOLS = ["KRW-AVAX", "KRW-LINK", "KRW-APT", "KRW-XRP", "KRW-ADA", "KRW-DOT", "KRW-ATOM", "KRW-SUI"]
START = "2024-01-01"
END = "2026-04-03"
CTYPE = "240m"


def main() -> None:
    print(f"=== SUI 상관관계 분석 ({START} ~ {END}) ===\n")

    # 데이터 로드
    closes: dict[str, pd.Series] = {}
    for sym in SYMBOLS:
        try:
            df = load_historical(sym, CTYPE, START, END)
            if len(df) < 50:
                print(f"  {sym}: 데이터 부족 ({len(df)}행)")
                continue
            closes[sym] = df["close"]
            print(f"  {sym}: {len(df)}행 로드 완료 ({df.index[0].date()} ~ {df.index[-1].date()})")
        except Exception as e:
            print(f"  {sym}: 로드 실패 — {e}")

    if len(closes) < 2:
        print("\n분석 불가: 데이터 부족")
        return

    # 공통 인덱스 정렬
    df_closes = pd.DataFrame(closes)
    df_closes = df_closes.dropna(how="all")

    # 4h 수익률
    returns = df_closes.pct_change().dropna()

    print(f"\n공통 기간: {returns.index[0].date()} ~ {returns.index[-1].date()} ({len(returns)}봉)\n")

    # 상관관계 행렬
    corr = returns.corr()

    # SUI vs 각 심볼 상관계수
    if "KRW-SUI" in corr.columns:
        print("=== SUI vs 기존 7심볼 상관계수 ===")
        sui_corr = corr["KRW-SUI"].drop("KRW-SUI").sort_values(ascending=False)
        for sym, val in sui_corr.items():
            bar = "█" * int(abs(val) * 20)
            sign = "+" if val > 0 else ""
            print(f"  {sym:<14} {sign}{val:.3f}  {bar}")

        avg_corr = sui_corr.mean()
        max_corr = sui_corr.max()
        min_corr = sui_corr.min()
        print(f"\n  평균 상관계수: {avg_corr:.3f}")
        print(f"  최고:          {sui_corr.idxmax()} {max_corr:.3f}")
        print(f"  최저:          {sui_corr.idxmin()} {min_corr:.3f}")

    # 전체 상관계수 행렬 (심볼 약칭)
    print("\n=== 전체 상관계수 행렬 ===")
    short_names = {s: s.replace("KRW-", "") for s in corr.columns}
    corr_short = corr.rename(index=short_names, columns=short_names)
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.width", 120)
    print(corr_short.to_string())

    # 포트폴리오 다각화 관점
    print("\n=== 다각화 분석 ===")
    existing_syms = [s for s in closes if s != "KRW-SUI"]
    if "KRW-SUI" in closes and existing_syms:
        existing_returns = returns[[s for s in existing_syms if s in returns.columns]]
        portfolio_ret = existing_returns.mean(axis=1)  # 동일가중
        sui_ret = returns["KRW-SUI"] if "KRW-SUI" in returns.columns else None

        if sui_ret is not None:
            corr_with_portfolio = portfolio_ret.corr(sui_ret)
            print(f"  SUI vs 기존 7심볼 동일가중 포트폴리오: {corr_with_portfolio:.3f}")

            # 포트폴리오 변동성 비교
            portfolio_vol = portfolio_ret.std() * np.sqrt(252 * 6)  # 연환산 (4h봉 = 6봉/일)
            sui_vol = sui_ret.std() * np.sqrt(252 * 6)
            print(f"  기존 포트폴리오 연환산 변동성: {portfolio_vol:.1%}")
            print(f"  SUI 연환산 변동성: {sui_vol:.1%}")

            # SUI 추가 시 포트폴리오 효과
            w_existing = 7 / 8  # 기존 7심볼 합산 비중
            w_sui = 1 / 8
            combined_ret = portfolio_ret * w_existing + sui_ret * w_sui
            combined_vol = combined_ret.std() * np.sqrt(252 * 6)
            print(f"  SUI 1/8 추가 후 포트폴리오 변동성: {combined_vol:.1%}")

            vol_change = combined_vol - portfolio_vol
            print(f"  변동성 변화: {vol_change:+.1%}")

    # daemon.toml SUI 추가 초안
    print("\n" + "=" * 60)
    print("=== daemon.toml SUI PRE-STAGED 초안 ===")
    print("=" * 60)
    print("""
# stealth_3gate_wallet_1에 KRW-SUI 추가 옵션:
# 근거: W2 Sharpe +3.990, W3 Sharpe +3.068 (2/3창 통과)
# W1 실패는 SUI 초기 BEAR(2023) — Gate1(BTC>SMA20) 실전 차단
# 활성화 조건: pre_bull_score ≥ 0.90 + BTC>SMA20 확인 시
#
# 현재 symbols 라인을 아래로 교체:
# symbols = ["KRW-AVAX", "KRW-LINK", "KRW-APT", "KRW-XRP",
#            "KRW-ADA", "KRW-DOT", "KRW-ATOM", "KRW-SUI"]
#
# 주의: Sharpe 5.0 기준 미달(최고 +3.990) → live 전환 전 추가 검증 권장
# 대안: 별도 stealth_3gate_wallet_sui 생성 (자본 250,000~500,000)
""")

    print("\n[사이클 113 완료]")


if __name__ == "__main__":
    main()
