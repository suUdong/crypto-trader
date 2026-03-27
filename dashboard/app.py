"""Unified crypto-trader dashboard with 4 responsive tabs."""

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

from dashboard.data import (  # noqa: E402
    load_checkpoint,
    load_daemon_heartbeat,
    load_daily_performance,
    load_data_freshness,
    load_health,
    load_macro_summary,
    load_momentum_pullback_research,
    load_promotion_gate,
    load_risk_overview,
    load_signal_history,
    load_wallet_analytics,
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
    st.plotly_chart(figure, use_container_width=True)


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
    st.plotly_chart(scatter, use_container_width=True)


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
            latest_price = wallet["latest_price"] or position["entry_price"]
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
    risk: dict[str, Any],
    macro: dict[str, Any] | None,
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
                <h2>멀티 월렛 상태를 4개 탭으로 압축한 운영 대시보드</h2>
                <p>
                    지갑별 실시간 P&amp;L, Sharpe/MDD/수익률, 매크로 레짐, 리스크 축소 상태,
                    전략 연구와 시그널 히스토리를 한 화면 흐름으로 정리했습니다.
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
        if macro is None:
            _empty("macro-intelligence 또는 regime-report 데이터가 없습니다.")
        else:
            alignment_level = "ok" if macro.get("alignment") == "aligned" else "warn"
            alignment_label = "정렬" if macro.get("alignment") == "aligned" else "혼합"
            summary_lines = [
                f'<span class="status-badge {_status_class(alignment_level)}">'
                f"{alignment_label}</span>"
            ]
            if macro.get("source_available"):
                summary_lines.append(
                    f"<strong>{macro.get('overall_regime_label', '-')}</strong> "
                    f"({float(macro.get('overall_confidence', 0.0)) * 100:.0f}%)"
                )
            if macro.get("local_regime_label"):
                summary_lines.append(f"로컬: {macro.get('local_regime_label')}")
            st.markdown(" · ".join(summary_lines), unsafe_allow_html=True)

            layers = macro.get("layers", [])
            for layer in layers:
                st.markdown(
                    f'<div class="dashboard-panel"><strong>{layer["name"]}</strong> '
                    f"{layer['label']} · 신뢰도 {layer['confidence'] * 100:.0f}%</div>",
                    unsafe_allow_html=True,
                )
            if macro.get("btc_dominance") is not None:
                st.metric("BTC Dominance", f"{float(macro['btc_dominance']):.2f}%")
            if macro.get("kimchi_premium") is not None:
                st.metric("Kimchi Premium", f"{float(macro['kimchi_premium']):.2f}%")
            if macro.get("fear_greed_index") is not None:
                st.metric("Fear & Greed", f"{int(macro['fear_greed_index'])}")

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
    st.dataframe(leaderboard_rows, use_container_width=True, hide_index=True)


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
        st.dataframe(risk_rows, use_container_width=True, hide_index=True)

    st.markdown("#### 현재 포지션")
    _render_open_positions(wallets)


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
    st.plotly_chart(chart, use_container_width=True)

    compare_col, symbol_col = st.columns([1.05, 0.95])
    with compare_col:
        st.markdown("#### 전략 비교")
        st.dataframe(compare_rows, use_container_width=True, hide_index=True)
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
        st.plotly_chart(bubble, use_container_width=True)
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
            use_container_width=True,
            hide_index=True,
        )


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
    st.dataframe(spotlight, use_container_width=True, hide_index=True)

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
    st.plotly_chart(chart, use_container_width=True)

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
        use_container_width=True,
        hide_index=True,
    )


st.markdown("## 크립토 트레이더")

with st.spinner("데이터 로딩 중..."):
    checkpoint = load_checkpoint()
    heartbeat = load_daemon_heartbeat()
    freshness = load_data_freshness()
    analytics = load_wallet_analytics()
    risk = load_risk_overview()
    macro = load_macro_summary()
    research = load_momentum_pullback_research()
    signal_history = load_signal_history(limit=400)
    daily_performance = load_daily_performance()
    promotion_gate = load_promotion_gate()
    health = load_health()

_render_status_row(heartbeat, freshness)

(
    tab_overview,
    tab_portfolio_risk,
    tab_strategy_research,
    tab_alerts_history,
) = st.tabs(
    [
        "개요",
        "포트폴리오·리스크",
        "전략연구",
        "알림·히스토리",
    ]
)

with tab_overview:
    _render_overview(
        analytics=analytics,
        daily_performance=daily_performance,
        risk=risk,
        macro=macro,
        promotion_gate=promotion_gate,
    )

with tab_portfolio_risk:
    _render_portfolio_and_risk(analytics=analytics, risk=risk, health=health)

with tab_strategy_research:
    _render_research(research)

with tab_alerts_history:
    _render_signals(signal_history)
