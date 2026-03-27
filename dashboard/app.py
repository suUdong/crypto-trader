"""Unified crypto-trader dashboard with v2 research and reporting tabs."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.auth import require_auth  # noqa: E402
from dashboard.data import (  # noqa: E402
    FEAR_GREED_ZONES,
    load_checkpoint,
    load_daemon_heartbeat,
    load_daily_performance,
    load_daily_report,
    load_data_freshness,
    load_edge_analysis,
    load_funding_rate_research,
    load_health,
    load_macro_summary,
    load_momentum_pullback_research,
    load_operator_report,
    load_pnl_report,
    load_promotion_gate,
    load_regime_panel_data,
    load_risk_overview,
    load_signal_history,
    load_signal_monitor_data,
    load_wallet_analytics,
    load_weekly_report,
    regime_kr,
    strategy_kr,
    symbol_kr,
)
from dashboard.styles import COLORS, PALETTE, chart_layout, inject_css, pnl_color  # noqa: E402

_UTC = timezone.utc  # noqa: UP017
_KST = timezone(timedelta(hours=9))

st.set_page_config(
    page_title="크립토 트레이더",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)
require_auth()
inject_css()

st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)


def _empty(message: str) -> None:
    st.info(message)


def _format_krw(value: float) -> str:
    return f"₩{value:,.0f}"


def _format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _status_class(level: str) -> str:
    return {
        "ok": "status-ok",
        "warn": "status-warn",
        "fail": "status-fail",
    }.get(level, "status-warn")


def _metric_delta(value: float, suffix: str = "%") -> str:
    return f"{value:+.2f}{suffix}"


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "-"
    return str(value).replace("T", " ")[:19]


def _render_status_row(heartbeat: dict[str, Any] | None, freshness: dict[str, Any]) -> None:
    checkpoint_info = freshness["files"].get("runtime-checkpoint.json", {})
    if checkpoint_info.get("exists"):
        age_seconds = int(checkpoint_info.get("age_seconds", 0))
        if age_seconds < 120:
            fresh_cls, fresh_text = "status-ok", "실시간"
        elif age_seconds < 300:
            fresh_cls, fresh_text = "status-warn", f"{age_seconds}초 전"
        else:
            fresh_cls, fresh_text = "status-fail", f"{age_seconds // 60}분 전"
    else:
        fresh_cls, fresh_text = "status-fail", "데이터 없음"

    if heartbeat is None:
        st.markdown(
            '<span class="status-badge status-fail">데몬 중지</span> '
            f'<span class="status-badge {fresh_cls}">체크포인트 {fresh_text}</span>',
            unsafe_allow_html=True,
        )
        return

    last_heartbeat = heartbeat.get("last_heartbeat", "")
    poll_interval = int(heartbeat.get("poll_interval_seconds", 60) or 60)
    heartbeat_dt = None
    try:
        heartbeat_dt = datetime.fromisoformat(last_heartbeat)
    except (TypeError, ValueError):
        heartbeat_dt = None
    if heartbeat_dt:
        age_seconds = int((datetime.now(_UTC) - heartbeat_dt).total_seconds())
    else:
        age_seconds = 999999
    is_stale = age_seconds > poll_interval * 2
    daemon_cls = "status-warn" if is_stale else "status-ok"
    daemon_text = "데몬 지연" if is_stale else "데몬 정상"
    uptime = float(heartbeat.get("uptime_seconds", 0.0) or 0.0)
    if uptime >= 3600:
        uptime_text = f"{int(uptime // 3600)}시간 {int((uptime % 3600) // 60)}분"
    else:
        uptime_text = f"{int(uptime // 60)}분"

    status_text = (
        f'<span class="status-badge {daemon_cls}">{daemon_text}</span> '
        f'<span class="status-badge {fresh_cls}">체크포인트 {fresh_text}</span> '
        f"PID {heartbeat.get('pid', '?')} · "
        f"반복 #{heartbeat.get('iteration', 0)} · 가동 {uptime_text}"
    )
    st.markdown(status_text, unsafe_allow_html=True)


def _render_wallet_timeline(wallets: list[dict[str, Any]]) -> None:
    if not wallets:
        _empty("표시할 지갑 데이터가 없습니다.")
        return

    options = [wallet["display_name"] for wallet in wallets]
    default_wallets = options[: min(5, len(options))]
    selected = st.multiselect(
        "실시간 P&L 차트에 표시할 지갑",
        options=options,
        default=default_wallets,
    )
    selected_wallets = [
        wallet for wallet in wallets if wallet["display_name"] in selected
    ] or wallets[:4]

    figure = go.Figure()
    for index, wallet in enumerate(selected_wallets):
        timeline = wallet["timeline"]
        if not timeline:
            continue
        figure.add_trace(
            go.Scatter(
                mode="lines+markers",
                name=wallet["display_name"],
                x=[point["timestamp"] for point in timeline],
                y=[point["equity"] for point in timeline],
                line={"width": 2.5, "color": PALETTE[index % len(PALETTE)]},
                marker={"size": 5},
                hovertemplate=(
                    f"{wallet['display_name']}<br>"
                    "시간: %{x}<br>"
                    "Equity: ₩%{y:,.0f}<extra></extra>"
                ),
            )
        )
    figure.update_layout(
        **chart_layout(
            title="지갑별 실시간 P&L / Equity Curve",
            height=360,
            yaxis_title="Equity (KRW)",
        ),
    )
    st.plotly_chart(figure, width="stretch")


def _render_wallet_matrix(wallets: list[dict[str, Any]]) -> None:
    if not wallets:
        return

    scatter = go.Figure()
    scatter.add_trace(
        go.Scatter(
            mode="markers+text",
            x=[wallet["max_drawdown_pct"] for wallet in wallets],
            y=[wallet["return_pct"] for wallet in wallets],
            text=[wallet["display_name"] for wallet in wallets],
            textposition="top center",
            marker={
                "size": [18 + wallet["open_positions"] * 8 for wallet in wallets],
                "color": [wallet["sharpe"] for wallet in wallets],
                "colorscale": "RdYlGn",
                "showscale": True,
                "colorbar": {"title": "Sharpe"},
                "line": {"width": 1, "color": "rgba(255,255,255,0.3)"},
            },
            hovertemplate=("지갑: %{text}<br>MDD: %{x:.2f}%<br>수익률: %{y:.2f}%<extra></extra>"),
        )
    )
    scatter.update_layout(
        **chart_layout(
            title="Sharpe / MDD / 수익률 포지셔닝",
            height=360,
            xaxis_title="MDD (%)",
            yaxis_title="수익률 (%)",
        ),
        showlegend=False,
    )
    st.plotly_chart(scatter, width="stretch")


def _render_open_positions(wallets: list[dict[str, Any]]) -> None:
    has_positions = any(wallet["positions"] for wallet in wallets)
    if not has_positions:
        _empty("현재 열린 포지션이 없습니다.")
        return

    for wallet in wallets:
        if not wallet["positions"]:
            continue
        st.markdown(f"#### {wallet['display_name']}")
        for position in wallet["positions"]:
            latest_price = position.get("latest_price") or position["entry_price"]
            unrealized = (latest_price - position["entry_price"]) * position["quantity"]
            unrealized_pct = (
                ((latest_price - position["entry_price"]) / position["entry_price"]) * 100.0
                if position["entry_price"] > 0
                else 0.0
            )
            entry_price_text = _format_krw(position["entry_price"])
            pnl_text = _format_krw(unrealized)
            st.markdown(
                f'<div class="dashboard-panel">'
                f"<strong>{position['symbol_display']}</strong> · 진입 {entry_price_text}"
                f" · 수량 {position['quantity']:.6f}<br>"
                f'실시간 P&L <span style="color:{pnl_color(unrealized)};font-weight:700;">'
                f"{pnl_text} ({_format_pct(unrealized_pct)})"
                f"</span>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _render_overview(
    *,
    analytics: dict[str, Any],
    daily_performance: dict[str, Any] | None,
    daily_report: dict[str, Any] | None,
    weekly_report: dict[str, Any] | None,
    risk: dict[str, Any],
    macro: dict[str, Any] | None,
    regime_panel: dict[str, Any],
    promotion_gate: dict[str, Any] | None,
) -> None:
    portfolio = analytics["portfolio"]
    wallets = analytics["wallets"]
    if not wallets:
        _empty("체크포인트가 없어 개요를 표시할 수 없습니다.")
        return

    total_trades = int(daily_performance.get("trade_count", 0) if daily_performance else 0)
    win_rate = float(daily_performance.get("win_rate", 0.0) if daily_performance else 0.0) * 100.0
    profitable_wallets = sum(1 for wallet in wallets if wallet["return_pct"] > 0)

    hero_macro = "매크로 데이터 없음"
    hero_macro_detail = "macro-intelligence API 응답을 기다리는 중"
    if macro:
        hero_macro = (
            macro.get("overall_regime_label") or macro.get("local_regime_label") or "로컬 레짐"
        )
        if macro.get("source_available"):
            hero_macro_detail = (
                f"Crypto {macro.get('crypto_regime_label', '-')}"
                f" · 신뢰도 {float(macro.get('overall_confidence', 0.0)) * 100:.0f}%"
            )
        else:
            hero_macro_detail = "로컬 regime-report 기준"

    promotion_status = promotion_gate.get("status", "unknown") if promotion_gate else "unknown"
    promotion_text = {
        "candidate_for_promotion": "프로모션 준비",
        "stay_in_paper": "페이퍼 유지",
    }.get(promotion_status, "검토 필요")

    st.markdown(
        f"""
        <div class="dashboard-hero">
            <div>
                <span class="eyebrow">Unified Operator View</span>
                <h2>멀티 월렛 운용, 엣지, 연구, 리포트를 v2 탭으로 연결한 대시보드</h2>
                <p>
                    지갑별 실시간 P&amp;L, Sharpe/MDD/수익률, 매크로 레짐, 리스크 축소 상태,
                    전략 연구, 펀딩레이트 검증, 자동 리포트, 엣지 분석을
                    한 화면 흐름으로 정리했습니다.
                </p>
            </div>
            <div class="hero-chip-stack">
                <span class="hero-chip">{hero_macro}</span>
                <span class="hero-chip">{hero_macro_detail}</span>
                <span class="hero-chip">{promotion_text}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metric_columns = st.columns(6)
    metric_columns[0].metric(
        "총 Equity",
        _format_krw(portfolio["total_equity"]),
        _metric_delta(portfolio["portfolio_return_pct"]),
    )
    metric_columns[1].metric("Sharpe", f"{portfolio['portfolio_sharpe']:.2f}", "포트폴리오")
    metric_columns[2].metric("MDD", f"{portfolio['portfolio_mdd']:.2f}%", "포트폴리오")
    metric_columns[3].metric("거래 수", f"{total_trades}", f"승률 {win_rate:.1f}%")
    metric_columns[4].metric("수익 지갑", f"{profitable_wallets}/{len(wallets)}", "활성 월렛")
    metric_columns[5].metric(
        "포지션 축소", f"{risk['position_size_penalty_pct']:.0f}%", risk["reduction_label"]
    )

    info_col, macro_col = st.columns([1.4, 1.0])
    with info_col:
        _render_wallet_timeline(wallets)
    with macro_col:
        st.markdown("#### 매크로 레짐 연동")
        _render_regime_panel(regime_panel)
        _render_fear_greed_gauge(regime_panel)

    _render_report_digest(daily_report=daily_report, weekly_report=weekly_report)

    st.markdown("#### 지갑 리더보드")
    leaderboard_rows = [
        {
            "지갑": wallet["display_name"],
            "전략": strategy_kr(wallet["strategy_type"]),
            "심볼": wallet["symbol_display"],
            "수익률": f"{wallet['return_pct']:+.2f}%",
            "Sharpe": f"{wallet['sharpe']:.2f}",
            "MDD": f"{wallet['max_drawdown_pct']:.2f}%",
            "실현손익": _format_krw(wallet["realized_pnl"]),
            "미실현손익": _format_krw(wallet["unrealized_pnl"]),
            "최근시그널": wallet["latest_signal_action"],
            "레짐": regime_kr(wallet["market_regime"]) if wallet["market_regime"] else "-",
        }
        for wallet in wallets
    ]
    st.dataframe(leaderboard_rows, width="stretch", hide_index=True)


def _render_report_digest(
    *,
    daily_report: dict[str, Any] | None,
    weekly_report: dict[str, Any] | None,
) -> None:
    st.markdown("#### 자동 리포트")
    if daily_report is None and weekly_report is None:
        _empty("저장된 자동 리포트가 없습니다.")
        return

    report_columns = st.columns(2)
    report_specs = [
        ("일일", daily_report, report_columns[0]),
        ("주간", weekly_report, report_columns[1]),
    ]
    for label, report, column in report_specs:
        with column:
            if report is None:
                empty_panel = (
                    f'<div class="dashboard-panel"><strong>{label} 리포트</strong><br>'
                    "아직 생성되지 않았습니다.</div>"
                )
                st.markdown(
                    empty_panel,
                    unsafe_allow_html=True,
                )
                continue
            generated_at = str(report.get("generated_at", ""))[:19] or "-"
            report_return = _format_pct(float(report.get("portfolio_return_pct", 0.0) or 0.0))
            report_sharpe = float(report.get("portfolio_sharpe", 0.0) or 0.0)
            report_mdd = float(report.get("portfolio_mdd_pct", 0.0) or 0.0)
            report_trades = int(report.get("portfolio_trades", 0) or 0)
            report_win_rate = float(report.get("portfolio_win_rate", 0.0) or 0.0) * 100
            report_open_positions = int(report.get("total_open_positions", 0) or 0)
            st.markdown(
                f"""
                <div class="dashboard-panel">
                    <strong>{label} 리포트</strong><br>
                    생성시각 {generated_at}<br>
                    수익률 <strong>{report_return}</strong> ·
                    Sharpe <strong>{report_sharpe:.2f}</strong> ·
                    MDD <strong>{report_mdd:.2f}%</strong><br>
                    거래 <strong>{report_trades}</strong> ·
                    승률 <strong>{report_win_rate:.1f}%</strong> ·
                    오픈 포지션 <strong>{report_open_positions}</strong>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if daily_report is None:
        return

    wallets = daily_report.get("wallets", [])
    if not isinstance(wallets, list) or not wallets:
        return
    st.markdown("#### 일일 리포트 상위 지갑")
    st.dataframe(
        [
            {
                "지갑": str(wallet.get("wallet", "")),
                "전략": strategy_kr(str(wallet.get("strategy", ""))),
                "수익률": _format_pct(float(wallet.get("return_pct", 0.0) or 0.0)),
                "Sharpe": f"{float(wallet.get('sharpe_ratio', 0.0) or 0.0):.2f}",
                "MDD": f"{float(wallet.get('max_drawdown_pct', 0.0) or 0.0):.2f}%",
                "오픈포지션": int(wallet.get("open_positions", 0) or 0),
                "Equity": _format_krw(float(wallet.get("ending_equity", 0.0) or 0.0)),
            }
            for wallet in wallets[:8]
            if isinstance(wallet, dict)
        ],
        width="stretch",
        hide_index=True,
    )


def _render_portfolio_and_risk(
    *,
    analytics: dict[str, Any],
    risk: dict[str, Any],
    health: dict[str, Any] | None,
) -> None:
    wallets = analytics["wallets"]
    if not wallets:
        _empty("리스크를 계산할 지갑 데이터가 없습니다.")
        return

    st.markdown("#### 리스크 상태")
    risk_columns = st.columns(5)
    risk_columns[0].metric(
        "연속 손실",
        f"{risk['consecutive_losses']}회",
        f"한도 {risk['max_consecutive_losses']}회",
    )
    risk_columns[1].metric(
        "MDD",
        f"{risk['portfolio_drawdown_pct']:.2f}%",
        f"한도 {risk['max_portfolio_drawdown_pct']:.2f}%",
    )
    risk_columns[2].metric(
        "일간 손실",
        f"{risk['daily_loss_pct']:.2f}%",
        f"한도 {risk['max_daily_loss_pct']:.2f}%",
    )
    risk_columns[3].metric(
        "포지션 배율",
        f"{risk['position_size_penalty_pct']:.0f}%",
        risk["reduction_label"],
    )
    risk_columns[4].metric(
        "엔진 상태",
        "정상" if (health or {}).get("success", False) else "점검",
        f"오픈 포지션 {(health or {}).get('open_positions', 0)}개",
    )

    if risk["triggered"]:
        st.error(risk["trigger_reason"] or "킬스위치가 발동했습니다.")
    elif risk["warning_active"] or risk["reduction_active"]:
        st.warning(
            f"리스크 경고: 연속 손실 {risk['consecutive_losses']}회, "
            f"포지션 크기 {risk['position_size_penalty_pct']:.0f}%로 축소"
        )
    else:
        st.success("리스크 축소 없이 정상 운용 중입니다.")

    left_col, right_col = st.columns([1.1, 0.9])
    with left_col:
        _render_wallet_matrix(wallets)
    with right_col:
        st.markdown("#### 리스크 히트리스트")
        risk_rows = [
            {
                "지갑": wallet["display_name"],
                "수익률": f"{wallet['return_pct']:+.2f}%",
                "Sharpe": f"{wallet['sharpe']:.2f}",
                "MDD": f"{wallet['max_drawdown_pct']:.2f}%",
                "오픈포지션": wallet["open_positions"],
                "최근시그널": wallet["latest_signal_action"],
            }
            for wallet in sorted(
                wallets,
                key=lambda wallet: (wallet["max_drawdown_pct"], -wallet["return_pct"]),
                reverse=True,
            )
        ]
        st.dataframe(risk_rows, width="stretch", hide_index=True)

    st.markdown("#### 현재 포지션")
    _render_open_positions(wallets)


def _render_edge_analysis(edge: dict[str, Any] | None) -> None:
    if edge is None:
        _empty("paper-trades 기반 엣지 분석 데이터가 없습니다.")
        return

    best_bucket = edge.get("best_bucket") or {}
    worst_bucket = edge.get("worst_bucket") or {}
    metric_columns = st.columns(5)
    metric_columns[0].metric("분석 거래", f"{int(edge['trade_count'])}", edge["timezone"])
    metric_columns[1].metric("누적 실현손익", _format_krw(float(edge["total_pnl"])))
    metric_columns[2].metric("승률", f"{float(edge['win_rate']) * 100:.1f}%")
    metric_columns[3].metric(
        "Best Bucket",
        best_bucket.get("hour_label", "-"),
        best_bucket.get("symbol", "-"),
    )
    metric_columns[4].metric(
        "Worst Bucket",
        worst_bucket.get("hour_label", "-"),
        worst_bucket.get("symbol", "-"),
    )

    heatmap = go.Figure(
        data=
        [
            go.Heatmap(
                x=edge["symbol_labels"],
                y=edge["hour_labels"],
                z=edge["heatmap_total_pnl"],
                customdata=edge["heatmap_trade_count"],
                colorscale=[
                    [0.0, "rgba(255,125,142,0.95)"],
                    [0.5, "rgba(15,29,42,0.85)"],
                    [1.0, "rgba(97,242,162,0.95)"],
                ],
                zmid=0,
                hovertemplate=(
                    "시간대: %{y} KST<br>"
                    "심볼: %{x}<br>"
                    "누적 P&L: ₩%{z:,.0f}<br>"
                    "거래 수: %{customdata}<extra></extra>"
                ),
            )
        ]
    )
    heatmap.update_layout(
        **chart_layout(
            title="시간대 × 심볼 누적 실현손익 히트맵",
            height=520,
            xaxis_title="심볼",
            yaxis_title="시간대 (KST)",
        ),
    )
    st.plotly_chart(heatmap, width="stretch")

    left_col, right_col = st.columns([1.1, 0.9])
    with left_col:
        st.markdown("#### 심볼별 엣지 요약")
        st.dataframe(
            [
                {
                    "심볼": row["symbol_display"],
                    "거래수": row["trade_count"],
                    "누적 P&L": _format_krw(float(row["total_pnl"])),
                    "평균 P&L": _format_krw(float(row["avg_pnl"])),
                    "승률": f"{float(row['win_rate']) * 100:.1f}%",
                    "강한 시간대": row["best_hour"],
                }
                for row in edge["symbol_summary"]
            ],
            width="stretch",
            hide_index=True,
        )
    with right_col:
        st.markdown("#### 시간대별 엣지 요약")
        st.dataframe(
            [
                {
                    "시간대": row["hour_label"],
                    "거래수": row["trade_count"],
                    "누적 P&L": _format_krw(float(row["total_pnl"])),
                    "평균 P&L": _format_krw(float(row["avg_pnl"])),
                    "승률": f"{float(row['win_rate']) * 100:.1f}%",
                }
                for row in edge["hour_summary"]
                if row["trade_count"] > 0
            ],
            width="stretch",
            hide_index=True,
        )

    strongest_rows = edge["bucket_rows"][:6]
    weakest_candidates = list(reversed(edge["bucket_rows"][-6:])) if edge["bucket_rows"] else []
    weakest_rows = [row for row in weakest_candidates if row not in strongest_rows]

    st.markdown("#### Strongest / Weakest Buckets")
    st.dataframe(
        [
            {
                "구간": "Strongest" if index < len(strongest_rows) else "Weakest",
                "시간대": row["hour_label"],
                "심볼": row["symbol_display"],
                "거래수": row["trade_count"],
                "누적 P&L": _format_krw(float(row["total_pnl"])),
                "평균 P&L": _format_krw(float(row["avg_pnl"])),
                "승률": f"{float(row['win_rate']) * 100:.1f}%",
            }
            for index, row in enumerate(strongest_rows + weakest_rows)
        ],
        width="stretch",
        hide_index=True,
    )


def _render_research(research: dict[str, Any] | None) -> None:
    if research is None:
        _empty("momentum_pullback 연구 산출물이 없습니다.")
        return

    best_candidate = research["best_candidate"]
    benchmark_map = research["benchmark_map"]
    best_symbol = research.get("best_symbol")

    metric_columns = st.columns(5)
    metric_columns[0].metric("상태", "Research Only", "배포 미활성")
    metric_columns[1].metric(
        "Best Avg Return",
        f"{float(best_candidate.get('avg_return_pct', 0.0)):+.3f}%",
    )
    metric_columns[2].metric(
        "Best Avg Sharpe", f"{float(best_candidate.get('avg_sharpe', 0.0)):.2f}"
    )
    metric_columns[3].metric(
        "Best Avg MDD", f"{float(best_candidate.get('avg_mdd_pct', 0.0)):.2f}%"
    )
    metric_columns[4].metric("Trades", f"{int(best_candidate.get('total_trades', 0))}")

    if research.get("verdict"):
        verdict_html = (
            '<div class="dashboard-panel"><strong>연구 결론</strong><br>'
            f"{research['verdict']}</div>"
        )
        st.markdown(
            verdict_html,
            unsafe_allow_html=True,
        )

    compare_rows = []
    labels = []
    returns = []
    sharpes = []
    mdds = []
    for key in ("momentum_pullback", "momentum", "mean_reversion"):
        record = best_candidate if key == "momentum_pullback" else benchmark_map.get(key)
        if not record:
            continue
        label = strategy_kr(key)
        labels.append(label)
        returns.append(float(record.get("avg_return_pct", 0.0)))
        sharpes.append(float(record.get("avg_sharpe", 0.0)))
        mdds.append(float(record.get("avg_mdd_pct", 0.0)))
        compare_rows.append(
            {
                "전략": label,
                "Avg Return": f"{float(record.get('avg_return_pct', 0.0)):+.3f}%",
                "Avg Sharpe": f"{float(record.get('avg_sharpe', 0.0)):.2f}",
                "Avg MDD": f"{float(record.get('avg_mdd_pct', 0.0)):.2f}%",
                "Trades": int(record.get("total_trades", 0)),
            }
        )

    chart = go.Figure()
    chart.add_trace(go.Bar(name="Avg Return %", x=labels, y=returns, marker_color=COLORS["green"]))
    chart.add_trace(go.Bar(name="Avg Sharpe", x=labels, y=sharpes, marker_color=COLORS["blue"]))
    chart.add_trace(go.Bar(name="Avg MDD %", x=labels, y=mdds, marker_color=COLORS["yellow"]))
    chart.update_layout(
        **chart_layout(title="momentum_pullback vs benchmarks", height=340),
        barmode="group",
    )
    st.plotly_chart(chart, width="stretch")

    compare_col, symbol_col = st.columns([1.05, 0.95])
    with compare_col:
        st.markdown("#### 전략 비교")
        st.dataframe(compare_rows, width="stretch", hide_index=True)
    with symbol_col:
        st.markdown("#### Best Candidate 파라미터")
        st.code(
            json.dumps(best_candidate.get("params", {}), ensure_ascii=False, indent=2),
            language="json",
        )
        if best_symbol:
            st.markdown(
                f'<div class="dashboard-panel"><strong>Best Symbol</strong><br>'
                f"{symbol_kr(best_symbol['symbol'])} · Sharpe {float(best_symbol['sharpe']):.2f}"
                f" · Return {float(best_symbol['return_pct']):+.2f}%"
                f"</div>",
                unsafe_allow_html=True,
            )

    per_symbol = best_candidate.get("per_symbol", [])
    if per_symbol:
        bubble = go.Figure()
        bubble.add_trace(
            go.Scatter(
                mode="markers+text",
                x=[float(row.get("max_drawdown_pct", 0.0)) for row in per_symbol],
                y=[float(row.get("return_pct", 0.0)) for row in per_symbol],
                text=[symbol_kr(str(row.get("symbol", ""))) for row in per_symbol],
                textposition="top center",
                marker={
                    "size": [12 + int(row.get("trade_count", 0)) for row in per_symbol],
                    "color": [float(row.get("sharpe", 0.0)) for row in per_symbol],
                    "colorscale": "RdYlGn",
                    "showscale": True,
                    "colorbar": {"title": "Sharpe"},
                },
            )
        )
        bubble.update_layout(
            **chart_layout(
                title="Best Candidate per-symbol",
                height=340,
                xaxis_title="MDD (%)",
                yaxis_title="Return (%)",
            ),
            showlegend=False,
        )
        st.plotly_chart(bubble, width="stretch")
        st.dataframe(
            [
                {
                    "심볼": symbol_kr(str(row.get("symbol", ""))),
                    "Return": f"{float(row.get('return_pct', 0.0)):+.2f}%",
                    "Sharpe": f"{float(row.get('sharpe', 0.0)):.2f}",
                    "MDD": f"{float(row.get('max_drawdown_pct', 0.0)):.2f}%",
                    "Trades": int(row.get("trade_count", 0)),
                    "Win Rate": f"{float(row.get('win_rate_pct', 0.0)):.1f}%",
                }
                for row in per_symbol
            ],
            width="stretch",
            hide_index=True,
        )


def _render_funding_rate_research(research: dict[str, Any] | None) -> None:
    if research is None:
        _empty("funding-rate 연구 산출물이 없습니다.")
        return

    best_candidate = research["best_candidate"]
    best_symbol = research.get("best_symbol")
    decision = str(research.get("decision") or "REVIEW_MISSING")
    decision_level = "fail" if "NO_DEPLOY" in decision else "ok"

    metric_columns = st.columns(6)
    metric_columns[0].metric("배포 판정", decision, research.get("review_date") or "-")
    metric_columns[1].metric(
        "Avg Return",
        f"{float(best_candidate.get('avg_return_pct', 0.0)):+.3f}%",
    )
    metric_columns[2].metric(
        "Avg Sharpe",
        f"{float(best_candidate.get('avg_sharpe', 0.0)):.2f}",
    )
    metric_columns[3].metric(
        "Max MDD",
        f"{float(best_candidate.get('max_mdd_pct', 0.0)):.2f}%",
    )
    metric_columns[4].metric("Trades", f"{int(best_candidate.get('trade_count', 0))}")
    metric_columns[5].metric(
        "Best Symbol",
        symbol_kr(str(best_symbol.get("symbol", ""))) if best_symbol else "-",
        f"Sharpe {float(best_symbol.get('sharpe', 0.0)):.2f}" if best_symbol else "-",
    )

    scope_text = research.get("review_scope") or "배포 리뷰 문서 없음"
    st.markdown(
        f'<div class="dashboard-panel"><strong>Funding-rate Deployment Review</strong><br>'
        f'<span class="status-badge {_status_class(decision_level)}">{decision}</span> '
        f"{scope_text}</div>",
        unsafe_allow_html=True,
    )

    per_symbol = best_candidate.get("per_symbol", [])
    if per_symbol:
        labels = [symbol_kr(str(row.get("symbol", ""))) for row in per_symbol]
        returns = [float(row.get("return_pct", 0.0)) for row in per_symbol]
        sharpes = [float(row.get("sharpe", 0.0)) for row in per_symbol]
        trades = [int(row.get("trade_count", 0)) for row in per_symbol]

        chart = go.Figure()
        chart.add_trace(
            go.Bar(
                name="Return %",
                x=labels,
                y=returns,
                marker_color=COLORS["green"],
                hovertemplate="%{x}<br>Return %{y:+.2f}%<extra></extra>",
            )
        )
        chart.add_trace(
            go.Bar(
                name="Sharpe",
                x=labels,
                y=sharpes,
                marker_color=COLORS["blue"],
                hovertemplate="%{x}<br>Sharpe %{y:.2f}<extra></extra>",
            )
        )
        chart.update_layout(
            **chart_layout(title="Funding-rate best candidate per-symbol", height=360),
            barmode="group",
        )
        st.plotly_chart(chart, width="stretch")

        left_col, right_col = st.columns([1.05, 0.95])
        with left_col:
            st.markdown("#### 심볼별 성능")
            st.dataframe(
                [
                    {
                        "심볼": label,
                        "Return": f"{returns[index]:+.2f}%",
                        "Sharpe": f"{sharpes[index]:.2f}",
                        "Trades": trades[index],
                        "Win Rate": f"{float(per_symbol[index].get('win_rate_pct', 0.0)):.1f}%",
                        "Profit Factor": (
                            f"{float(per_symbol[index].get('profit_factor', 0.0)):.2f}"
                        ),
                    }
                    for index, label in enumerate(labels)
                ],
                width="stretch",
                hide_index=True,
            )
        with right_col:
            st.markdown("#### Best Candidate 파라미터")
            st.code(
                json.dumps(
                    {
                        "strategy_params": best_candidate.get("strategy_params", {}),
                        "risk_params": best_candidate.get("risk_params", {}),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                language="json",
            )

    st.markdown("#### Top Research Candidates")
    st.dataframe(
        [
            {
                "Rank": index + 1,
                "Avg Return": f"{float(candidate.get('avg_return_pct', 0.0)):+.3f}%",
                "Avg Sharpe": f"{float(candidate.get('avg_sharpe', 0.0)):.2f}",
                "Max MDD": f"{float(candidate.get('max_mdd_pct', 0.0)):.2f}%",
                "Trades": int(candidate.get("trade_count", 0)),
                "Score": f"{float(candidate.get('score', 0.0)):.3f}",
            }
            for index, candidate in enumerate(research.get("phase1_top5", []))
        ],
        width="stretch",
        hide_index=True,
    )

    review_markdown = research.get("review_markdown")
    if review_markdown:
        with st.expander("배포 리뷰 원문"):
            st.markdown(review_markdown)


def _render_reports(
    *,
    daily_report: dict[str, Any] | None,
    weekly_report: dict[str, Any] | None,
    operator_report: str | None,
    pnl_report: dict[str, Any] | None,
) -> None:
    _render_report_digest(daily_report=daily_report, weekly_report=weekly_report)

    if pnl_report is not None:
        st.markdown("#### P&L Snapshot")
        metric_columns = st.columns(5)
        metric_columns[0].metric("구간", str(pnl_report.get("period", "-")).upper())
        metric_columns[1].metric(
            "포트폴리오 수익률",
            f"{float(pnl_report.get('portfolio_return_pct', 0.0)):+.2f}%",
        )
        metric_columns[2].metric(
            "Sharpe",
            f"{float(pnl_report.get('portfolio_sharpe', 0.0)):.2f}",
        )
        metric_columns[3].metric(
            "MDD",
            f"{float(pnl_report.get('portfolio_mdd', 0.0)) * 100:.2f}%",
        )
        metric_columns[4].metric(
            "총 거래",
            f"{int(pnl_report.get('total_trades', 0) or 0)}",
            _format_timestamp(str(pnl_report.get("generated_at", ""))),
        )

    strategy_rows = []
    for report in (daily_report, weekly_report):
        if report is None:
            continue
        strategies = report.get("strategies", [])
        if not isinstance(strategies, list):
            continue
        for strategy in strategies:
            if not isinstance(strategy, dict):
                continue
            strategy_rows.append(
                {
                    "리포트": "일일" if report.get("period") == "daily" else "주간",
                    "전략": strategy_kr(str(strategy.get("strategy_type", ""))),
                    "지갑": str(strategy.get("wallet_name", "")),
                    "Signals": int(strategy.get("total_signals", 0) or 0),
                    "Executed": int(strategy.get("trades_executed", 0) or 0),
                    "Win Rate": f"{float(strategy.get('win_rate', 0.0) or 0.0) * 100:.1f}%",
                    "Avg Conf": f"{float(strategy.get('avg_confidence', 0.0) or 0.0) * 100:.0f}%",
                }
            )

    if strategy_rows:
        st.markdown("#### 전략별 자동 리포트 집계")
        st.dataframe(strategy_rows[:20], width="stretch", hide_index=True)

    if operator_report:
        with st.expander("Operator Report 원문"):
            st.markdown(operator_report)


def _render_signals(history: dict[str, Any]) -> None:
    rows = history["rows"]
    if not rows:
        _empty("최근 시그널이 없습니다.")
        return

    counts = history["action_counts"]
    columns = st.columns(5)
    columns[0].metric("전체", f"{history['total']}")
    columns[1].metric("매수", f"{counts['buy']}")
    columns[2].metric("매도", f"{counts['sell']}")
    columns[3].metric("관망", f"{counts['hold']}")
    columns[4].metric("고신뢰 시그널", f"{history['high_confidence_count']}")

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    action_options = ["buy", "sell", "hold", "risk"]
    actions = filter_col1.multiselect("액션", action_options, default=action_options)
    wallet_options = sorted({row["display_name"] for row in rows})
    default_wallets = wallet_options[: min(6, len(wallet_options))] or wallet_options
    selected_wallets = filter_col2.multiselect(
        "지갑",
        wallet_options,
        default=default_wallets,
    )
    regime_options = sorted({row["regime_label"] for row in rows if row["regime_label"]})
    selected_regimes = filter_col3.multiselect("레짐", regime_options, default=regime_options)
    high_conf_only = st.checkbox("신뢰도 70% 이상만", value=False)

    filtered_rows = []
    for row in rows:
        if row["action"] not in actions:
            continue
        if selected_wallets and row["display_name"] not in selected_wallets:
            continue
        if selected_regimes and row["regime_label"] and row["regime_label"] not in selected_regimes:
            continue
        if high_conf_only and row["confidence"] < 0.7:
            continue
        filtered_rows.append(row)

    st.markdown("#### 알림 스포트라이트")
    spotlight = [
        {
            "시간": row["timestamp"][:19] if row["timestamp"] else "-",
            "지갑": row["display_name"],
            "액션": row["action"],
            "심볼": row["symbol_display"],
            "이유": row["reason"],
            "상태": row["order_status"] or row["verdict_status"] or "-",
        }
        for row in history["alert_rows"][:20]
    ]
    st.dataframe(spotlight, width="stretch", hide_index=True)

    chart = go.Figure()
    chart.add_trace(
        go.Bar(
            name="매수",
            x=list(history["wallet_counts"].keys()),
            y=[
                sum(
                    1
                    for row in filtered_rows
                    if row["display_name"] == wallet and row["action"] == "buy"
                )
                for wallet in history["wallet_counts"].keys()
            ],
            marker_color=COLORS["green"],
        )
    )
    chart.add_trace(
        go.Bar(
            name="매도",
            x=list(history["wallet_counts"].keys()),
            y=[
                sum(
                    1
                    for row in filtered_rows
                    if row["display_name"] == wallet and row["action"] == "sell"
                )
                for wallet in history["wallet_counts"].keys()
            ],
            marker_color=COLORS["red"],
        )
    )
    chart.add_trace(
        go.Bar(
            name="관망",
            x=list(history["wallet_counts"].keys()),
            y=[
                sum(
                    1
                    for row in filtered_rows
                    if row["display_name"] == wallet and row["action"] == "hold"
                )
                for wallet in history["wallet_counts"].keys()
            ],
            marker_color=COLORS["muted"],
        )
    )
    chart.update_layout(**chart_layout(title="지갑별 시그널 히스토리", height=320), barmode="stack")
    st.plotly_chart(chart, width="stretch")

    st.markdown(f"#### 시그널 히스토리 ({len(filtered_rows)}건)")
    st.dataframe(
        [
            {
                "시간": row["timestamp"][:19] if row["timestamp"] else "-",
                "지갑": row["display_name"],
                "액션": row["action"],
                "심볼": row["symbol_display"],
                "신뢰도": f"{row['confidence'] * 100:.0f}%",
                "이유": row["reason"],
                "레짐": row["regime_label"],
                "주문상태": row["order_status"] or "-",
                "판정": row["verdict_status"] or "-",
            }
            for row in filtered_rows[:120]
        ],
        width="stretch",
        hide_index=True,
    )


def _render_regime_panel(regime_data: dict[str, Any]) -> None:
    """Render dedicated regime status panel with confidence bars and F&G gauge."""
    if not regime_data.get("available"):
        _empty("매크로 레짐 데이터를 사용할 수 없습니다. macro-intelligence API를 확인하세요.")
        return

    # Weekend badge
    weekend_html = ""
    if regime_data.get("is_weekend"):
        weekend_html = ' <span class="status-badge status-warn">주말 전략 활성</span>'

    alignment = regime_data.get("alignment", "unknown")
    align_cls = "status-ok" if alignment == "aligned" else "status-warn"
    align_label = "정렬" if alignment == "aligned" else "혼합"

    st.markdown(
        f'<span class="status-badge {align_cls}">{align_label}</span> '
        f'<strong>{regime_data["overall_regime_label"]}</strong> '
        f'({regime_data["overall_confidence"] * 100:.0f}%)'
        f"{weekend_html}",
        unsafe_allow_html=True,
    )

    # Layer confidence bar chart
    layers = regime_data.get("layers", [])
    if layers:
        layer_names = [layer["name"] for layer in layers]
        layer_confidences = [float(layer["confidence"]) * 100 for layer in layers]
        layer_labels = [layer["label"] for layer in layers]
        layer_colors = [
            COLORS["green"] if layer["regime"] in ("expansionary", "risk_on") else
            COLORS["yellow"] if layer["regime"] in ("neutral",) else
            COLORS["red"]
            for layer in layers
        ]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=layer_names,
            y=layer_confidences,
            text=[
                f"{label}<br>{conf:.0f}%"
                for label, conf in zip(layer_labels, layer_confidences, strict=False)
            ],
            textposition="inside",
            marker_color=layer_colors,
            hovertemplate="%{x}: %{text}<extra></extra>",
        ))
        fig.update_layout(
            **chart_layout(title="레짐 레이어별 신뢰도", height=220),
            yaxis={"range": [0, 100], "title": "신뢰도 (%)"},
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")

    # Position multiplier
    multiplier = regime_data.get("position_multiplier", 1.0)
    mult_color = (
        COLORS["green"] if multiplier >= 1.2 else
        COLORS["yellow"] if multiplier >= 0.8 else
        COLORS["red"]
    )
    st.markdown(
        f'<div class="dashboard-panel">'
        f'<strong>포지션 배율</strong> '
        f'<span style="color:{mult_color};font-weight:700;font-size:1.3rem;">'
        f'{multiplier:.2f}x</span><br>'
        f'<span style="color:var(--text-muted);font-size:0.85rem;">'
        f'{" · ".join(regime_data.get("multiplier_reasons", []))}'
        f'</span></div>',
        unsafe_allow_html=True,
    )

    # Crypto metrics row
    metrics_col = st.columns(3)
    if regime_data.get("btc_dominance") is not None:
        metrics_col[0].metric("BTC Dominance", f"{float(regime_data['btc_dominance']):.1f}%")
    if regime_data.get("kimchi_premium") is not None:
        metrics_col[1].metric("Kimchi Premium", f"{float(regime_data['kimchi_premium']):.2f}%")
    if regime_data.get("fear_greed_index") is not None:
        metrics_col[2].metric(
            "Fear & Greed",
            f"{regime_data['fear_greed_index']}",
            regime_data.get("fear_greed_label", ""),
        )


def _render_fear_greed_gauge(regime_data: dict[str, Any]) -> None:
    """Render Fear & Greed index as a Plotly gauge with 5 color zones."""
    fg_value = regime_data.get("fear_greed_index")
    if fg_value is None:
        _empty("Fear & Greed 인덱스 데이터가 없습니다.")
        return

    fg_label = regime_data.get("fear_greed_label", "")

    steps = [
        {"range": [low, high], "color": color}
        for low, high, _label, color in FEAR_GREED_ZONES
    ]

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=fg_value,
        number={"font": {"size": 48, "color": "#edf5fb"}},
        title={"text": f"Fear & Greed · {fg_label}", "font": {"size": 14, "color": "#9fb4c7"}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#3a5068"},
            "bar": {"color": "#edf5fb", "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": steps,
            "threshold": {
                "line": {"color": "#edf5fb", "width": 3},
                "thickness": 0.8,
                "value": fg_value,
            },
        },
    ))
    fig.update_layout(
        height=240,
        margin={"l": 20, "r": 20, "t": 40, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "'Noto Sans KR', sans-serif"},
    )
    st.plotly_chart(fig, width="stretch")


def _render_signal_monitor(monitor: dict[str, Any]) -> None:
    """Render real-time signal monitor tab."""
    wallet_signals = monitor["wallet_signals"]
    if not wallet_signals:
        _empty("시그널 데이터가 없습니다. 데몬이 실행 중인지 확인하세요.")
        return

    # Summary metrics
    metric_cols = st.columns(4)
    metric_cols[0].metric("활성 지갑", f"{len(wallet_signals)}")
    metric_cols[1].metric("매수 시그널", f"{monitor['active_buy_count']}", delta_color="normal")
    metric_cols[2].metric("매도 시그널", f"{monitor['active_sell_count']}", delta_color="normal")
    metric_cols[3].metric("관망", f"{monitor['active_hold_count']}")

    # Per-wallet latest signal table
    st.markdown("#### 전략별 최신 시그널")
    signal_rows = []
    for sig in wallet_signals:
        action = sig["action"]
        signal_rows.append({
            "지갑": sig["display_name"],
            "심볼": sig["symbol_display"],
            "액션": action.upper(),
            "신뢰도": f"{sig['confidence'] * 100:.0f}%",
            "이유": sig["reason"][:60] if sig["reason"] else "-",
            "레짐": sig["regime_label"] or "-",
            "가격": f"₩{sig['latest_price']:,.0f}" if sig["latest_price"] else "-",
            "시간": sig["timestamp"][:19] if sig["timestamp"] else "-",
        })
    st.dataframe(signal_rows, width="stretch", hide_index=True)

    # Two columns: heatmap + timeline
    left_col, right_col = st.columns([1.1, 0.9])

    with left_col:
        # Strategy x Regime heatmap
        strategies = monitor["strategies"]
        regimes = monitor["regimes"]
        heatmap_z = monitor["heatmap_z"]
        if strategies and regimes and heatmap_z:
            st.markdown("#### 전략 × 레짐 시그널 매트릭스")
            fig = go.Figure(data=[go.Heatmap(
                x=regimes,
                y=strategies,
                z=heatmap_z,
                colorscale=[
                    [0.0, "rgba(15,29,42,0.85)"],
                    [0.5, "rgba(119,184,255,0.5)"],
                    [1.0, "rgba(97,242,162,0.95)"],
                ],
                hovertemplate="전략: %{y}<br>레짐: %{x}<br>시그널: %{z}<extra></extra>",
            )])
            fig.update_layout(
                **chart_layout(title="", height=max(200, len(strategies) * 36 + 60)),
                xaxis_title="레짐",
                yaxis_title="",
            )
            st.plotly_chart(fig, width="stretch")
        else:
            _empty("시그널 매트릭스 데이터가 부족합니다.")

    with right_col:
        # Signal timeline
        timeline = monitor["timeline"]
        if timeline:
            st.markdown("#### 시그널 타임라인")
            fig = go.Figure()
            buy_tl = [t for t in timeline if t["action"] == "buy"]
            sell_tl = [t for t in timeline if t["action"] == "sell"]

            for label, data, color in [
                ("매수", buy_tl, COLORS["green"]),
                ("매도", sell_tl, COLORS["red"]),
            ]:
                if data:
                    fig.add_trace(go.Scatter(
                        x=[t["timestamp"][:19] for t in data],
                        y=[t["confidence"] for t in data],
                        mode="markers",
                        name=label,
                        marker={"size": 10, "color": color},
                        text=[f"{t['display_name']}<br>{t['symbol_display']}" for t in data],
                        hovertemplate="%{text}<br>신뢰도: %{y:.0%}<br>%{x}<extra></extra>",
                    ))
            fig.update_layout(
                **chart_layout(title="", height=280, yaxis_title="신뢰도"),
                yaxis={"range": [0, 1]},
            )
            st.plotly_chart(fig, width="stretch")
        else:
            _empty("최근 매수/매도 시그널이 없습니다.")


st.markdown("## 크립토 트레이더")

with st.spinner("데이터 로딩 중..."):
    checkpoint = load_checkpoint()
    heartbeat = load_daemon_heartbeat()
    freshness = load_data_freshness()
    analytics = load_wallet_analytics()
    risk = load_risk_overview()
    macro = load_macro_summary()
    regime_panel = load_regime_panel_data()
    signal_monitor = load_signal_monitor_data()
    edge_analysis = load_edge_analysis()
    research = load_momentum_pullback_research()
    funding_rate_research = load_funding_rate_research()
    signal_history = load_signal_history(limit=400)
    daily_performance = load_daily_performance()
    daily_report = load_daily_report()
    weekly_report = load_weekly_report()
    operator_report = load_operator_report()
    pnl_report = load_pnl_report()
    promotion_gate = load_promotion_gate()
    health = load_health()

_render_status_row(heartbeat, freshness)

(
    tab_overview,
    tab_portfolio_risk,
    tab_signal_monitor,
    tab_edge_analysis,
    tab_reports,
    tab_strategy_research,
    tab_funding_rate_research,
    tab_alerts_history,
) = st.tabs(
    [
        "개요",
        "포트폴리오·리스크",
        "시그널 모니터",
        "엣지분석",
        "자동리포트",
        "전략연구",
        "펀딩레이트 연구",
        "알림·히스토리",
    ]
)

with tab_overview:
    _render_overview(
        analytics=analytics,
        daily_performance=daily_performance,
        daily_report=daily_report,
        weekly_report=weekly_report,
        risk=risk,
        macro=macro,
        regime_panel=regime_panel,
        promotion_gate=promotion_gate,
    )

with tab_portfolio_risk:
    _render_portfolio_and_risk(analytics=analytics, risk=risk, health=health)

with tab_signal_monitor:
    _render_signal_monitor(signal_monitor)

with tab_edge_analysis:
    _render_edge_analysis(edge_analysis)

with tab_reports:
    _render_reports(
        daily_report=daily_report,
        weekly_report=weekly_report,
        operator_report=operator_report,
        pnl_report=pnl_report,
    )

with tab_strategy_research:
    _render_research(research)

with tab_funding_rate_research:
    _render_funding_rate_research(funding_rate_research)

with tab_alerts_history:
    _render_signals(signal_history)
