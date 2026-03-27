"""크립토 트레이더 대시보드 — 모바일 최적화 Streamlit 앱."""

from __future__ import annotations

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

from dashboard.auth import check_auth, render_login  # noqa: E402
from dashboard.data import (  # noqa: E402
    SYMBOL_KR,
    load_backtest_baseline,
    load_checkpoint,
    load_daemon_heartbeat,
    load_daily_memo,
    load_daily_performance,
    load_data_freshness,
    load_drift_report,
    load_health,
    load_kill_switch,
    load_paper_trades,
    load_pnl_report,
    load_positions,
    load_promotion_gate,
    load_regime_report,
    load_signal_summary,
    load_strategy_runs,
    regime_kr,
    strategy_kr,
    symbol_kr,
)
from dashboard.styles import (  # noqa: E402
    COLORS,
    PALETTE,
    chart_layout,
    inject_css,
    pnl_color,
    pnl_colors,
)

_UTC = timezone.utc  # noqa: UP017
_KST = timezone(timedelta(hours=9))

# ── 페이지 설정 ───────────────────────────────────────────
st.set_page_config(
    page_title="크립토 트레이더",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
)
inject_css()

# ── 인증 ──────────────────────────────────────────────────
if not check_auth():
    render_login()
    st.stop()

# ── 자동 새로고침 (60초) ──────────────────────────────────
st.markdown(
    '<meta http-equiv="refresh" content="60">',
    unsafe_allow_html=True,
)

# ── 헤더 + 로그아웃 ──────────────────────────────────────
col_title, col_logout = st.columns([5, 1])
with col_title:
    st.markdown("## 크립토 트레이더")
with col_logout:
    if st.button("로그아웃", key="logout_btn"):
        st.session_state["dashboard_authenticated"] = False
        st.rerun()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 글로벌 데이터 로딩 — 한 번만 로드하고 전체 탭에서 공유
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with st.spinner("데이터 로딩 중..."):
    try:
        _checkpoint = load_checkpoint()
    except Exception:
        _checkpoint = None

    try:
        _heartbeat = load_daemon_heartbeat()
    except Exception:
        _heartbeat = None

    try:
        _strategy_runs = load_strategy_runs()
    except Exception:
        _strategy_runs = []

    try:
        _paper_trades = load_paper_trades()
    except Exception:
        _paper_trades = []

    try:
        _kill_switch = load_kill_switch()
    except Exception:
        _kill_switch = None

    _freshness = load_data_freshness()

# ── 데이터 신선도 표시 ────────────────────────────────────
_cp_info = _freshness["files"].get("runtime-checkpoint.json", {})
if _cp_info.get("exists"):
    _cp_age = int(_cp_info.get("age_seconds", 0))
    if _cp_age < 120:
        _fresh_badge = "status-ok"
        _fresh_text = "실시간"
    elif _cp_age < 300:
        _fresh_badge = "status-warn"
        _fresh_text = f"{_cp_age}초 전"
    else:
        _fresh_badge = "status-fail"
        _fresh_text = f"{_cp_age // 60}분 전"
else:
    _fresh_badge = "status-fail"
    _fresh_text = "데이터 없음"

# ── 데몬 상태 (전체 공통) ─────────────────────────────────
if _heartbeat is None:
    st.markdown(
        '<span class="status-badge status-fail">데몬 중지</span> '
        f'<span class="status-badge {_fresh_badge}">{_fresh_text}</span>',
        unsafe_allow_html=True,
    )
else:
    hb_time_str = _heartbeat.get("last_heartbeat", "")
    poll_interval = _heartbeat.get("poll_interval_seconds", 60)
    stale_threshold = poll_interval * 2
    try:
        hb_time = datetime.fromisoformat(hb_time_str)
        age_seconds = (datetime.now(_UTC) - hb_time).total_seconds()
    except (ValueError, TypeError):
        age_seconds = float("inf")

    if age_seconds <= stale_threshold:
        badge_cls, badge_text = "status-ok", "데몬 정상"
    else:
        badge_cls, badge_text = "status-warn", "데몬 지연"

    uptime = _heartbeat.get("uptime_seconds", 0)
    if uptime >= 3600:
        uptime_str = f"{int(uptime // 3600)}시간 {int((uptime % 3600) // 60)}분"
    else:
        uptime_str = f"{int(uptime // 60)}분"
    pid = _heartbeat.get("pid", "?")
    iteration = _heartbeat.get("iteration", 0)
    symbols_list = _heartbeat.get("symbols", [])
    symbols_text = ", ".join(symbol_kr(s) for s in symbols_list) if symbols_list else ""

    st.markdown(
        f'<span class="status-badge {badge_cls}">{badge_text}</span> '
        f'<span class="status-badge {_fresh_badge}">데이터 {_fresh_text}</span> '
        f"PID {pid} · 반복 #{iteration} · 가동 {uptime_str} · "
        f"마지막 {int(age_seconds)}초 전"
        + (f"<br>종목: {symbols_text}" if symbols_text else ""),
        unsafe_allow_html=True,
    )

# ── 탭 내비게이션 ─────────────────────────────────────────
tab_trading, tab_wallets, tab_vspike, tab_pnl_chart, tab_corr, tab_killswitch, tab_signals, tab_sig_analysis, tab_trades, tab_regime, tab_operator, tab_health, tab_perf = st.tabs(
    ["현황", "전략", "거래량급등", "포지션PnL", "상관관계", "킬스위치", "시그널", "시그널분석", "체결현황", "국면", "운영", "시스템", "성과"]
)


# ── 헬퍼 ─────────────────────────────────────────────────
def _empty(msg: str) -> None:
    """Render a consistent empty-state message."""
    st.info(msg)


def _get_wallet_states() -> dict[str, Any]:
    """Get wallet states from the live checkpoint (primary source)."""
    if _checkpoint is None:
        return {}
    return _checkpoint.get("wallet_states", {})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 1: 현황 — 페이퍼 트레이딩 개요
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_trading:
    if _checkpoint is None:
        _empty("런타임 체크포인트 데이터가 없습니다. 데몬이 실행 중인지 확인하세요.")
    else:
        # 헬스 표시기 — checkpoint 기반으로 판단
        try:
            health = load_health()
        except Exception:
            health = None

        if health:
            is_healthy = health.get("success", False)
            last_signal = health.get("last_signal", "N/A")
            badge_cls = "status-ok" if is_healthy else "status-fail"
            badge_text = "정상" if is_healthy else "오류"
            st.markdown(
                f'<span class="status-badge {badge_cls}">{badge_text}</span> '
                f"마지막 시그널: {last_signal}",
                unsafe_allow_html=True,
            )

        # 킬스위치 & 프로모션 게이트 상태
        ks_col, pg_col = st.columns(2)
        with ks_col:
            if _kill_switch is None:
                st.markdown('<span class="status-badge status-warn">킬스위치 ?</span>', unsafe_allow_html=True)
            elif _kill_switch.get("triggered"):
                st.markdown(
                    f'<span class="status-badge status-fail">킬스위치 발동</span> {_kill_switch.get("trigger_reason", "")}',
                    unsafe_allow_html=True,
                )
            else:
                dd = _kill_switch.get("portfolio_drawdown_pct", 0) * 100
                st.markdown(
                    f'<span class="status-badge status-ok">킬스위치 정상</span> MDD {dd:.3f}%',
                    unsafe_allow_html=True,
                )
        with pg_col:
            try:
                pg = load_promotion_gate()
            except Exception:
                pg = None
            if pg is None:
                st.markdown('<span class="status-badge status-warn">프로모션 ?</span>', unsafe_allow_html=True)
            else:
                pg_status = pg.get("status", "unknown")
                if pg_status == "candidate_for_promotion":
                    badge = "status-ok"
                    label = "프로모션 준비"
                elif pg_status == "stay_in_paper":
                    badge = "status-warn"
                    label = "페이퍼 유지"
                else:
                    badge = "status-fail"
                    label = "프로모션 불가"
                st.markdown(f'<span class="status-badge {badge}">{label}</span>', unsafe_allow_html=True)

        # 체크포인트 시간
        gen_at = _checkpoint.get("generated_at", "")
        if gen_at:
            st.caption(f"업데이트: {gen_at[:19]}")

        # 반복 & 종목
        iteration = _checkpoint.get("iteration", 0)
        symbols = _checkpoint.get("symbols", [])
        symbols_display = ", ".join(symbol_kr(s) for s in symbols)
        st.markdown(f"**반복 #{iteration}** · {symbols_display}")

        # 전략별 지갑 요약 카드
        wallet_states = _get_wallet_states()
        if not wallet_states:
            _empty("지갑 정보를 불러올 수 없습니다.")
        else:
            cols = st.columns(min(len(wallet_states), 3))
            for i, (name, state) in enumerate(wallet_states.items()):
                with cols[i % len(cols)]:
                    display_name = strategy_kr(name)
                    equity = state.get("equity", 0)
                    pnl = state.get("realized_pnl", 0)
                    trades = state.get("trade_count", 0)
                    initial = state.get("initial_capital", equity)
                    return_pct = ((equity - initial) / initial * 100) if initial > 0 else 0

                    st.metric(
                        display_name,
                        f"₩{equity:,.0f}",
                        f"{return_pct:+.2f}% (PnL ₩{pnl:,.0f})",
                    )
                    st.caption(f"거래 {trades}건 · 포지션 {state.get('open_positions', 0)}개")

        # 보유 포지션 — checkpoint에서 직접 추출
        has_positions = False
        for wname, wstate in wallet_states.items():
            pos_data = wstate.get("positions", {})
            if isinstance(pos_data, dict) and pos_data:
                if not has_positions:
                    st.markdown("#### 보유 포지션")
                    has_positions = True
                for sym, pos in pos_data.items():
                    entry_price = pos.get("entry_price", 0)
                    quantity = pos.get("quantity", 0)
                    st.markdown(
                        f'<div class="position-card">'
                        f"<strong>{symbol_kr(sym)}</strong> · {strategy_kr(wname)}<br>"
                        f"수량: {quantity:.8f} · "
                        f"진입가: ₩{entry_price:,.0f}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        if not has_positions:
            _empty("보유 포지션이 없습니다.")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 2: 전략비교 — 전략별 지갑 비교
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_wallets:
    wallet_states = _get_wallet_states()
    if not wallet_states:
        _empty("전략 비교 데이터가 없습니다. 데몬이 실행 중인지 확인하세요.")
    else:
        names = []
        equities = []
        pnls = []
        trade_counts = []
        return_pcts = []
        for name, state in wallet_states.items():
            display = strategy_kr(name)
            names.append(display)
            eq = state.get("equity", 0)
            equities.append(eq)
            pnls.append(state.get("realized_pnl", 0))
            trade_counts.append(state.get("trade_count", 0))
            initial = state.get("initial_capital", eq)
            ret = ((eq - initial) / initial * 100) if initial > 0 else 0
            return_pcts.append(ret)

        # 전략별 비교 테이블
        st.markdown("#### 전략별 성과 비교")
        for i, n in enumerate(names):
            c1, c2, c3 = st.columns(3)
            c1.metric(n, f"₩{equities[i]:,.0f}", f"{return_pcts[i]:+.2f}%")
            c2.metric("실현 손익", f"₩{pnls[i]:,.0f}")
            c3.metric("거래 수", f"{trade_counts[i]}")

        # 수익률 비교 차트
        fig_ret = go.Figure()
        fig_ret.add_trace(go.Bar(
            name="수익률(%)",
            x=names,
            y=return_pcts,
            marker_color=pnl_colors(return_pcts),
            text=[f"{r:+.2f}%" for r in return_pcts],
            textposition="outside",
        ))
        fig_ret.update_layout(**chart_layout(title="전략별 수익률", yaxis_title="수익률 (%)"))
        st.plotly_chart(fig_ret, use_container_width=True)

        # 자본금 vs PnL 비교 차트
        fig = go.Figure()
        fig.add_trace(go.Bar(name="자본금", x=names, y=equities, marker_color=COLORS["blue"]))
        fig.add_trace(go.Bar(name="실현 손익", x=names, y=pnls, marker_color=COLORS["green"]))
        fig.update_layout(**chart_layout(title="전략별 자본금 / 손익"), barmode="group")
        st.plotly_chart(fig, use_container_width=True)

        # 거래 수 차트
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(name="거래 수", x=names, y=trade_counts, marker_color=COLORS["yellow"]))
        fig2.update_layout(**chart_layout(title="전략별 거래 수", show_legend=False))
        st.plotly_chart(fig2, use_container_width=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 3: 거래량급등 — VolumeSpikeStrategy 전용
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_vspike:
    # Filter volume_spike data from shared data
    vs_signals = [r for r in _strategy_runs if "volume_spike" in r.get("wallet_name", "")]
    vs_closed = [t for t in _paper_trades if "volume_spike" in t.get("wallet", "")]

    if not vs_signals and not vs_closed:
        _empty("거래량급등 전략 데이터가 없습니다.")
    else:
        # Wallet state summary from checkpoint
        if _checkpoint:
            vs_wallets = {
                k: v for k, v in _get_wallet_states().items()
                if "volume_spike" in k
            }
            if vs_wallets:
                cols = st.columns(min(len(vs_wallets), 3))
                for i, (wname, wstate) in enumerate(vs_wallets.items()):
                    with cols[i % len(cols)]:
                        eq = wstate.get("equity", 0)
                        initial = wstate.get("initial_capital", eq)
                        ret = ((eq - initial) / initial * 100) if initial > 0 else 0
                        pnl = wstate.get("realized_pnl", 0)
                        st.metric(
                            strategy_kr(wname),
                            f"₩{eq:,.0f}",
                            f"{ret:+.2f}% (PnL ₩{pnl:,.0f})",
                        )

        # Signal action distribution
        if vs_signals:
            st.markdown("#### 시그널 분포")
            action_counts: dict[str, int] = {"buy": 0, "sell": 0, "hold": 0}
            conf_values: list[float] = []
            for s in vs_signals:
                action = s.get("signal_action", "hold")
                if action in action_counts:
                    action_counts[action] += 1
                conf_values.append(s.get("signal_confidence", 0.0))

            c1, c2, c3, c4 = st.columns(4)
            total_vs = sum(action_counts.values())
            c1.metric("총 시그널", f"{total_vs}")
            c2.metric("매수", f"{action_counts['buy']}")
            c3.metric("매도", f"{action_counts['sell']}")
            avg_conf = sum(conf_values) / len(conf_values) if conf_values else 0
            c4.metric("평균 신뢰도", f"{avg_conf:.2f}")

            # Confidence distribution histogram
            if conf_values:
                fig_conf = go.Figure()
                fig_conf.add_trace(go.Histogram(
                    x=conf_values,
                    nbinsx=20,
                    marker_color=COLORS["purple"],
                    name="신뢰도",
                ))
                fig_conf.update_layout(**chart_layout(
                    title="신뢰도 분포", height=250,
                    xaxis_title="신뢰도", yaxis_title="빈도", show_legend=False,
                ))
                st.plotly_chart(fig_conf, use_container_width=True)

        # Win rate for volume spike
        if vs_closed:
            st.markdown("#### 거래량급등 승률")
            wins = sum(1 for t in vs_closed if t.get("pnl", 0) > 0)
            total_t = len(vs_closed)
            wr = (wins / total_t * 100) if total_t > 0 else 0
            total_pnl = sum(t.get("pnl", 0) for t in vs_closed)
            avg_pnl_pct = (
                sum(t.get("pnl_pct", 0) for t in vs_closed) / total_t
                if total_t > 0 else 0
            )
            c1, c2, c3 = st.columns(3)
            c1.metric("승률", f"{wr:.1f}%", f"{wins}/{total_t}건")
            c2.metric("총 손익", f"₩{total_pnl:,.0f}")
            c3.metric("평균 수익률", f"{avg_pnl_pct:+.2f}%")

            # PnL per trade bar chart
            pnl_pcts = [t.get("pnl_pct", 0) for t in vs_closed[-30:]]
            fig_pnl = go.Figure()
            fig_pnl.add_trace(go.Bar(
                y=pnl_pcts,
                marker_color=pnl_colors(pnl_pcts),
                name="수익률",
            ))
            fig_pnl.update_layout(**chart_layout(
                title="최근 거래 수익률 (%)", height=250,
                yaxis_title="수익률 (%)", xaxis_title="거래 순서", show_legend=False,
            ))
            st.plotly_chart(fig_pnl, use_container_width=True)

        # Recent signals timeline (volume spike only)
        if vs_signals:
            st.markdown("#### 최근 시그널")
            ACTION_KR_VS = {"buy": "매수", "sell": "매도", "hold": "관망"}
            html_parts = ['<div class="signal-container">']
            for run in reversed(vs_signals[-30:]):
                ts = run.get("recorded_at", "")[:19]
                action = run.get("signal_action", "hold")
                symbol = run.get("symbol", "?")
                price = run.get("latest_price", 0)
                reason = run.get("signal_reason", "")
                confidence = run.get("signal_confidence", 0)

                action_kr = ACTION_KR_VS.get(action, action)
                if action == "buy":
                    css_cls, icon = "signal-buy", "🟢"
                elif action == "sell":
                    css_cls, icon = "signal-sell", "🔴"
                else:
                    css_cls, icon = "signal-hold", "⚪"

                conf_color = COLORS["green"] if confidence > 0.7 else COLORS["yellow"] if confidence > 0.4 else COLORS["red"]
                conf_bar = (
                    f'<span class="conf-track">'
                    f'<span class="conf-fill" style="width:{confidence*100:.0f}%;'
                    f'background:{conf_color};"></span></span>'
                )
                html_parts.append(
                    f'<div class="signal-row">'
                    f'{icon} <span class="{css_cls}">{action_kr}</span> '
                    f"<strong>{symbol_kr(symbol)}</strong> ₩{price:,.0f} · {reason} · "
                    f"{confidence:.0%} {conf_bar}"
                    f'<br><span style="color:var(--text-secondary);font-size:0.8125rem">'
                    f"{ts}</span>"
                    f"</div>"
                )
            html_parts.append("</div>")
            st.markdown("".join(html_parts), unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 4: 포지션PnL — 전략별 실시간 포지션 손익 차트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_pnl_chart:
    pnl_wallets = _get_wallet_states()
    if not pnl_wallets:
        _empty("포지션 데이터가 없습니다. 데몬이 실행 중인지 확인하세요.")
    else:
        # Per-strategy equity & unrealized PnL
        st.markdown("#### 전략별 포지션 손익")
        strat_names: list[str] = []
        unrealized_pnls: list[float] = []
        realized_pnls: list[float] = []
        equities_pnl: list[float] = []
        return_pcts_pnl: list[float] = []

        for wname, wstate in pnl_wallets.items():
            strat_names.append(strategy_kr(wname))
            eq = wstate.get("equity", 0)
            initial = wstate.get("initial_capital", eq)
            realized = wstate.get("realized_pnl", 0)
            unrealized = eq - initial - realized
            unrealized_pnls.append(unrealized)
            realized_pnls.append(realized)
            equities_pnl.append(eq)
            ret = ((eq - initial) / initial * 100) if initial > 0 else 0
            return_pcts_pnl.append(ret)

        # Stacked bar: realized + unrealized PnL
        fig_pnl_stacked = go.Figure()
        fig_pnl_stacked.add_trace(go.Bar(
            name="실현 손익",
            x=strat_names,
            y=realized_pnls,
            marker_color=COLORS["green"],
        ))
        fig_pnl_stacked.add_trace(go.Bar(
            name="미실현 손익",
            x=strat_names,
            y=unrealized_pnls,
            marker_color=COLORS["blue"],
        ))
        fig_pnl_stacked.update_layout(
            **chart_layout(title="전략별 실현/미실현 손익", height=300, yaxis_title="손익 (KRW)"),
            barmode="relative",
        )
        st.plotly_chart(fig_pnl_stacked, use_container_width=True)

        # Per-wallet position detail cards
        st.markdown("#### 보유 포지션 상세")
        has_open = False
        for wname, wstate in pnl_wallets.items():
            pos_data = wstate.get("positions", {})
            if isinstance(pos_data, dict) and pos_data:
                has_open = True
                for sym, pos in pos_data.items():
                    entry_price = pos.get("entry_price", 0)
                    quantity = pos.get("quantity", 0)
                    # Try to get latest price from strategy runs
                    latest_price = entry_price  # fallback
                    for run in reversed(_strategy_runs[-200:] if _strategy_runs else []):
                        if run.get("symbol") == sym:
                            latest_price = run.get("latest_price", entry_price)
                            break
                    unrealized = (latest_price - entry_price) * quantity
                    unrealized_pct = ((latest_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                    st.markdown(
                        f'<div class="position-card">'
                        f"<strong>{symbol_kr(sym)}</strong> · {strategy_kr(wname)}<br>"
                        f"진입가: ₩{entry_price:,.0f} · 수량: {quantity:.8f}<br>"
                        f'미실현: <span style="color:{pnl_color(unrealized)};">₩{unrealized:,.0f} ({unrealized_pct:+.2f}%)</span>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        if not has_open:
            _empty("보유 포지션이 없습니다.")

        # Return waterfall chart
        fig_waterfall = go.Figure()
        fig_waterfall.add_trace(go.Bar(
            x=strat_names,
            y=return_pcts_pnl,
            marker_color=pnl_colors(return_pcts_pnl),
            text=[f"{r:+.2f}%" for r in return_pcts_pnl],
            textposition="outside",
        ))
        fig_waterfall.update_layout(**chart_layout(
            title="전략별 총수익률", yaxis_title="수익률 (%)", show_legend=False,
        ))
        st.plotly_chart(fig_waterfall, use_container_width=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 5: 상관관계 — 클러스터 노출 매트릭스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_corr:
    corr_wallets = _get_wallet_states()
    if not corr_wallets:
        _empty("상관관계 데이터가 없습니다. 데몬이 실행 중인지 확인하세요.")
    else:
        # Build position matrix: wallet × symbol
        all_symbols: set[str] = set()
        wallet_positions: dict[str, set[str]] = {}
        for wname, wstate in corr_wallets.items():
            pos_data = wstate.get("positions", {})
            if isinstance(pos_data, dict):
                syms = set(pos_data.keys())
                if syms:
                    wallet_positions[wname] = syms
                    all_symbols.update(syms)

        # Correlation clusters
        clusters: dict[str, list[str]] = {
            "major_crypto": ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP"],
        }
        symbol_to_cluster: dict[str, str] = {}
        for cname, csyms in clusters.items():
            for s in csyms:
                symbol_to_cluster[s] = cname

        st.markdown("#### 클러스터 노출도")

        # Cluster exposure summary
        cluster_wallets: dict[str, list[str]] = {}
        for wname, syms in wallet_positions.items():
            for sym in syms:
                cl = symbol_to_cluster.get(sym, "기타")
                cluster_wallets.setdefault(cl, [])
                if wname not in cluster_wallets[cl]:
                    cluster_wallets[cl].append(wname)

        max_exposure = 6
        if cluster_wallets:
            for cname, wallets in cluster_wallets.items():
                exposure = len(wallets)
                ratio = exposure / max_exposure
                if ratio >= 0.75:
                    badge_cls = "status-fail"
                elif ratio >= 0.5:
                    badge_cls = "status-warn"
                else:
                    badge_cls = "status-ok"
                st.markdown(
                    f'<span class="status-badge {badge_cls}">'
                    f"{cname}: {exposure}/{max_exposure}</span> "
                    f"{', '.join(strategy_kr(w) for w in wallets)}",
                    unsafe_allow_html=True,
                )
        else:
            _empty("포지션이 없어 클러스터 노출이 없습니다.")

        # Position heatmap: wallets × symbols
        st.markdown("#### 포지션 매트릭스")
        sorted_wallets = sorted(corr_wallets.keys())
        sorted_symbols = sorted(all_symbols) if all_symbols else sorted(SYMBOL_KR.keys())[:8]

        if sorted_symbols:
            matrix: list[list[int]] = []
            for wname in sorted_wallets:
                row: list[int] = []
                pos_data = corr_wallets[wname].get("positions", {})
                for sym in sorted_symbols:
                    row.append(1 if isinstance(pos_data, dict) and sym in pos_data else 0)
                matrix.append(row)

            fig_heat = go.Figure(data=go.Heatmap(
                z=matrix,
                x=[symbol_kr(s) for s in sorted_symbols],
                y=[strategy_kr(w) for w in sorted_wallets],
                colorscale=[[0, COLORS["bg_dark"]], [1, COLORS["green"]]],
                showscale=False,
                hovertemplate="전략: %{y}<br>종목: %{x}<br>포지션: %{z}<extra></extra>",
            ))
            fig_heat.update_layout(**chart_layout(
                height=max(200, len(sorted_wallets) * 35 + 80), show_legend=False,
            ))
            fig_heat.update_layout(xaxis=dict(side="bottom"))
            st.plotly_chart(fig_heat, use_container_width=True)

        # Wallet-to-wallet correlation (based on shared symbol holdings)
        if len(wallet_positions) >= 2:
            st.markdown("#### 전략간 포지션 상관도")
            wp_keys = sorted(wallet_positions.keys())
            corr_matrix: list[list[float]] = []
            for w1 in wp_keys:
                row_corr: list[float] = []
                s1 = wallet_positions[w1]
                for w2 in wp_keys:
                    s2 = wallet_positions[w2]
                    union = len(s1 | s2)
                    overlap = len(s1 & s2)
                    row_corr.append(overlap / union if union > 0 else 0)
                corr_matrix.append(row_corr)

            fig_corr = go.Figure(data=go.Heatmap(
                z=corr_matrix,
                x=[strategy_kr(w) for w in wp_keys],
                y=[strategy_kr(w) for w in wp_keys],
                colorscale="RdYlGn_r",
                zmin=0, zmax=1,
                text=[[f"{v:.0%}" for v in row] for row in corr_matrix],
                texttemplate="%{text}",
                hovertemplate="%{y} ↔ %{x}: %{z:.0%}<extra></extra>",
            ))
            fig_corr.update_layout(**chart_layout(
                height=max(250, len(wp_keys) * 40 + 80), show_legend=False,
            ))
            st.plotly_chart(fig_corr, use_container_width=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 6: 킬스위치 — 리스크 게이지
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_killswitch:
    if _kill_switch is None:
        _empty("킬스위치 데이터가 없습니다. 데몬이 실행 중인지 확인하세요.")
    else:
        # Overall status
        triggered = _kill_switch.get("triggered", False)
        if triggered:
            st.markdown(
                f'<span class="status-badge status-fail">킬스위치 발동</span> '
                f'{_kill_switch.get("trigger_reason", "")}',
                unsafe_allow_html=True,
            )
        else:
            warning = _kill_switch.get("warning_active", False)
            if warning:
                st.markdown(
                    '<span class="status-badge status-warn">경고 활성</span> '
                    "리스크 지표 상승 중",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<span class="status-badge status-ok">킬스위치 정상</span>',
                    unsafe_allow_html=True,
                )

        # Config limits
        ks_config = _kill_switch.get("config", {})
        max_dd = ks_config.get("max_portfolio_drawdown_pct", 0.05)
        max_daily = ks_config.get("max_daily_loss_pct", 0.03)
        max_consec = ks_config.get("max_consecutive_losses", 5)
        warn_thresh = ks_config.get("warn_threshold_pct", 0.5)
        reduce_thresh = ks_config.get("reduce_threshold_pct", 0.75)

        # Current values
        cur_dd = _kill_switch.get("portfolio_drawdown_pct", 0)
        cur_daily = _kill_switch.get("daily_loss_pct", 0)
        cur_consec = _kill_switch.get("consecutive_losses", 0)
        penalty = _kill_switch.get("position_size_penalty", 1.0)

        st.markdown("#### 리스크 게이지")

        def _make_gauge(
            title: str, value: float, max_val: float,
            suffix: str = "%", is_int: bool = False,
        ) -> go.Figure:
            """Create a gauge chart for a risk metric."""
            if is_int:
                display_val = int(value)
                warn_val = int(max_val * warn_thresh)
                reduce_val = int(max_val * reduce_thresh)
            else:
                display_val = value * 100
                max_val_display = max_val * 100
                warn_val = max_val_display * warn_thresh
                reduce_val = max_val_display * reduce_thresh
                max_val = max_val_display

            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=display_val,
                number={"suffix": suffix, "font": {"size": 24}},
                title={"text": title, "font": {"size": 14}},
                gauge=dict(
                    axis=dict(range=[0, max_val], tickfont=dict(size=10)),
                    bar=dict(color=COLORS["blue"]),
                    bgcolor="rgba(0,0,0,0)",
                    steps=[
                        dict(range=[0, warn_val], color=COLORS["green_bg"]),
                        dict(range=[warn_val, reduce_val], color="#5c4d1a"),
                        dict(range=[reduce_val, max_val], color=COLORS["red_bg"]),
                    ],
                    threshold=dict(
                        line=dict(color=COLORS["red"], width=3),
                        thickness=0.8,
                        value=max_val,
                    ),
                ),
            ))
            fig.update_layout(
                **chart_layout(height=200, show_legend=False),
            )
            return fig

        g1, g2, g3 = st.columns(3)
        with g1:
            st.plotly_chart(
                _make_gauge("포트폴리오 MDD", cur_dd, max_dd),
                use_container_width=True,
            )
        with g2:
            st.plotly_chart(
                _make_gauge("일간 손실", cur_daily, max_daily),
                use_container_width=True,
            )
        with g3:
            st.plotly_chart(
                _make_gauge("연속 손실", cur_consec, max_consec, suffix="회", is_int=True),
                use_container_width=True,
            )

        # Position size penalty
        st.markdown("#### 포지션 크기 조절")
        penalty_pct = penalty * 100
        penalty_color = COLORS["green"] if penalty >= 0.9 else COLORS["yellow"] if penalty >= 0.6 else COLORS["red"]
        st.markdown(
            f'포지션 크기 배율: <span style="color:{penalty_color};font-weight:700;font-size:1.5rem;">'
            f"{penalty_pct:.0f}%</span>",
            unsafe_allow_html=True,
        )
        if penalty < 1.0:
            st.caption(f"리스크 수준에 따라 포지션 크기가 {100 - penalty_pct:.0f}% 축소되었습니다.")

        # Kill switch config summary
        st.markdown("#### 킬스위치 설정")
        c1, c2, c3 = st.columns(3)
        c1.metric("MDD 한도", f"{max_dd:.1%}")
        c2.metric("일간 손실 한도", f"{max_daily:.1%}")
        c3.metric("연속 손실 한도", f"{max_consec}회")
        c4, c5 = st.columns(2)
        c4.metric("경고 임계값", f"{warn_thresh:.0%}")
        c5.metric("축소 임계값", f"{reduce_thresh:.0%}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 7: 시그널 — 시그널 히스토리 타임라인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_signals:
    if not _strategy_runs:
        _empty("최근 시그널 기록이 없습니다.")
    else:
        ACTION_KR = {"buy": "매수", "sell": "매도", "hold": "관망"}
        hide_hold = st.checkbox("관망(hold) 숨기기", value=True)
        filtered = [r for r in _strategy_runs if not (hide_hold and r.get("signal_action") == "hold")]
        st.markdown(f"#### 시그널 히스토리 ({len(filtered)}건 / 전체 {len(_strategy_runs)}건)")

        # Batch render into single HTML block for performance
        html_parts = ['<div class="signal-container">']
        for run in reversed(filtered[-50:]):
            ts = run.get("recorded_at", "")[:19]
            action = run.get("signal_action", "hold")
            symbol = run.get("symbol", "?")
            price = run.get("latest_price", 0)
            regime = run.get("market_regime", "")
            reason = run.get("signal_reason", "")
            confidence = run.get("signal_confidence", 0)
            wallet = run.get("wallet_name", "")

            action_kr = ACTION_KR.get(action, action)
            if action == "buy":
                css_cls = "signal-buy"
                icon = "🟢"
            elif action == "sell":
                css_cls = "signal-sell"
                icon = "🔴"
            else:
                css_cls = "signal-hold"
                icon = "⚪"

            # Confidence bar
            conf_color = COLORS["green"] if confidence > 0.7 else COLORS["yellow"] if confidence > 0.4 else COLORS["red"]
            conf_bar = (
                f'<span class="conf-track">'
                f'<span class="conf-fill" style="width:{confidence*100:.0f}%;'
                f'background:{conf_color};"></span></span>'
            )

            wallet_display = f" · {strategy_kr(wallet)}" if wallet else ""
            html_parts.append(
                f'<div class="signal-row">'
                f'{icon} <span class="{css_cls}">{action_kr}</span> '
                f"<strong>{symbol_kr(symbol)}</strong> ₩{price:,.0f} · {reason} · "
                f"{confidence:.0%} {conf_bar}"
                f"{wallet_display}"
                f'<br><span style="color:var(--text-secondary);font-size:0.8125rem">'
                f"{ts} · {regime_kr(regime)}</span>"
                f"</div>"
            )
        html_parts.append("</div>")
        st.markdown("".join(html_parts), unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 8: 시그널분석 — Hold 사유 분포 + 전략별 시그널 분포
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_sig_analysis:
    try:
        sig_summary = load_signal_summary()
    except Exception:
        sig_summary = None

    if sig_summary is None or (not sig_summary.get("hold_reasons") and not sig_summary.get("by_wallet")):
        _empty("시그널 분석 데이터가 없습니다.")
    else:
        # Hold 사유 분포 파이차트
        hold_reasons = sig_summary.get("hold_reasons", {})
        if hold_reasons:
            st.markdown("#### Hold 사유 분포")
            # Top 10 reasons, rest grouped as '기타'
            sorted_reasons = sorted(hold_reasons.items(), key=lambda x: x[1], reverse=True)
            top_reasons = sorted_reasons[:10]
            other_count = sum(v for _, v in sorted_reasons[10:])
            labels = [r for r, _ in top_reasons]
            values = [v for _, v in top_reasons]
            if other_count > 0:
                labels.append("기타")
                values.append(other_count)

            fig_pie = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                hole=0.4,
                textinfo="label+percent",
                textposition="outside",
                marker=dict(colors=PALETTE[:len(labels)]),
            )])
            fig_pie.update_layout(**chart_layout(height=350, show_legend=False))
            st.plotly_chart(fig_pie, use_container_width=True)

        # 전략별 시그널 분포 (stacked bar)
        by_wallet = sig_summary.get("by_wallet", {})
        if by_wallet:
            st.markdown("#### 전략별 시그널 분포")
            wallet_names = [strategy_kr(w) for w in by_wallet]
            buys = [by_wallet[w]["buy"] for w in by_wallet]
            sells = [by_wallet[w]["sell"] for w in by_wallet]
            holds = [by_wallet[w]["hold"] for w in by_wallet]

            fig_stack = go.Figure()
            fig_stack.add_trace(go.Bar(name="매수", x=wallet_names, y=buys, marker_color=COLORS["green"]))
            fig_stack.add_trace(go.Bar(name="매도", x=wallet_names, y=sells, marker_color=COLORS["red"]))
            fig_stack.add_trace(go.Bar(name="관망", x=wallet_names, y=holds, marker_color=COLORS["muted"]))
            fig_stack.update_layout(**chart_layout(height=280), barmode="stack")
            st.plotly_chart(fig_stack, use_container_width=True)

            # 전략별 매수율 + 평균 신뢰도 테이블
            st.markdown("#### 전략별 매수율 / 평균 신뢰도")
            for wallet_key, stats in by_wallet.items():
                total = stats["total"]
                buy_rate = (stats["buy"] / total * 100) if total > 0 else 0
                avg_conf = stats["avg_conf"]
                col1, col2, col3 = st.columns(3)
                col1.metric(strategy_kr(wallet_key), f"{total}건")
                col2.metric("매수율", f"{buy_rate:.1f}%")
                col3.metric("평균 신뢰도", f"{avg_conf:.2f}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 9: 체결현황 — 최근 24h 체결 + 전략별 승률
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_trades:
    if not _paper_trades:
        _empty("체결 데이터가 없습니다.")
    else:
        # Filter last 24h trades
        now = datetime.now(_UTC)
        cutoff = now - timedelta(hours=24)
        recent_trades: list[dict[str, Any]] = []
        for t in _paper_trades:
            exit_str = t.get("exit_time", "")
            if exit_str:
                try:
                    exit_time = datetime.fromisoformat(exit_str)
                    if exit_time.tzinfo is None:
                        exit_time = exit_time.replace(tzinfo=_UTC)
                    if exit_time >= cutoff:
                        recent_trades.append(t)
                except (ValueError, TypeError):
                    continue

        st.markdown(f"#### 최근 24시간 체결 ({len(recent_trades)}건)")

        if recent_trades:
            # Trade table as HTML
            html = ['<table style="width:100%;font-size:0.85rem;border-collapse:collapse;">']
            html.append(
                "<tr style='border-bottom:1px solid #374151;color:var(--text-secondary);'>"
                "<th>시각</th><th>종목</th><th>전략</th>"
                "<th>진입가</th><th>청산가</th><th>손익</th></tr>"
            )
            for t in reversed(recent_trades[-30:]):
                exit_str = t.get("exit_time", "")[:16]
                sym = t.get("symbol", "?")
                wallet = t.get("wallet", "")
                entry_p = t.get("entry_price", 0)
                exit_p = t.get("exit_price", 0)
                pnl_val = t.get("pnl", 0)
                pnl_pct = t.get("pnl_pct", 0)
                html.append(
                    f"<tr style='border-bottom:1px solid #1f2937;'>"
                    f"<td>{exit_str}</td>"
                    f"<td>{symbol_kr(sym)}</td>"
                    f"<td>{strategy_kr(wallet)}</td>"
                    f"<td>₩{entry_p:,.0f}</td>"
                    f"<td>₩{exit_p:,.0f}</td>"
                    f"<td style='color:{pnl_color(pnl_val)};'>{pnl_pct:+.2f}%</td>"
                    f"</tr>"
                )
            html.append("</table>")
            st.markdown("".join(html), unsafe_allow_html=True)
        else:
            _empty("최근 24시간 내 체결 내역이 없습니다.")

        # 전략별 승률 (all trades)
        st.markdown("#### 전략별 승률")
        wallet_stats: dict[str, dict[str, int]] = {}
        for t in _paper_trades:
            w = t.get("wallet", "unknown")
            if w not in wallet_stats:
                wallet_stats[w] = {"wins": 0, "total": 0}
            wallet_stats[w]["total"] += 1
            if t.get("pnl", 0) > 0:
                wallet_stats[w]["wins"] += 1

        if wallet_stats:
            w_names = [strategy_kr(w) for w in wallet_stats]
            w_rates = [
                (s["wins"] / s["total"] * 100) if s["total"] > 0 else 0
                for s in wallet_stats.values()
            ]
            w_totals = [s["total"] for s in wallet_stats.values()]

            fig_wr = go.Figure()
            fig_wr.add_trace(go.Bar(
                x=w_names, y=w_rates,
                marker_color=[COLORS["green"] if r >= 50 else COLORS["red"] for r in w_rates],
                text=[f"{r:.1f}% ({t}건)" for r, t in zip(w_rates, w_totals)],
                textposition="outside",
            ))
            fig_wr.update_layout(
                **chart_layout(yaxis_title="승률 (%)", show_legend=False),
                yaxis=dict(range=[0, 105]),
            )
            st.plotly_chart(fig_wr, use_container_width=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 10: 시장국면 — Regime 상태
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_regime:
    try:
        regime = load_regime_report()
    except Exception:
        regime = None

    if regime is None:
        _empty("시장 국면 데이터가 없습니다. regime-report CLI를 실행하세요.")
    else:
        market_regime = regime.get("market_regime", "unknown")
        badge_map = {
            "bull": ("regime-bull", "상승장"),
            "sideways": ("regime-sideways", "횡보장"),
            "bear": ("regime-bear", "하락장"),
        }
        cls, label = badge_map.get(market_regime, ("regime-sideways", market_regime.upper()))
        st.markdown(f'<span class="regime-badge {cls}">{label}</span>', unsafe_allow_html=True)

        sym = regime.get("symbol", "?")
        st.caption(f"종목: {symbol_kr(sym)} · {regime.get('generated_at', '')[:19]}")

        # Staleness warning
        regime_info = _freshness["files"].get("regime-report.json", {})
        if regime_info.get("is_stale"):
            age_h = regime_info.get("age_seconds", 0) / 3600
            st.warning(f"국면 데이터가 {age_h:.1f}시간 전 것입니다. 최신 데이터가 아닐 수 있습니다.")

        c1, c2 = st.columns(2)
        short_ret = regime.get("short_return_pct", 0) * 100
        long_ret = regime.get("long_return_pct", 0) * 100
        c1.metric("단기 수익률", f"{short_ret:+.2f}%")
        c2.metric("장기 수익률", f"{long_ret:+.2f}%")

        # 분석 근거
        reasons = regime.get("reasons", [])
        if reasons:
            st.markdown("**분석 근거:**")
            for r in reasons:
                st.markdown(f"- {r}")

        # 파라미터 비교
        base = regime.get("base_parameters", {})
        adjusted = regime.get("adjusted_parameters", {})
        if base and adjusted:
            changed = {k: (base[k], adjusted[k]) for k in base if base.get(k) != adjusted.get(k)}
            if changed:
                st.markdown("**조정된 파라미터:**")
                for k, (b, a) in changed.items():
                    st.markdown(f"- `{k}`: {b} → {a}")
            else:
                st.caption("파라미터 변경 없음 (기본값 유지)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 11: 운영리포트 — Drift / Promotion / 메모
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_operator:
    try:
        drift = load_drift_report()
    except Exception:
        drift = None

    try:
        promo = load_promotion_gate()
    except Exception:
        promo = None

    try:
        memo = load_daily_memo()
    except Exception:
        memo = None

    DRIFT_KR = {
        "on_track": ("status-ok", "정상 추적"),
        "caution": ("status-warn", "주의"),
        "drifting": ("status-warn", "편차 발생"),
        "out_of_sync": ("status-fail", "동기화 이탈"),
        "insufficient_data": ("status-warn", "데이터 부족"),
    }

    # 드리프트 상태
    st.markdown("#### 드리프트 상태")
    if drift is None:
        _empty("드리프트 데이터가 없습니다.")
    else:
        drift_status = drift.get("status", "unknown")
        cls, label = DRIFT_KR.get(drift_status, ("status-fail", drift_status.upper()))
        st.markdown(
            f'<span class="status-badge {cls}">{label}</span>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        c1.metric("페이퍼 실행 수", drift.get("paper_run_count", 0))
        c2.metric("페이퍼 손익률", f"{drift.get('paper_realized_pnl_pct', 0):.2%}")

        # 추가 지표
        c3, c4 = st.columns(2)
        c3.metric("매수 비율", f"{drift.get('paper_buy_rate', 0):.0%}")
        c4.metric("매도 비율", f"{drift.get('paper_sell_rate', 0):.0%}")

        for r in drift.get("reasons", []):
            st.caption(f"· {r}")

    st.divider()

    # 승격 게이트
    PROMO_KR = {
        "promote": ("status-ok", "승격 가능"),
        "candidate_for_promotion": ("status-ok", "승격 후보"),
        "stay_in_paper": ("status-warn", "페이퍼 유지"),
        "do_not_promote": ("status-fail", "승격 불가"),
    }

    st.markdown("#### 라이브 승격 판정")
    if promo is None:
        _empty("승격 판정 데이터가 없습니다.")
    else:
        promo_status = promo.get("status", "unknown")
        cls, label = PROMO_KR.get(promo_status, ("status-warn", promo_status.upper()))
        st.markdown(
            f'<span class="status-badge {cls}">{label}</span>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        c1.metric("관찰된 실행", promo.get("observed_paper_runs", 0))
        c2.metric("필요 최소 실행", promo.get("minimum_paper_runs_required", 0))
        for r in promo.get("reasons", []):
            st.caption(f"· {r}")

    st.divider()

    # 일일 메모
    st.markdown("#### 일일 운영 메모")
    if memo is None:
        _empty("일일 메모가 없습니다.")
    else:
        st.markdown(memo)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 12: 시스템 — 전략 활성/비활성 + 마지막 시그널 시각
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_health:
    # Overall system status
    st.markdown("#### 시스템 상태")
    if _heartbeat is not None:
        hb_time_str_h = _heartbeat.get("last_heartbeat", "")
        try:
            hb_time_h = datetime.fromisoformat(hb_time_str_h)
            age_h = (datetime.now(_UTC) - hb_time_h).total_seconds()
        except (ValueError, TypeError):
            age_h = float("inf")
        poll_h = _heartbeat.get("poll_interval_seconds", 60)
        if age_h <= poll_h * 2:
            st.markdown(
                '<span class="status-badge status-ok">시스템 정상</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<span class="status-badge status-fail">시스템 이상</span>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<span class="status-badge status-fail">시스템 이상</span> 하트비트 없음',
            unsafe_allow_html=True,
        )

    # Data freshness detail
    st.markdown("#### 데이터 신선도")
    for fname, info in _freshness["files"].items():
        if not info.get("exists"):
            st.markdown(
                f'<span class="status-badge status-fail">없음</span> {fname}',
                unsafe_allow_html=True,
            )
        else:
            age = info.get("age_seconds", 0)
            if age < 120:
                badge = "status-ok"
                age_str = f"{int(age)}초 전"
            elif age < 300:
                badge = "status-warn"
                age_str = f"{int(age)}초 전"
            elif age < 3600:
                badge = "status-warn"
                age_str = f"{int(age // 60)}분 전"
            else:
                badge = "status-fail"
                age_str = f"{age / 3600:.1f}시간 전"
            st.markdown(
                f'<span class="status-badge {badge}">{age_str}</span> {fname}',
                unsafe_allow_html=True,
            )

    st.divider()

    # Per-strategy health cards
    st.markdown("#### 전략별 상태")
    wallet_states_h = _get_wallet_states()

    # Build last-signal-time per wallet from runs
    last_signal_by_wallet: dict[str, str] = {}
    for run in _strategy_runs:
        w = run.get("wallet_name", "")
        ts = run.get("recorded_at", "")
        if w and ts:
            if w not in last_signal_by_wallet or ts > last_signal_by_wallet[w]:
                last_signal_by_wallet[w] = ts

    if not wallet_states_h:
        _empty("전략 상태 정보가 없습니다.")
    else:
        cols_h = st.columns(min(len(wallet_states_h), 3))
        for i, (wname, wstate) in enumerate(wallet_states_h.items()):
            with cols_h[i % len(cols_h)]:
                display_name = strategy_kr(wname)
                trade_count = wstate.get("trade_count", 0)
                equity = wstate.get("equity", 0)
                open_pos = wstate.get("open_positions", 0)

                # Determine active/inactive
                last_ts = last_signal_by_wallet.get(wname, "")
                is_active = False
                time_ago_str = "기록 없음"
                if last_ts:
                    try:
                        last_dt = datetime.fromisoformat(last_ts)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=_UTC)
                        delta = datetime.now(_UTC) - last_dt
                        hours_ago = delta.total_seconds() / 3600
                        is_active = hours_ago < 2
                        if hours_ago < 1:
                            time_ago_str = f"{int(delta.total_seconds() / 60)}분 전"
                        elif hours_ago < 24:
                            time_ago_str = f"{hours_ago:.1f}시간 전"
                        else:
                            time_ago_str = f"{int(hours_ago / 24)}일 전"
                    except (ValueError, TypeError):
                        pass

                badge_cls = "status-ok" if is_active else "status-warn"
                badge_text = "활성" if is_active else "비활성"

                st.markdown(
                    f'<div class="position-card">'
                    f'<strong>{display_name}</strong> '
                    f'<span class="status-badge {badge_cls}">{badge_text}</span><br>'
                    f'마지막 시그널: {time_ago_str}<br>'
                    f'자본: ₩{equity:,.0f} · 거래 {trade_count}건 · 포지션 {open_pos}개'
                    f'</div>',
                    unsafe_allow_html=True,
                )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 13: 성과 — 백테스트 기준선 + 일간 성과 + 가격 차트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_perf:
    try:
        baseline = load_backtest_baseline()
    except Exception:
        baseline = None

    try:
        daily_perf = load_daily_performance()
    except Exception:
        daily_perf = None

    # 백테스트 기준선
    if baseline is None:
        _empty("백테스트 데이터가 없습니다.")
    elif baseline:
        st.markdown("#### 백테스트 기준선")
        c1, c2, c3 = st.columns(3)
        c1.metric("수익률", f"{baseline.get('total_return_pct', 0):.2%}")
        c2.metric("승률", f"{baseline.get('win_rate', 0):.0%}")
        c3.metric("거래 수", baseline.get("trade_count", 0))
        c4, c5 = st.columns(2)
        c4.metric("최대 낙폭", f"{baseline.get('max_drawdown', 0):.2%}")
        c5.metric("수익 팩터", f"{baseline.get('profit_factor', 0):.2f}")

    # 일간 성과
    if daily_perf is None:
        _empty("성과 데이터가 없습니다.")
    elif daily_perf:
        st.markdown("#### 일간 성과")

        # Staleness warning
        dp_info = _freshness["files"].get("daily-performance.json", {})
        if dp_info.get("is_stale"):
            age_h = dp_info.get("age_seconds", 0) / 3600
            st.warning(f"일간 성과 데이터가 {age_h:.1f}시간 전 것입니다.")

        c1, c2, c3 = st.columns(3)
        c1.metric("실현 수익률", f"{daily_perf.get('realized_return_pct', 0):.2%}")
        c2.metric("승률", f"{daily_perf.get('win_rate', 0):.0%}")
        c3.metric("시가평가 자산", f"₩{daily_perf.get('mark_to_market_equity', 0):,.0f}")

    # 판단 시점 + 현재가 비교 가격 차트
    if _strategy_runs:
        st.markdown("#### 가격 추이 및 시그널")
        timestamps = []
        prices = []
        actions = []
        for run in _strategy_runs:
            ts_str = run.get("recorded_at", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    continue
                timestamps.append(ts)
                prices.append(run.get("latest_price", 0))
                actions.append(run.get("signal_action", "hold"))

        if timestamps:
            # 시그널별 색상 + 크기
            marker_colors = []
            marker_sizes = []
            hover_texts = []
            ACTION_KR_CHART = {"buy": "매수", "sell": "매도", "hold": "관망"}
            for i, a in enumerate(actions):
                if a == "buy":
                    marker_colors.append(COLORS["green"])
                    marker_sizes.append(14)
                elif a == "sell":
                    marker_colors.append(COLORS["red"])
                    marker_sizes.append(14)
                else:
                    marker_colors.append(COLORS["muted"])
                    marker_sizes.append(7)
                hover_texts.append(
                    f"{ACTION_KR_CHART.get(a, a)} · ₩{prices[i]:,.0f}<br>"
                    f"{timestamps[i].strftime('%m/%d %H:%M')}"
                )

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=prices,
                    mode="lines+markers",
                    name="가격",
                    line=dict(color=COLORS["blue"], width=2),
                    marker=dict(size=marker_sizes, color=marker_colors),
                    hovertext=hover_texts,
                    hoverinfo="text",
                )
            )

            # 매수/매도 포인트 강조
            buy_ts = [t for t, a in zip(timestamps, actions) if a == "buy"]
            buy_pr = [p for p, a in zip(prices, actions) if a == "buy"]
            sell_ts = [t for t, a in zip(timestamps, actions) if a == "sell"]
            sell_pr = [p for p, a in zip(prices, actions) if a == "sell"]

            if buy_ts:
                fig.add_trace(go.Scatter(
                    x=buy_ts, y=buy_pr, mode="markers",
                    name="매수", marker=dict(size=16, color=COLORS["green"], symbol="triangle-up"),
                ))
            if sell_ts:
                fig.add_trace(go.Scatter(
                    x=sell_ts, y=sell_pr, mode="markers",
                    name="매도", marker=dict(size=16, color=COLORS["red"], symbol="triangle-down"),
                ))

            fig.update_layout(
                **chart_layout(yaxis_title="가격 (KRW)"),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)
    elif not baseline and not daily_perf:
        _empty("성과 데이터가 없습니다.")

# ── 푸터 ──────────────────────────────────────────────────
st.divider()
now_str = datetime.now(_KST).strftime("%Y-%m-%d %H:%M KST")
st.caption(f"마지막 새로고침: {now_str} · 60초 자동 갱신")
