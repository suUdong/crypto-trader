"""Crypto Trader Dashboard — mobile-first Streamlit app."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the repo root is on sys.path so that 'dashboard' resolves as a package
# when Streamlit Cloud runs this file directly (streamlit run dashboard/app.py).
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import plotly.graph_objects as go  # type: ignore[import-untyped]  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.auth import check_auth, render_login  # noqa: E402
from dashboard.data import (  # noqa: E402
    load_backtest_baseline,
    load_checkpoint,
    load_daemon_heartbeat,
    load_daily_memo,
    load_daily_performance,
    load_drift_report,
    load_health,
    load_positions,
    load_promotion_gate,
    load_regime_report,
    load_strategy_runs,
)
from dashboard.styles import inject_css  # noqa: E402

_UTC = timezone.utc  # noqa: UP017

# ── Page Config ────────────────────────────────────────────
st.set_page_config(
    page_title="Crypto Trader",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
)
inject_css()

# ── Auth Gate ──────────────────────────────────────────────
if not check_auth():
    render_login()
    st.stop()

# ── Header ─────────────────────────────────────────────────
st.markdown("## 📊 Crypto Trader Dashboard")

# ── Tab Navigation ─────────────────────────────────────────
tab_trading, tab_wallets, tab_signals, tab_regime, tab_operator, tab_perf = st.tabs(
    ["현황", "전략비교", "시그널", "Regime", "리포트", "성과"]
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tab 1: Paper Trading Overview
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_trading:
    # Daemon heartbeat status
    heartbeat = load_daemon_heartbeat()
    if heartbeat is None:
        st.markdown(
            '<span class="status-badge status-fail">DAEMON OFF</span> '
            "하트비트 데이터 없음",
            unsafe_allow_html=True,
        )
    else:
        hb_time_str = heartbeat.get("last_heartbeat", "")
        poll_interval = heartbeat.get("poll_interval_seconds", 60)
        stale_threshold = poll_interval * 2
        try:
            hb_time = datetime.fromisoformat(hb_time_str)
            age_seconds = (datetime.now(_UTC) - hb_time).total_seconds()
        except (ValueError, TypeError):
            age_seconds = float("inf")

        if age_seconds <= stale_threshold:
            badge_cls, badge_text = "status-ok", "DAEMON ALIVE"
        else:
            badge_cls, badge_text = "status-fail", "DAEMON STALE"

        uptime = heartbeat.get("uptime_seconds", 0)
        uptime_min = int(uptime // 60)
        pid = heartbeat.get("pid", "?")
        iteration = heartbeat.get("iteration", 0)
        st.markdown(
            f'<span class="status-badge {badge_cls}">{badge_text}</span> '
            f"PID {pid} · 반복 #{iteration} · 가동 {uptime_min}분 · "
            f"마지막 {int(age_seconds)}초 전",
            unsafe_allow_html=True,
        )

    st.divider()

    checkpoint = load_checkpoint()
    health = load_health()
    positions = load_positions()

    if checkpoint is None:
        st.info("런타임 체크포인트 데이터가 없습니다.")
    else:
        # Health indicator
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

        # Checkpoint time
        gen_at = checkpoint.get("generated_at", "")
        if gen_at:
            st.caption(f"업데이트: {gen_at[:19]}")

        # Iteration & symbols
        iteration = checkpoint.get("iteration", 0)
        symbols = checkpoint.get("symbols", [])
        st.markdown(f"**반복 #{iteration}** · {', '.join(symbols)}")

        # Wallet summary cards
        wallet_states = checkpoint.get("wallet_states", {})
        if wallet_states:
            cols = st.columns(len(wallet_states))
            for col, (name, state) in zip(cols, wallet_states.items(), strict=False):
                with col:
                    display_name = name.replace("_wallet", "").replace("_", " ").title()
                    equity = state.get("equity", 0)
                    pnl = state.get("realized_pnl", 0)
                    trades = state.get("trade_count", 0)
                    st.metric(display_name, f"₩{equity:,.0f}", f"PnL: ₩{pnl:,.0f}")
                    st.caption(f"거래 {trades}건 · 포지션 {state.get('open_positions', 0)}개")

        # Open positions
        if positions:
            pos_list = positions.get("positions", [])
            if pos_list:
                st.markdown("#### 보유 포지션")
                for p in pos_list:
                    st.markdown(
                        f"- **{p.get('symbol', '?')}** "
                        f"수량: {p.get('quantity', 0):.8f} "
                        f"진입가: ₩{p.get('entry_price', 0):,.0f}"
                    )
            else:
                st.caption("보유 포지션 없음")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tab 2: Strategy Wallet Comparison
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_wallets:
    checkpoint = load_checkpoint()
    if checkpoint is None:
        st.info("전략 비교 데이터가 없습니다.")
    else:
        wallet_states = checkpoint.get("wallet_states", {})
        if not wallet_states:
            st.info("지갑 데이터가 없습니다.")
        else:
            names = []
            equities = []
            pnls = []
            trade_counts = []
            for name, state in wallet_states.items():
                display = name.replace("_wallet", "").replace("_", " ").title()
                names.append(display)
                equities.append(state.get("equity", 0))
                pnls.append(state.get("realized_pnl", 0))
                trade_counts.append(state.get("trade_count", 0))

            # Comparison table
            st.markdown("#### 전략별 지갑 비교")
            for i, n in enumerate(names):
                c1, c2, c3 = st.columns(3)
                c1.metric(n, f"₩{equities[i]:,.0f}")
                c2.metric("실현 PnL", f"₩{pnls[i]:,.0f}")
                c3.metric("거래 수", f"{trade_counts[i]}")

            # Bar chart
            fig = go.Figure()
            fig.add_trace(go.Bar(name="자본금", x=names, y=equities, marker_color="#60a5fa"))
            fig.add_trace(go.Bar(name="실현 PnL", x=names, y=pnls, marker_color="#4ade80"))
            fig.update_layout(
                barmode="group",
                template="plotly_dark",
                margin=dict(l=0, r=0, t=30, b=0),
                height=350,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                font=dict(size=14),
            )
            st.plotly_chart(fig, use_container_width=True)

            # Trade count bar
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(name="거래 수", x=names, y=trade_counts, marker_color="#fbbf24"))
            fig2.update_layout(
                template="plotly_dark",
                margin=dict(l=0, r=0, t=30, b=0),
                height=250,
                font=dict(size=14),
            )
            st.plotly_chart(fig2, use_container_width=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tab 3: Signal History Timeline
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_signals:
    runs = load_strategy_runs()
    if not runs:
        st.info("시그널 히스토리가 없습니다.")
    else:
        st.markdown(f"#### 시그널 히스토리 ({len(runs)}건)")
        # Show most recent first
        for run in reversed(runs):
            ts = run.get("recorded_at", "")[:19]
            action = run.get("signal_action", "hold")
            symbol = run.get("symbol", "?")
            price = run.get("latest_price", 0)
            regime = run.get("market_regime", "")
            reason = run.get("signal_reason", "")
            confidence = run.get("signal_confidence", 0)

            if action == "buy":
                css_cls = "signal-buy"
                icon = "🟢"
            elif action == "sell":
                css_cls = "signal-sell"
                icon = "🔴"
            else:
                css_cls = "signal-hold"
                icon = "⚪"

            st.markdown(
                f'{icon} <span class="{css_cls}">{action.upper()}</span> '
                f"**{symbol}** ₩{price:,.0f} · {reason} · conf {confidence:.0%}"
                f'<br><span style="color:#666;font-size:0.8125rem">'
                f"{ts} · {regime}</span>",
                unsafe_allow_html=True,
            )
            st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tab 4: Regime Status
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_regime:
    regime = load_regime_report()
    if regime is None:
        st.info("Regime 데이터가 없습니다.")
    else:
        market_regime = regime.get("market_regime", "unknown")
        badge_map = {
            "bull": ("regime-bull", "BULL 🐂"),
            "sideways": ("regime-sideways", "SIDEWAYS ➡️"),
            "bear": ("regime-bear", "BEAR 🐻"),
        }
        cls, label = badge_map.get(market_regime, ("regime-sideways", market_regime.upper()))
        st.markdown(f'<span class="regime-badge {cls}">{label}</span>', unsafe_allow_html=True)

        st.caption(f"종목: {regime.get('symbol', '?')} · {regime.get('generated_at', '')[:19]}")

        c1, c2 = st.columns(2)
        short_ret = regime.get("short_return_pct", 0) * 100
        long_ret = regime.get("long_return_pct", 0) * 100
        c1.metric("단기 수익률", f"{short_ret:+.2f}%")
        c2.metric("장기 수익률", f"{long_ret:+.2f}%")

        # Reasons
        reasons = regime.get("reasons", [])
        if reasons:
            st.markdown("**분석 근거:**")
            for r in reasons:
                st.markdown(f"- {r}")

        # Parameter comparison
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
# Tab 5: Operator Report
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_operator:
    drift = load_drift_report()
    promo = load_promotion_gate()
    memo = load_daily_memo()

    # Drift status
    st.markdown("#### Drift 상태")
    if drift is None:
        st.info("Drift 데이터가 없습니다.")
    else:
        drift_status = drift.get("status", "unknown")
        if drift_status == "on_track":
            st.markdown(
                '<span class="status-badge status-ok">ON TRACK</span>',
                unsafe_allow_html=True,
            )
        elif drift_status == "drifting":
            st.markdown(
                '<span class="status-badge status-warn">DRIFTING</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<span class="status-badge status-fail">{drift_status.upper()}</span>',
                unsafe_allow_html=True,
            )
        c1, c2 = st.columns(2)
        c1.metric("Paper 실행 수", drift.get("paper_run_count", 0))
        c2.metric("Paper PnL", f"{drift.get('paper_realized_pnl_pct', 0):.2%}")
        for r in drift.get("reasons", []):
            st.caption(f"· {r}")

    st.divider()

    # Promotion gate
    st.markdown("#### Promotion Gate")
    if promo is None:
        st.info("Promotion 데이터가 없습니다.")
    else:
        promo_status = promo.get("status", "unknown")
        if promo_status == "promote":
            st.markdown(
                '<span class="status-badge status-ok">PROMOTE</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<span class="status-badge status-warn">DO NOT PROMOTE</span>',
                unsafe_allow_html=True,
            )
        c1, c2 = st.columns(2)
        c1.metric("관찰된 실행", promo.get("observed_paper_runs", 0))
        c2.metric("필요 최소 실행", promo.get("minimum_paper_runs_required", 0))
        for r in promo.get("reasons", []):
            st.caption(f"· {r}")

    st.divider()

    # Daily memo
    st.markdown("#### Daily Memo")
    if memo is None:
        st.info("Daily Memo가 없습니다.")
    else:
        st.markdown(memo)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tab 6: Performance Charts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_perf:
    runs = load_strategy_runs()
    baseline = load_backtest_baseline()
    daily_perf = load_daily_performance()

    # Baseline summary
    if baseline:
        st.markdown("#### 백테스트 기준선")
        c1, c2, c3 = st.columns(3)
        c1.metric("수익률", f"{baseline.get('total_return_pct', 0):.2%}")
        c2.metric("승률", f"{baseline.get('win_rate', 0):.0%}")
        c3.metric("거래 수", baseline.get("trade_count", 0))
        c4, c5 = st.columns(2)
        c4.metric("최대 낙폭", f"{baseline.get('max_drawdown', 0):.2%}")
        c5.metric("Profit Factor", f"{baseline.get('profit_factor', 0):.2f}")

    # Daily performance
    if daily_perf:
        st.markdown("#### 일간 성과")
        c1, c2, c3 = st.columns(3)
        c1.metric("실현 수익률", f"{daily_perf.get('realized_return_pct', 0):.2%}")
        c2.metric("승률", f"{daily_perf.get('win_rate', 0):.0%}")
        c3.metric("시가평가 자산", f"₩{daily_perf.get('mark_to_market_equity', 0):,.0f}")

    # Price chart from signal history
    if runs:
        st.markdown("#### 가격 추이")
        timestamps = []
        prices = []
        actions = []
        for run in runs:
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
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=prices,
                    mode="lines+markers",
                    name="Price",
                    line=dict(color="#60a5fa", width=2),
                    marker=dict(
                        size=8,
                        color=[
                            "#4ade80" if a == "buy" else "#f87171" if a == "sell" else "#6b7280"
                            for a in actions
                        ],
                    ),
                )
            )
            fig.update_layout(
                template="plotly_dark",
                margin=dict(l=0, r=0, t=10, b=0),
                height=400,
                yaxis_title="Price (KRW)",
                xaxis_title="",
                font=dict(size=14),
            )
            st.plotly_chart(fig, use_container_width=True)
    elif not baseline and not daily_perf:
        st.info("성과 데이터가 없습니다.")

# ── Footer ─────────────────────────────────────────────────
st.divider()
now = datetime.now(_UTC).strftime("%Y-%m-%d %H:%M UTC")
st.caption(f"마지막 새로고침: {now}")
