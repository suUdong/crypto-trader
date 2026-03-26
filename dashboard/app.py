"""크립토 트레이더 대시보드 — 모바일 최적화 Streamlit 앱."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import plotly.graph_objects as go  # noqa: E402
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
    load_kill_switch,
    load_pnl_report,
    load_positions,
    load_promotion_gate,
    load_regime_report,
    load_strategy_runs,
    regime_kr,
    strategy_kr,
    symbol_kr,
)
from dashboard.styles import inject_css  # noqa: E402

_UTC = timezone.utc  # noqa: UP017

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

# ── 헤더 ──────────────────────────────────────────────────
st.markdown("## 📊 크립토 트레이더 대시보드")

# ── 데몬 상태 (전체 공통) ─────────────────────────────────
try:
    heartbeat = load_daemon_heartbeat()
except Exception:
    heartbeat = None

if heartbeat is None:
    st.markdown(
        '<span class="status-badge status-fail">데몬 중지</span> '
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
        badge_cls, badge_text = "status-ok", "데몬 정상"
    else:
        badge_cls, badge_text = "status-warn", "데몬 지연"

    uptime = heartbeat.get("uptime_seconds", 0)
    if uptime >= 3600:
        uptime_str = f"{int(uptime // 3600)}시간 {int((uptime % 3600) // 60)}분"
    else:
        uptime_str = f"{int(uptime // 60)}분"
    pid = heartbeat.get("pid", "?")
    iteration = heartbeat.get("iteration", 0)
    symbols_list = heartbeat.get("symbols", [])
    symbols_text = ", ".join(symbol_kr(s) for s in symbols_list) if symbols_list else ""

    st.markdown(
        f'<span class="status-badge {badge_cls}">{badge_text}</span> '
        f"PID {pid} · 반복 #{iteration} · 가동 {uptime_str} · "
        f"마지막 {int(age_seconds)}초 전"
        + (f"<br>종목: {symbols_text}" if symbols_text else ""),
        unsafe_allow_html=True,
    )

# ── 탭 내비게이션 ─────────────────────────────────────────
tab_trading, tab_wallets, tab_signals, tab_regime, tab_operator, tab_perf = st.tabs(
    ["현황", "전략비교", "시그널", "시장국면", "운영리포트", "성과"]
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 1: 현황 — 페이퍼 트레이딩 개요
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_trading:
    with st.spinner("데이터 로딩 중..."):
        try:
            checkpoint = load_checkpoint()
        except Exception:
            checkpoint = None
            st.warning("체크포인트 데이터를 불러오는 중 오류가 발생했습니다.")

        try:
            health = load_health()
        except Exception:
            health = None
            st.warning("헬스 데이터를 불러올 수 없습니다.")

        positions = None  # positions now read from checkpoint directly

    if checkpoint is None:
        st.info("런타임 체크포인트 데이터가 없습니다.")
    else:
        # 헬스 표시기
        if health is None:
            st.info("헬스 데이터를 불러올 수 없습니다.")
        elif health:
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
            try:
                ks = load_kill_switch()
            except Exception:
                ks = None
            if ks is None:
                st.markdown('<span class="status-badge status-warn">킬스위치 ?</span>', unsafe_allow_html=True)
            elif ks.get("triggered"):
                st.markdown(
                    f'<span class="status-badge status-fail">킬스위치 발동</span> {ks.get("trigger_reason", "")}',
                    unsafe_allow_html=True,
                )
            else:
                dd = ks.get("portfolio_drawdown_pct", 0) * 100
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
        gen_at = checkpoint.get("generated_at", "")
        if gen_at:
            st.caption(f"업데이트: {gen_at[:19]}")

        # 반복 & 종목
        iteration = checkpoint.get("iteration", 0)
        symbols = checkpoint.get("symbols", [])
        symbols_display = ", ".join(symbol_kr(s) for s in symbols)
        st.markdown(f"**반복 #{iteration}** · {symbols_display}")

        # 전략별 지갑 요약 카드
        wallet_states = checkpoint.get("wallet_states", {})
        if not wallet_states:
            st.info("지갑 정보를 불러올 수 없습니다.")
        else:
            # 모바일에서 자연스럽게 쌓이도록 max 3컬럼 유지 (CSS가 스택 처리)
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
            st.info("보유 포지션이 없습니다.")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 2: 전략비교 — 전략별 지갑 비교
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_wallets:
    with st.spinner("데이터 로딩 중..."):
        try:
            checkpoint = load_checkpoint()
        except Exception:
            checkpoint = None
            st.warning("전략 비교 데이터를 불러오는 중 오류가 발생했습니다.")

    if checkpoint is None:
        st.info("전략 비교 데이터가 없습니다.")
    else:
        wallet_states = checkpoint.get("wallet_states", {})
        if not wallet_states:
            st.info("지갑 정보를 불러올 수 없습니다.")
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

            # 전략별 비교 테이블 (모바일에서 CSS가 2컬럼으로 처리)
            st.markdown("#### 전략별 성과 비교")
            for i, n in enumerate(names):
                c1, c2, c3 = st.columns(3)
                c1.metric(n, f"₩{equities[i]:,.0f}", f"{return_pcts[i]:+.2f}%")
                c2.metric("실현 손익", f"₩{pnls[i]:,.0f}")
                c3.metric("거래 수", f"{trade_counts[i]}")

            # 수익률 비교 차트
            pnl_colors = ["#4ade80" if p >= 0 else "#f87171" for p in return_pcts]
            fig_ret = go.Figure()
            fig_ret.add_trace(go.Bar(
                name="수익률(%)",
                x=names,
                y=return_pcts,
                marker_color=pnl_colors,
                text=[f"{r:+.2f}%" for r in return_pcts],
                textposition="outside",
            ))
            fig_ret.update_layout(
                title="전략별 수익률",
                template="plotly_dark",
                margin=dict(l=8, r=8, t=32, b=8),
                height=280,
                font=dict(size=11),
                yaxis_title="수익률 (%)",
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig_ret, use_container_width=True)

            # 자본금 vs PnL 비교 차트
            fig = go.Figure()
            fig.add_trace(go.Bar(name="자본금", x=names, y=equities, marker_color="#60a5fa"))
            fig.add_trace(go.Bar(name="실현 손익", x=names, y=pnls, marker_color="#4ade80"))
            fig.update_layout(
                title="전략별 자본금 / 손익",
                barmode="group",
                template="plotly_dark",
                margin=dict(l=8, r=8, t=32, b=8),
                height=280,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                font=dict(size=11),
            )
            st.plotly_chart(fig, use_container_width=True)

            # 거래 수 차트
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(name="거래 수", x=names, y=trade_counts, marker_color="#fbbf24"))
            fig2.update_layout(
                title="전략별 거래 수",
                template="plotly_dark",
                margin=dict(l=8, r=8, t=32, b=8),
                height=280,
                font=dict(size=11),
            )
            st.plotly_chart(fig2, use_container_width=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 3: 시그널 — 시그널 히스토리 타임라인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_signals:
    with st.spinner("데이터 로딩 중..."):
        try:
            runs = load_strategy_runs()
        except Exception:
            runs = None
            st.warning("시그널 데이터를 불러오는 중 오류가 발생했습니다.")

    if not runs:
        st.info("최근 시그널 기록이 없습니다.")
    else:
        ACTION_KR = {"buy": "매수", "sell": "매도", "hold": "관망"}
        hide_hold = st.checkbox("관망(hold) 숨기기", value=True)
        filtered = [r for r in runs if not (hide_hold and r.get("signal_action") == "hold")]
        st.markdown(f"#### 시그널 히스토리 ({len(filtered)}건 / 전체 {len(runs)}건)")
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

            wallet_display = f" · {strategy_kr(wallet)}" if wallet else ""
            st.markdown(
                f'<div class="signal-row">'
                f'{icon} <span class="{css_cls}">{action_kr}</span> '
                f"<strong>{symbol_kr(symbol)}</strong> ₩{price:,.0f} · {reason} · 신뢰도 {confidence:.0%}"
                f"{wallet_display}"
                f'<br><span style="color:#666;font-size:0.8125rem">'
                f"{ts} · {regime_kr(regime)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.divider()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 4: 시장국면 — Regime 상태
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_regime:
    with st.spinner("데이터 로딩 중..."):
        try:
            regime = load_regime_report()
        except Exception:
            regime = None
            st.warning("시장국면 데이터를 불러오는 중 오류가 발생했습니다.")

    if regime is None:
        st.info("시장 국면 데이터가 없습니다.")
    else:
        market_regime = regime.get("market_regime", "unknown")
        badge_map = {
            "bull": ("regime-bull", "상승장 🐂"),
            "sideways": ("regime-sideways", "횡보장 ➡️"),
            "bear": ("regime-bear", "하락장 🐻"),
        }
        cls, label = badge_map.get(market_regime, ("regime-sideways", market_regime.upper()))
        st.markdown(f'<span class="regime-badge {cls}">{label}</span>', unsafe_allow_html=True)

        sym = regime.get("symbol", "?")
        st.caption(f"종목: {symbol_kr(sym)} · {regime.get('generated_at', '')[:19]}")

        # 모바일에서 CSS가 컬럼 스택 처리
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
# 탭 5: 운영리포트 — Drift / Promotion / 메모
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_operator:
    with st.spinner("데이터 로딩 중..."):
        try:
            drift = load_drift_report()
        except Exception:
            drift = None
            st.warning("드리프트 데이터를 불러오는 중 오류가 발생했습니다.")

        try:
            promo = load_promotion_gate()
        except Exception:
            promo = None
            st.warning("승격 판정 데이터를 불러오는 중 오류가 발생했습니다.")

        try:
            memo = load_daily_memo()
        except Exception:
            memo = None
            st.warning("일일 메모를 불러오는 중 오류가 발생했습니다.")

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
        st.info("드리프트 데이터가 없습니다.")
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
        st.info("승격 판정 데이터가 없습니다.")
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
        st.info("일일 메모가 없습니다.")
    else:
        st.markdown(memo)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 6: 성과 — 백테스트 기준선 + 일간 성과 + 가격 차트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_perf:
    with st.spinner("데이터 로딩 중..."):
        try:
            runs = load_strategy_runs()
        except Exception:
            runs = None
            st.warning("전략 실행 데이터를 불러오는 중 오류가 발생했습니다.")

        try:
            baseline = load_backtest_baseline()
        except Exception:
            baseline = None
            st.warning("백테스트 데이터를 불러오는 중 오류가 발생했습니다.")

        try:
            daily_perf = load_daily_performance()
        except Exception:
            daily_perf = None
            st.warning("일간 성과 데이터를 불러오는 중 오류가 발생했습니다.")

    # 백테스트 기준선
    if baseline is None:
        st.info("백테스트 데이터가 없습니다.")
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
        st.info("성과 데이터가 없습니다.")
    elif daily_perf:
        st.markdown("#### 일간 성과")
        c1, c2, c3 = st.columns(3)
        c1.metric("실현 수익률", f"{daily_perf.get('realized_return_pct', 0):.2%}")
        c2.metric("승률", f"{daily_perf.get('win_rate', 0):.0%}")
        c3.metric("시가평가 자산", f"₩{daily_perf.get('mark_to_market_equity', 0):,.0f}")

    # 판단 시점 + 현재가 비교 가격 차트
    if runs:
        st.markdown("#### 가격 추이 및 시그널")
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
            # 시그널별 색상 + 크기 (모바일 터치 타겟 위해 크기 유지)
            marker_colors = []
            marker_sizes = []
            hover_texts = []
            ACTION_KR_CHART = {"buy": "매수", "sell": "매도", "hold": "관망"}
            for i, a in enumerate(actions):
                if a == "buy":
                    marker_colors.append("#4ade80")
                    marker_sizes.append(14)
                elif a == "sell":
                    marker_colors.append("#f87171")
                    marker_sizes.append(14)
                else:
                    marker_colors.append("#6b7280")
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
                    line=dict(color="#60a5fa", width=2),
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
                    name="매수", marker=dict(size=16, color="#4ade80", symbol="triangle-up"),
                ))
            if sell_ts:
                fig.add_trace(go.Scatter(
                    x=sell_ts, y=sell_pr, mode="markers",
                    name="매도", marker=dict(size=16, color="#f87171", symbol="triangle-down"),
                ))

            fig.update_layout(
                template="plotly_dark",
                margin=dict(l=8, r=8, t=32, b=8),
                height=280,
                yaxis_title="가격 (KRW)",
                xaxis_title="",
                font=dict(size=11),
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)
    elif not baseline and not daily_perf:
        st.info("성과 데이터가 없습니다.")

# ── 푸터 ──────────────────────────────────────────────────
st.divider()
now_str = datetime.now(_UTC).strftime("%Y-%m-%d %H:%M UTC")
st.caption(f"마지막 새로고침: {now_str}")
