"""crypto-trader dashboard — card-based dark dashboard.

Layout (전부 카드, 60초마다 부분 갱신):
  0. BTC 시장 국면  +  데몬 상태   (최상단 2-카드)
  1. 손익 요약 (4 metric)
  2. 현재 포지션 (포지션별 카드)
  3. 활성 지갑 (지갑별 카드 그리드)
  4. 최근 거래 (간결한 리스트)

데이터 섹션은 st.fragment(run_every=60)으로 1분마다 부분 갱신.
"""

from __future__ import annotations

import html
import json
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

import dashboard.data as data_mod  # noqa: E402
from dashboard.auth import require_auth  # noqa: E402
from dashboard.styles import inject_css  # noqa: E402

_UTC = timezone.utc  # noqa: UP017


def _noop_fragment(*args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return func

    return decorator


_fragment = cast(
    Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]],
    getattr(st, "fragment", _noop_fragment),
)


def _load_data_attr(name: str, default: Any) -> Any:
    return getattr(data_mod, name, default)


FEAR_GREED_ZONES = _load_data_attr("FEAR_GREED_ZONES", [])
load_all_paper_trades = _load_data_attr("load_all_paper_trades", lambda: [])
load_health = _load_data_attr("load_health", lambda: {})
load_pnl_report = _load_data_attr("load_pnl_report", lambda: {})
load_recent_rotations = _load_data_attr("load_recent_rotations", lambda window_hours=24: {})
load_trading_mode = _load_data_attr("load_trading_mode", lambda: ("UNKNOWN", "mode-paper"))
load_live_pnl_summary = _load_data_attr(
    "load_live_pnl_summary",
    lambda: {
        "total_realized_pnl": 0.0,
        "total_unrealized_pnl": 0.0,
        "total_pnl": 0.0,
        "total_trades": 0,
        "open_position_count": 0,
        "today_realized_pnl": 0.0,
        "today_trade_count": 0,
        "total_gross_position_value": 0.0,
        "capital_utilization_pct": 0.0,
        "portfolio_return_pct": 0.0,
        "generated_at": None,
        "realized_source": "unknown",
        "unrealized_source": "unknown",
    },
)
load_capital_utilization_diagnostics = _load_data_attr(
    "load_capital_utilization_diagnostics",
    lambda: {
        "utilization_pct": 0.0,
        "utilization_label": "알 수 없음",
        "gross_position_value": 0.0,
        "idle_capital": 0.0,
        "idle_wallet_count": 0,
        "active_wallet_count": 0,
        "notes": [],
    },
)
load_positions = _load_data_attr("load_positions", lambda: {})
load_regime_panel_data = _load_data_attr(
    "load_regime_panel_data",
    lambda: {"available": False},
)
load_regime_report = _load_data_attr("load_regime_report", lambda: {})
load_signal_monitor_data = _load_data_attr(
    "load_signal_monitor_data",
    lambda: {
        "wallet_signals": [],
        "timeline": [],
        "active_buy_count": 0,
        "active_sell_count": 0,
        "active_hold_count": 0,
    },
)
load_wallet_analytics = _load_data_attr("load_wallet_analytics", lambda: {})
symbol_kr = _load_data_attr("symbol_kr", lambda value: str(value))

st.set_page_config(page_title="크립토 트레이더", layout="wide")

# Cloudflare 캐시 방지
st.markdown(
    '<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">'
    '<meta http-equiv="Pragma" content="no-cache">'
    '<meta http-equiv="Expires" content="0">',
    unsafe_allow_html=True,
)

require_auth()
inject_css()

# 추가 카드/그리드 스타일 — 다크 테마 일관
st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 22px !important;
        padding: 1.1rem 1.25rem !important;
        margin-bottom: 1rem !important;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.22);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] h2,
    div[data-testid="stVerticalBlockBorderWrapper"] h3 {
        margin-top: 0 !important;
        margin-bottom: 0.5rem !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMetric"] {
        background: var(--bg-card-strong) !important;
    }
    /* metric 값 대비 강화 — 회색 → 흰색 */
    [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-weight: 800 !important;
        font-size: 1.5rem !important;
        text-shadow: 0 1px 0 rgba(0,0,0,0.4);
    }
    [data-testid="stMetricDelta"] {
        color: var(--text-muted) !important;
        font-weight: 600 !important;
    }
    /* 상단 카드 — caption 영역 높이 통일해서 metric row 정렬 */
    .topcard-caption {
        min-height: 3.2rem;
        font-size: 0.78rem;
        color: var(--text-muted);
        line-height: 1.55;
        margin-bottom: 0.35rem;
    }
    /* 카드 클릭(앵커) 스타일 정리 */
    a.ct-card-link, a.ct-card-link:visited {
        text-decoration: none !important;
        color: inherit !important;
        display: block;
    }
    a.ct-card-link:hover .ct-card {
        border-color: var(--blue) !important;
    }
    /* 페이징 버튼 컴팩트화 */
    div[data-testid="stButton"] > button {
        min-height: 30px !important;
        height: 30px !important;
        padding: 0.1rem 0.4rem !important;
        font-size: 0.8rem !important;
        background: var(--bg-card-strong) !important;
        border: 1px solid var(--border-card) !important;
        color: var(--text-primary) !important;
        border-radius: 8px !important;
    }
    div[data-testid="stButton"] > button:hover:not(:disabled) {
        border-color: var(--blue) !important;
        background: var(--bg-card-hover) !important;
    }
    div[data-testid="stButton"] > button:disabled {
        opacity: 0.35 !important;
    }
    h1 {
        background: linear-gradient(135deg, #77b8ff 0%, #42d9c8 60%, #61f2a2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 800 !important;
    }
    hr { display: none !important; }

    /* ── 반응형 컨테이너 ───────────────────────────────────── */
    /* 기본(데스크탑): 가로 거의 다 사용 */
    .block-container {
        max-width: 1800px !important;
        width: 100% !important;
        padding: 1.4rem 2rem 2.4rem !important;
    }
    /* QHD 이상 */
    @media (min-width: 2000px) {
        .block-container {
            max-width: 1900px !important;
            padding: 1.6rem 2.4rem 3rem !important;
        }
    }
    /* 일반 노트북 */
    @media (max-width: 1600px) {
        .block-container { padding: 1.2rem 1.4rem 2.4rem !important; }
    }
    /* 태블릿 가로 */
    @media (max-width: 1180px) {
        .block-container { padding: 1rem 1rem 2rem !important; }
    }
    /* 태블릿 세로 */
    @media (max-width: 900px) {
        .block-container { padding: 0.85rem 0.85rem 1.6rem !important; }
        .ct-card { padding: 0.95rem 1rem !important; }
    }
    /* 모바일 */
    @media (max-width: 640px) {
        .block-container { padding: 0.6rem 0.55rem 1.4rem !important; }
        h1 { font-size: 1.5rem !important; }
        .ct-card .name { font-size: 1rem !important; }
        .ct-card .kv { font-size: 0.88rem !important; }
        .ct-trade-row { font-size: 0.85rem !important; padding: 0.6rem 0.7rem !important; }
        .ct-trade-row, .ct-trade-head {
            grid-template-columns: 1.3fr 1fr 1.4fr 1fr !important;
            gap: 0.4rem !important;
        }
        [data-testid="stMetricValue"] { font-size: 1.2rem !important; }
        .topcard-caption { min-height: auto !important; }
    }

    /* ── 반응형 카드 그리드 ─────────────────────────────────── */
    .ct-grid {
        /* minmax는 화면 크기에 따라 자동 조정되지만, 모바일에서 더 작게 */
    }
    @media (max-width: 900px) {
        .ct-grid {
            grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)) !important;
            gap: 0.7rem !important;
        }
    }
    @media (max-width: 640px) {
        .ct-grid {
            grid-template-columns: 1fr !important;
            gap: 0.6rem !important;
        }
    }

    /* ── 모바일에서 정렬 셀렉트박스 풀폭 ────────────────────── */
    @media (max-width: 640px) {
        div[data-testid="stSelectbox"] {
            margin-top: 0.3rem !important;
            margin-bottom: 0.3rem !important;
        }
    }

    /* 카드 그리드 (포지션/지갑) */
    .ct-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
        gap: 0.95rem;
        margin-top: 0.6rem;
    }
    .ct-card {
        background: var(--bg-card-strong);
        border: 1px solid var(--border-card);
        border-radius: 18px;
        padding: 1.15rem 1.25rem;
        transition: border-color 0.18s ease, transform 0.18s ease;
    }
    .ct-card:hover {
        border-color: var(--border-card-hover);
        transform: translateY(-1px);
    }
    .ct-card .head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 0.5rem;
        margin-bottom: 0.7rem;
    }
    .ct-card .name {
        font-weight: 700;
        font-size: 1.1rem;
        color: var(--text-primary);
    }
    .ct-card .sub {
        font-size: 0.85rem;
        color: var(--text-muted);
        margin-top: 0.15rem;
    }
    .ct-card .kv {
        display: flex;
        justify-content: space-between;
        font-size: 0.95rem;
        margin: 0.3rem 0;
    }
    .ct-card .kv .k { color: var(--text-muted); }
    .ct-card .kv .v {
        color: var(--text-primary);
        font-family: var(--mono);
        font-variant-numeric: tabular-nums;
    }
    .pnl-pos { color: var(--green) !important; }
    .pnl-neg { color: var(--red) !important; }
    .chip {
        display: inline-block;
        padding: 0.15rem 0.55rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
    }
    .chip-long { background: var(--green-bg); color: var(--green); }
    .chip-short { background: var(--red-bg); color: var(--red); }
    .chip-new {
        background: rgba(119, 184, 255, 0.18);
        color: var(--blue);
        border: 1px solid rgba(119, 184, 255, 0.35);
    }
    .ct-rotation {
        font-size: 0.74rem;
        color: var(--text-muted);
        margin-top: 0.4rem;
        padding-top: 0.4rem;
        border-top: 1px dashed var(--border-card);
    }
    .ct-rotation .out {
        text-decoration: line-through;
        color: var(--red);
        opacity: 0.7;
    }
    .ct-rotation .in {
        color: var(--blue);
        font-weight: 700;
    }

    /* 타이틀 + 모드 배지 */
    .ct-titlebar {
        display: flex;
        align-items: center;
        gap: 0.85rem;
        flex-wrap: wrap;
        margin-bottom: 0.2rem;
    }
    .ct-titlebar h1 { margin: 0 !important; }
    .mode-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.45rem 0.95rem;
        border-radius: 999px;
        font-weight: 800;
        font-size: 0.85rem;
        letter-spacing: 0.04em;
    }
    .mode-paper {
        background: var(--yellow-bg);
        color: var(--yellow);
        border: 1px solid rgba(255, 199, 95, 0.45);
    }
    /* status line (countdown + reload icon) */
    .ct-statusline {
        font-size: 0.82rem;
        color: var(--text-muted);
        margin: 0.2rem 0 0.6rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    a.ct-reload {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 26px;
        border-radius: 8px;
        background: var(--bg-card-strong);
        border: 1px solid var(--border-card);
        text-decoration: none !important;
        font-size: 0.85rem;
        line-height: 1;
        transition: border-color 0.15s, transform 0.15s;
    }
    a.ct-reload:hover {
        border-color: var(--blue);
        transform: rotate(90deg);
    }

    /* selectbox 다크 테마 + 컴팩트 (정렬 셀렉터) */
    div[data-testid="stSelectbox"] {
        margin-bottom: 0 !important;
    }
    div[data-testid="stSelectbox"] > div > div {
        background: var(--bg-card-strong) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 10px !important;
        min-height: 32px !important;
        font-size: 0.78rem !important;
        color: var(--text-primary) !important;
    }
    div[data-testid="stSelectbox"] > div > div:hover {
        border-color: var(--blue) !important;
    }
    div[data-testid="stSelectbox"] svg {
        fill: var(--text-muted) !important;
    }

    .mode-live {
        background: var(--red-bg);
        color: var(--red);
        border: 1px solid rgba(255, 125, 142, 0.55);
        box-shadow: 0 0 14px rgba(255, 125, 142, 0.35);
    }

    /* 거래 리스트 (테이블 대체) */
    .ct-trade-list { display: flex; flex-direction: column; gap: 0.35rem; }
    .ct-trade-row {
        display: grid;
        grid-template-columns: 1.4fr 1.2fr 1.6fr 1.4fr;
        gap: 0.8rem;
        align-items: center;
        padding: 0.85rem 1.1rem;
        background: var(--bg-card-strong);
        border: 1px solid var(--border-card);
        border-radius: 14px;
    }
    .ct-trade-row .cell { color: var(--text-primary); font-size: 0.95rem; }
    /* 강조: 종목명 */
    .ct-trade-row .cell-symbol {
        font-size: 1.1rem;
        font-weight: 800;
        color: var(--text-primary);
    }
    /* 강조: 손익 (오른쪽 끝) */
    .ct-trade-row .cell-pnl {
        font-size: 1.05rem;
        font-weight: 800;
        font-family: var(--mono);
        font-variant-numeric: tabular-nums;
        text-align: right;
    }
    /* 부가정보: 시각 (가장 작게) */
    .ct-trade-row .muted {
        color: var(--text-muted);
        font-size: 0.75rem;
        margin-top: 0.15rem;
    }
    /* 지갑: 명확하게 강조 */
    .ct-trade-row .cell-wallet {
        color: var(--text-primary);
        font-size: 1rem;
        font-weight: 600;
    }
    .ct-trade-row .num {
        font-family: var(--mono);
        font-variant-numeric: tabular-nums;
        text-align: right;
    }
    .ct-trade-head {
        display: grid;
        grid-template-columns: 1.4fr 1.2fr 1.6fr 1.2fr;
        gap: 0.7rem;
        padding: 0.4rem 1rem;
        font-size: 0.82rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .ct-trade-head .num { text-align: right; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ───────────── helpers ─────────────
def fmt_won(v: float | int) -> str:
    return f"₩{int(round(float(v))):,}"


def fmt_qty(v: float) -> str:
    """Smart quantity formatting — strip excessive decimals."""
    v = float(v)
    if v == 0:
        return "0"
    if abs(v) >= 100:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:,.4f}"
    return f"{v:.6f}".rstrip("0").rstrip(".")


def pnl_class(v: float) -> str:
    return "pnl-pos" if float(v) >= 0 else "pnl-neg"


def esc(s: object) -> str:
    return html.escape(str(s))


STRATEGY_INFO: dict[str, dict[str, str]] = {
    "vpin": {
        "title": "VPIN — Volume-synchronized PIN",
        "summary": "거래량 기반 정보 흐름 지표(VPIN)가 임계 이상일 때 매수 진입.",
        "detail": (
            "거래량을 buy/sell volume bucket으로 나눠 정보 비대칭(toxic flow) "
            "수준을 측정. VPIN이 높을수록 한쪽 방향으로 매물이 쏠리고 있다는 "
            "신호 — 추세 발생 직전에 자주 나타남.\n\n"
            "진입: VPIN > 임계 + 추가 필터(BTC 레짐, 변동성 등) 통과 시\n"
            "청산: ATR 기반 trailing stop / take-profit 또는 시간 만료"
        ),
    },
    "momentum": {
        "title": "Momentum — 추세 추종",
        "summary": "단기·중기 모멘텀 지표가 임계를 넘으면 진입, 약화 시 청산.",
        "detail": (
            "lookback 기간 수익률 / RSI / MACD 등을 조합해 추세의 강도를 판정. "
            "강한 상승 추세에 올라타고, 추세 약화 신호가 나오면 빠르게 빠져나옴.\n\n"
            "진입: 모멘텀 점수 > entry_threshold\n"
            "청산: 모멘텀 < exit_threshold 또는 stop-loss"
        ),
    },
    "volume_spike": {
        "title": "Volume Spike — 거래량 급증",
        "summary": "평균 대비 N배 거래량 급증이 발생하면 단기 진입.",
        "detail": (
            "최근 평균 거래량 대비 spike ratio가 임계를 넘으면 단발적인 매수 압력 "
            "발생으로 보고 진입. 보통 ATR로 손절·익절을 좁게 설정해 빠른 회전.\n\n"
            "진입: vol > avg_vol × multiplier 그리고 양봉/RS 필터\n"
            "청산: 짧은 보유 후 익절 또는 stop"
        ),
    },
    "bb_squeeze_independent": {
        "title": "Bollinger Squeeze — 볼린저 변동성 압축 후 돌파",
        "summary": "변동성이 충분히 수축한 뒤 밴드 돌파 시 추세 진입.",
        "detail": (
            "볼린저 밴드 폭이 최근 N봉 중 최저 수준으로 좁아지는 'squeeze' 상태를 "
            "찾고, squeeze 해제와 함께 가격이 상단 밴드를 돌파하면 진입.\n\n"
            "진입: bandwidth < pctile(N) AND close > upper_band\n"
            "청산: 중심선 회귀 또는 stop"
        ),
    },
    "bb_mr": {
        "title": "Bollinger Mean Reversion — 평균 회귀",
        "summary": "가격이 하단 밴드 터치 후 평균 복귀를 노리는 전략.",
        "detail": (
            "강한 하락으로 하단 밴드를 벗어나면 매수, 중심선(SMA)으로 평균 회귀를 "
            "기다림. BEAR 레짐에서는 비활성(false signal 방지).\n\n"
            "진입: close < lower_band AND RSI < oversold\n"
            "청산: close ≥ middle_band 또는 stop"
        ),
    },
    "accumulation_breakout": {
        "title": "Accumulation Breakout — 매집 후 돌파",
        "summary": "alpha-scanner가 발굴한 매집(accumulation) 종목을 돌파 시 매수.",
        "detail": (
            "market_scan_loop가 매일 alpha 점수 상위 종목을 골라 wallet에 자동 "
            "할당. 그 종목이 박스권 상단을 돌파(또는 RS/거래량 조건 충족)하면 진입.\n\n"
            "진입: alpha_score ≥ threshold AND breakout 조건\n"
            "청산: trailing stop / time decay"
        ),
    },
    "stealth_3gate": {
        "title": "Stealth 3-Gate — 3중 게이트 진입",
        "summary": "BTC 레짐 + BTC stealth + 알트 품질 3개 게이트 모두 통과 시 진입.",
        "detail": (
            "검증된 3-게이트 진입 룰 (BTC stealth 92.9% 승률):\n"
            "1) BTC 레짐 = BULL\n"
            "2) BTC stealth signal = ON (조용한 매집 감지)\n"
            "3) 알트 quality filter (RS·거래량·변동성) 통과\n\n"
            "BEAR 레짐에선 자동 차단."
        ),
    },
    "vbreak": {
        "title": "Volatility Breakout — 변동성 돌파",
        "summary": "Larry Williams 변동성 돌파 — 전일 range × k를 넘으면 진입.",
        "detail": (
            "오늘 시가 + (전일 high - low) × k 가격을 돌파하면 매수. 짧은 보유 "
            "후 종가 청산. 단순하지만 강한 추세장에서 잘 작동.\n\n"
            "진입: price > open_today + range_yesterday × k\n"
            "청산: 종가 또는 stop"
        ),
    },
}


def get_strategy_info(strategy_type: str) -> dict[str, str]:
    if not strategy_type:
        return {"title": "?", "summary": "전략 정보 없음", "detail": ""}
    # 부분 매칭 (e.g. bb_squeeze_independent → bb_squeeze_independent)
    if strategy_type in STRATEGY_INFO:
        return STRATEGY_INFO[strategy_type]
    for key, info in STRATEGY_INFO.items():
        if strategy_type.startswith(key) or key in strategy_type:
            return info
    return {
        "title": strategy_type,
        "summary": "이 전략의 한국어 설명이 아직 등록되지 않았어요.",
        "detail": "",
    }


def fmt_relative_time(ts_dt: datetime) -> str:
    sec = max(0, (datetime.now(_UTC) - ts_dt).total_seconds())
    if sec < 60:
        return f"{int(sec)}초 전"
    if sec < 3600:
        return f"{int(sec / 60)}분 전"
    if sec < 86400:
        return f"{int(sec / 3600)}시간 전"
    return f"{int(sec / 86400)}일 전"


def _empty(message: str) -> None:
    st.info(message)


def _rerun_fragment() -> None:
    try:
        st.rerun(scope="fragment")
    except TypeError:
        st.rerun()


def render_header() -> None:
    mode_label, mode_class = load_trading_mode()
    loaded_at = datetime.now(_UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(
        f'<div class="ct-titlebar">'
        f'<h1>⚡ crypto-trader</h1>'
        f'<span class="mode-badge {mode_class}">{mode_label}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    cd_left, cd_right = st.columns([20, 1])
    with cd_left:
        @_fragment(run_every=1)
        def render_countdown() -> None:
            import time as _t

            if "_dash_start_t" not in st.session_state:
                st.session_state._dash_start_t = _t.time()
            elapsed = int(_t.time() - st.session_state._dash_start_t)
            remaining = 60 - (elapsed % 60)
            st.markdown(
                f'<div class="ct-statusline">'
                f"최초 로드: {loaded_at}  ·  다음 자동 갱신까지 "
                f"<b style=\"color:var(--blue);\">{remaining}초</b>"
                f"</div>",
                unsafe_allow_html=True,
            )

        render_countdown()
    with cd_right:
        if st.button("🔄", key="reload_inline", help="즉시 새로고침"):
            st.cache_data.clear()
            st.session_state._dash_start_t = datetime.now().timestamp()
            st.rerun()


# ───────────── 0. 시장 국면 + 데몬 상태 ─────────────
@_fragment(run_every=60)
def render_regime_and_health() -> None:
    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            st.subheader("🌐 BTC 시장 국면")
            st.markdown(
                '<div class="topcard-caption">'
                "시장 국면(레짐) = BTC가 상승장/하락장/횡보 중 어디인지. "
                "모든 전략의 진입·보유 강도를 자동 조절하는 기준이에요."
                "</div>",
                unsafe_allow_html=True,
            )
            regime = load_regime_report() or {}
            regime_kr = {
                "BULL": "📈 상승장",
                "BEAR": "📉 하락장",
                "SIDEWAYS": "➖ 횡보",
            }
            raw_regime = str(regime.get("market_regime", "?")).upper()
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("국면", regime_kr.get(raw_regime, raw_regime))
            rc2.metric(
                "단기 수익률",
                f"{float(regime.get('short_return_pct', 0) or 0):.2f}%",
            )
            rc3.metric(
                "장기 수익률",
                f"{float(regime.get('long_return_pct', 0) or 0):.2f}%",
            )
            reasons = regime.get("reasons") or []
            if reasons:
                st.caption(" · ".join(str(r) for r in reasons[:3]))

    with right:
        with st.container(border=True):
            st.subheader("⚙️ 데몬 상태")
            st.markdown(
                '<div class="topcard-caption">'
                "데몬(자동매매 프로세스)이 정상 동작 중인지, 최근 오류 여부."
                "</div>",
                unsafe_allow_html=True,
            )
            h = load_health() or {}
            status = h.get("status") or ("정상" if h.get("success") else "알 수 없음")
            hc1, hc2, hc3 = st.columns(3)
            hc1.metric("상태", str(status))
            hc2.metric("연속 실패", int(h.get("failure_streak", 0) or 0))
            hc3.metric("보유 포지션", int(h.get("open_positions", 0) or 0))
            err = h.get("last_error")
            if err:
                st.caption(f"마지막 오류: {err}")

# ───────────── 1. 손익 요약 ─────────────
@_fragment(run_every=60)
def render_pnl_summary() -> None:
    with st.container(border=True):
        st.subheader("💰 손익 요약")
        st.caption("paper(모의) 거래 기준. 실현=청산 완료, 미실현=보유 중 평가손익.")

        pnl_summary = load_live_pnl_summary() or {}
        realized = float(pnl_summary.get("total_realized_pnl", 0.0) or 0.0)
        unrealized = float(pnl_summary.get("total_unrealized_pnl", 0.0) or 0.0)
        total_trades = int(pnl_summary.get("total_trades", 0) or 0)
        today_pnl = float(pnl_summary.get("today_realized_pnl", 0.0) or 0.0)
        trades_today = int(pnl_summary.get("today_trade_count", 0) or 0)

        utilization = float(pnl_summary.get("capital_utilization_pct", 0.0) or 0.0)
        total = realized + unrealized
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("오늘 실현 손익", fmt_won(today_pnl), f"{trades_today} 거래")
        c2.metric("누적 실현 손익", fmt_won(realized), f"{total_trades} 거래")
        c3.metric(
            "현재 미실현 손익",
            fmt_won(unrealized),
            f"{pnl_summary.get('open_position_count', 0)} 포지션",
        )
        c4.metric("총 손익", fmt_won(total), "실현 + 미실현")
        c5.metric("자본 활용률", f"{utilization:.1f}%", "포지션 평가액 / equity")
        st.caption(
            f"갱신: {datetime.now().strftime('%H:%M:%S')} | "
            f"실현소스: {pnl_summary.get('realized_source', 'unknown')} | "
            f"미실현소스: {pnl_summary.get('unrealized_source', 'unknown')}"
        )

# ───────────── 2. 현재 포지션 ─────────────
@_fragment(run_every=60)
def render_positions() -> None:
    with st.container(border=True):
        head_l, head_r = st.columns([5, 1], vertical_alignment="bottom")
        with head_l:
            st.subheader("📊 현재 포지션")
            st.caption("daemon이 지금 보유 중인 모든 포지션과 실시간 평가손익.")
        positions = load_positions() or {}
        pos_list = positions.get("positions") or []

        # Overlay live prices from Upbit
        if pos_list:
            from dashboard.data import fetch_live_prices

            symbols = tuple({str(p.get("symbol", "")) for p in pos_list if p.get("symbol")})
            live = fetch_live_prices(symbols)
            if live:
                for p in pos_list:
                    sym = str(p.get("symbol", ""))
                    if sym in live:
                        lp = live[sym]
                        p["market_price"] = lp
                        entry = float(p.get("entry_price", 0) or 0)
                        qty = float(p.get("qty", 0) or 0)
                        if entry > 0:
                            p["unrealized_pnl"] = (lp - entry) * qty
                            p["unrealized_pnl_pct"] = (lp - entry) / entry
                            p["marked_value"] = lp * qty
        sort_opts = {
            "수익률 % ↓": ("unrealized_pnl_pct", True),
            "수익률 % ↑": ("unrealized_pnl_pct", False),
            "손익 금액 ↓": ("unrealized_pnl", True),
            "손익 금액 ↑": ("unrealized_pnl", False),
        }
        with head_r:
            choice = st.selectbox(
                "정렬",
                list(sort_opts.keys()),
                key="pos_sort",
                label_visibility="collapsed",
            )
        if not pos_list:
            st.info("열린 포지션 없음")
            return
        key, desc = sort_opts[choice]
        pos_list = sorted(
            pos_list, key=lambda x: float(x.get(key, 0) or 0), reverse=desc
        )

        cards: list[str] = []
        for p in pos_list:
            wallet_raw = str(p.get("wallet", ""))
            wallet = esc(wallet_raw.replace("_wallet", ""))
            anchor = esc(wallet_raw)  # 같은 지갑 카드의 id로 점프
            symbol = esc(symbol_kr(str(p.get("symbol", ""))))
            qty = fmt_qty(float(p.get("qty", 0) or 0))
            entry = fmt_won(float(p.get("entry_price", 0) or 0))
            now_p = fmt_won(float(p.get("market_price", 0) or 0))
            upnl = float(p.get("unrealized_pnl", 0) or 0)
            upnl_pct = float(p.get("unrealized_pnl_pct", 0) or 0) * 100
            value = fmt_won(float(p.get("marked_value", 0) or 0))
            cls = pnl_class(upnl)
            cards.append(f"""
<a class="ct-card-link" href="#wallet-{anchor}" title="이 지갑 보기">
<div class="ct-card">
  <div class="head">
    <div>
      <div class="name">{symbol}</div>
      <div class="sub">{wallet} ↗</div>
    </div>
    <div class="num {cls}" style="font-weight:700;">{fmt_won(upnl)}</div>
  </div>
  <div class="kv"><span class="k">진입가</span><span class="v">{entry}</span></div>
  <div class="kv"><span class="k">현재가</span><span class="v">{now_p}</span></div>
  <div class="kv"><span class="k">수량</span><span class="v">{qty}</span></div>
  <div class="kv"><span class="k">평가액</span><span class="v">{value}</span></div>
  <div class="kv"><span class="k">미실현 %</span>
    <span class="v {cls}">{upnl_pct:+.2f}%</span></div>
</div></a>""")
        st.markdown(f'<div class="ct-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

# ───────────── 3. 활성 지갑 ─────────────
@_fragment(run_every=60)
def render_wallets() -> None:
    with st.container(border=True):
        whead_l, whead_r = st.columns([5, 1], vertical_alignment="bottom")
        with whead_l:
            st.subheader("💼 활성 지갑")
            st.caption("전략별 지갑 현황. 거래수·승률·수익률·자본을 한눈에.")
        analytics = load_wallet_analytics() or {}
        wallets = analytics.get("wallets") or []
        wallet_sort_opts = {
            "수익률 % ↓": ("return_pct", True),
            "수익률 % ↑": ("return_pct", False),
            "실현 손익 ↓": ("realized_pnl", True),
            "실현 손익 ↑": ("realized_pnl", False),
            "활용률 ↓": ("capital_utilization_pct", True),
            "활용률 ↑": ("capital_utilization_pct", False),
        }
        with whead_r:
            wchoice = st.selectbox(
                "정렬",
                list(wallet_sort_opts.keys()),
                key="wallet_sort",
                label_visibility="collapsed",
            )
        if not wallets:
            st.caption("데이터 없음")
            return
        wkey, wdesc = wallet_sort_opts[wchoice]
        wallets = sorted(
            wallets, key=lambda x: float(x.get(wkey, 0) or 0), reverse=wdesc
        )

        cards: list[str] = []
        for w in wallets:
            name_raw = str(w.get("wallet_name") or w.get("name") or "")
            display = esc(str(w.get("display_name") or name_raw).replace("_wallet", ""))
            symbol = esc(str(w.get("symbol_display") or w.get("symbol") or ""))
            trades = int(w.get("trade_count", 0) or 0)
            wr = float(w.get("win_rate", 0) or 0) * 100
            ret = float(w.get("return_pct") or w.get("roi_pct") or 0)
            pnl = float(w.get("realized_pnl", 0) or 0)
            equity = float(w.get("equity", 0) or 0)
            gross_position_value = float(w.get("gross_position_value", 0) or 0)
            capital_utilization_pct = float(w.get("capital_utilization_pct", 0) or 0)
            theoretical_position_pct = float(w.get("theoretical_position_pct", 0) or 0)
            sizing_driver = esc(str(w.get("sizing_driver") or "-"))
            cls = pnl_class(ret)
            cards.append(f"""
<div class="ct-card">
  <div class="head">
    <div>
      <div class="name">{display}</div>
      <div class="sub">{symbol}</div>
    </div>
    <div class="num {cls}" style="font-weight:700;">{ret:+.2f}%</div>
  </div>
  <div class="kv"><span class="k">자본</span><span class="v">{fmt_won(equity)}</span></div>
  <div class="kv"><span class="k">점유액 / 활용률</span>
    <span class="v">{fmt_won(gross_position_value)} / {capital_utilization_pct:.1f}%</span></div>
  <div class="kv"><span class="k">이론상 1회 상한 / 요인</span>
    <span class="v">{theoretical_position_pct:.1f}% / {sizing_driver}</span></div>
  <div class="kv"><span class="k">실현 손익</span>
    <span class="v {pnl_class(pnl)}">{fmt_won(pnl)}</span></div>
  <div class="kv"><span class="k">거래수 / 승률</span>
    <span class="v">{trades} / {wr:.1f}%</span></div>
</div>""")
        st.markdown(f'<div class="ct-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

# ───────────── 4. 최근 거래 ─────────────
TRADES_PER_PAGE = 10


@_fragment(run_every=60)
def render_recent_trades() -> None:
    with st.container(border=True):
        st.subheader("🕒 최근 거래")
        st.caption(
            "매도 시각 기준 최신순. Upbit는 spot이라 모두 매수 진입 → 매도 종료예요."
        )
        trades = load_all_paper_trades() or []
        # 청산 완료된 거래만 (exit_time / closed_at 존재)
        trades_sorted = sorted(
            trades,
            key=lambda t: str(
                t.get("exit_time") or t.get("closed_at") or t.get("timestamp") or ""
            ),
            reverse=True,
        )
        total = len(trades_sorted)
        if total == 0:
            st.caption("거래 없음")
            return

        # 페이징
        if "trades_page" not in st.session_state:
            st.session_state.trades_page = 0
        max_page = max(0, (total - 1) // TRADES_PER_PAGE)
        if st.session_state.trades_page > max_page:
            st.session_state.trades_page = max_page
        page = st.session_state.trades_page
        start = page * TRADES_PER_PAGE
        end = start + TRADES_PER_PAGE
        page_trades = trades_sorted[start:end]

        rows: list[str] = [
            '<div class="ct-trade-head">'
            "<div>시각 / 종목</div>"
            "<div>지갑</div>"
            "<div class=\"num\">진입가 → 매도가</div>"
            "<div class=\"num\">손익 / 손익%</div>"
            "</div>"
        ]
        for t in page_trades:
            ts = esc(
                str(
                    t.get("exit_time")
                    or t.get("closed_at")
                    or t.get("timestamp")
                    or ""
                )[:19]
            )
            symbol = esc(symbol_kr(str(t.get("symbol", ""))))
            wallet = esc(str(t.get("wallet", "")).replace("_wallet", ""))
            entry_p = float(t.get("entry_price", 0) or 0)
            exit_p = float(t.get("exit_price", 0) or 0)
            # 호환: realized_pnl(구) 또는 pnl(현재)
            pnl = float(
                t.get("realized_pnl") if t.get("realized_pnl") is not None else (t.get("pnl") or 0)
            )
            # load_all_paper_trades가 이미 *100 해서 % 단위로 반환함
            pnl_pct_raw = (
                t.get("realized_pnl_pct")
                if t.get("realized_pnl_pct") is not None
                else (t.get("pnl_pct") or 0)
            )
            pnl_pct = float(pnl_pct_raw)
            cls = pnl_class(pnl)
            rows.append(f"""
<div class="ct-trade-row">
  <div class="cell cell-symbol">{symbol}<div class="muted">{ts}</div></div>
  <div class="cell cell-wallet">{wallet}</div>
  <div class="cell num">{fmt_won(entry_p)} → {fmt_won(exit_p)}</div>
  <div class="cell-pnl {cls}">{fmt_won(pnl)} / {pnl_pct:+.2f}%</div>
</div>""")
        st.markdown(
            f'<div class="ct-trade-list">{"".join(rows)}</div>',
            unsafe_allow_html=True,
        )

        # 페이지 컨트롤 — 가운데 정렬 (좌우 spacer)
        st.markdown(
            f'<div style="text-align:center;color:var(--text-muted);'
            f'font-size:0.8rem;margin:0.6rem 0 0.3rem;">'
            f"{start + 1}–{min(end, total)} / 총 {total}건"
            f"  ·  {page + 1}/{max_page + 1} 페이지"
            f"</div>",
            unsafe_allow_html=True,
        )
        spacer_l, b1, b2, b3, b4, spacer_r = st.columns([4, 1, 1, 1, 1, 4])
        with b1:
            if st.button("⏮", key="t_first", disabled=page == 0,
                         use_container_width=True):
                st.session_state.trades_page = 0
                _rerun_fragment()
        with b2:
            if st.button("◀", key="t_prev", disabled=page == 0,
                         use_container_width=True):
                st.session_state.trades_page = max(0, page - 1)
                _rerun_fragment()
        with b3:
            if st.button("▶", key="t_next", disabled=page >= max_page,
                         use_container_width=True):
                st.session_state.trades_page = min(max_page, page + 1)
                _rerun_fragment()
        with b4:
            if st.button("⏭", key="t_last", disabled=page >= max_page,
                         use_container_width=True):
                st.session_state.trades_page = max_page
                _rerun_fragment()

def _render_regime_panel(regime_data: dict[str, Any]) -> None:
    if not regime_data.get("available"):
        _empty("매크로 레짐 데이터가 없습니다.")
        return

    cols = st.columns(4)
    cols[0].metric(
        "전체 레짐",
        str(regime_data.get("overall_regime_label") or regime_data.get("overall_regime") or "-"),
    )
    cols[1].metric(
        "신뢰도",
        f"{float(regime_data.get('overall_confidence', 0.0) or 0.0) * 100:.0f}%",
    )
    cols[2].metric(
        "포지션 배율",
        f"{float(regime_data.get('position_multiplier', 1.0) or 1.0):.2f}x",
    )
    cols[3].metric(
        "정렬",
        str(regime_data.get("alignment") or "unknown"),
        str(regime_data.get("local_regime_label") or ""),
    )
    reasons = regime_data.get("multiplier_reasons") or []
    if reasons:
        st.caption(" · ".join(str(reason) for reason in reasons))


def _render_fear_greed_gauge(regime_data: dict[str, Any]) -> None:
    fg_value = regime_data.get("fear_greed_index")
    if fg_value is None:
        _empty("Fear & Greed 인덱스 데이터가 없습니다.")
        return

    steps = [
        {"range": [low, high], "color": color}
        for low, high, _label, color in FEAR_GREED_ZONES
    ]
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=fg_value,
        title={
            "text": f"Fear & Greed · {regime_data.get('fear_greed_label', '')}",
            "font": {"size": 14},
        },
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#edf5fb"},
            "steps": steps,
        },
    ))
    fig.update_layout(height=220, margin={"l": 10, "r": 10, "t": 40, "b": 10})
    st.plotly_chart(fig, width="stretch")


def _render_signal_monitor(monitor: dict[str, Any]) -> None:
    wallet_signals = monitor.get("wallet_signals") or []
    if not wallet_signals:
        _empty("시그널 데이터가 없습니다. 데몬이 실행 중인지 확인하세요.")
        return

    cols = st.columns(4)
    cols[0].metric("활성 지갑", f"{len(wallet_signals)}")
    cols[1].metric("매수", f"{int(monitor.get('active_buy_count', 0) or 0)}")
    cols[2].metric("매도", f"{int(monitor.get('active_sell_count', 0) or 0)}")
    cols[3].metric("관망", f"{int(monitor.get('active_hold_count', 0) or 0)}")

    rows = [
        {
            "신뢰도": (
                f"{float(sig_confidence) * 100:.0f}%"
            ),
            "지갑": str(sig.get("display_name") or sig.get("wallet_name") or "-"),
            "심볼": str(sig.get("symbol_display") or sig.get("symbol") or "-"),
            "액션": str(sig.get("action") or sig.get("signal_action") or "-").upper(),
            "레짐": str(sig.get("regime_label") or sig.get("market_regime") or "-"),
            "이유": str(sig.get("reason") or sig.get("signal_reason") or "-")[:80],
            "시간": str(sig.get("timestamp") or sig.get("recorded_at") or "-")[:19],
        }
        for sig in wallet_signals[:30]
        for sig_confidence in [
            sig.get("confidence", sig.get("signal_confidence", 0.0)) or 0.0
        ]
    ]
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_portfolio_risk_tab() -> None:
    pnl_summary = load_live_pnl_summary() or {}
    utilization_diag = load_capital_utilization_diagnostics() or {}
    analytics = load_wallet_analytics() or {}
    wallets = analytics.get("wallets") or []

    cols = st.columns(5)
    cols[0].metric(
        "누적 실현 손익",
        fmt_won(float(pnl_summary.get("total_realized_pnl", 0.0) or 0.0)),
    )
    cols[1].metric("열린 포지션", int(pnl_summary.get("open_position_count", 0) or 0))
    cols[2].metric(
        "미실현 손익",
        fmt_won(float(pnl_summary.get("total_unrealized_pnl", 0.0) or 0.0)),
    )
    cols[3].metric(
        "자본 활용률",
        f"{float(pnl_summary.get('capital_utilization_pct', 0.0) or 0.0):.1f}%",
        fmt_won(float(pnl_summary.get("total_gross_position_value", 0.0) or 0.0)),
    )
    cols[4].metric("활성 지갑", len(wallets))

    notes = utilization_diag.get("notes") or []
    if notes:
        st.caption(" | ".join(str(note) for note in notes))
    underutilized_wallets = utilization_diag.get("underutilized_wallets") or []
    if underutilized_wallets:
        st.markdown("### 저활용 지갑")
        st.dataframe(
            [
                {
                    "지갑": str(wallet.get("display_name") or wallet.get("wallet_name") or "-"),
                    "심볼": str(wallet.get("symbol_display") or "-"),
                    "활용률": f"{float(wallet.get('capital_utilization_pct', 0.0) or 0.0):.1f}%",
                    "이론상 1회 상한": (
                        f"{float(wallet.get('theoretical_position_pct', 0.0) or 0.0):.1f}%"
                    ),
                    "제한 요인": str(wallet.get("sizing_driver") or "-"),
                    "점유액": fmt_won(float(wallet.get("gross_position_value", 0.0) or 0.0)),
                    "자본": fmt_won(float(wallet.get("equity", 0.0) or 0.0)),
                    "실현 손익": fmt_won(float(wallet.get("realized_pnl", 0.0) or 0.0)),
                    "열린 포지션": int(wallet.get("open_positions", 0) or 0),
                }
                for wallet in underutilized_wallets[:8]
            ],
            width="stretch",
            hide_index=True,
        )

    regime_panel = load_regime_panel_data() or {"available": False}
    st.markdown("### 레짐·리스크 상태")
    _render_regime_panel(regime_panel)

    top_wallets = sorted(
        wallets,
        key=lambda wallet: float(wallet.get("return_pct") or wallet.get("roi_pct") or 0.0),
        reverse=True,
    )[:12]
    if top_wallets:
        st.markdown("### 상위 지갑")
        st.dataframe(
            [
                {
                    "지갑": str(wallet.get("display_name") or wallet.get("wallet_name") or "-"),
                    "심볼": str(wallet.get("symbol_display") or wallet.get("symbol") or "-"),
                    "수익률": (
                        f"{float(wallet.get('return_pct') or wallet.get('roi_pct') or 0.0):+.2f}%"
                    ),
                    "활용률": f"{float(wallet.get('capital_utilization_pct', 0.0) or 0.0):.1f}%",
                    "실현 손익": fmt_won(float(wallet.get("realized_pnl", 0.0) or 0.0)),
                    "열린 포지션": int(wallet.get("open_positions", 0) or 0),
                    "거래수": int(wallet.get("trade_count", 0) or 0),
                }
                for wallet in top_wallets
            ],
            width="stretch",
            hide_index=True,
        )


def _render_edge_analysis_tab() -> None:
    rotations = load_recent_rotations()
    if not rotations:
        _empty("최근 24시간 심볼 로테이션 이력이 없습니다.")
        return

    st.dataframe(
        [
            {
                "지갑": wallet_name,
                "이전": str(rotation.get("before") or "-"),
                "현재": str(rotation.get("after") or "-"),
                "트리거": str(rotation.get("trigger") or "-"),
                "시각": fmt_relative_time(rotation["ts_dt"]),
            }
            for wallet_name, rotation in sorted(
                rotations.items(),
                key=lambda item: item[1]["_ts"],
                reverse=True,
            )
        ],
        width="stretch",
        hide_index=True,
    )


def _render_reports_tab() -> None:
    pnl = load_pnl_report() or {}
    st.markdown("### PnL 스냅샷")
    st.code(json.dumps(pnl, ensure_ascii=False, indent=2)[:4000], language="json")

    trades = load_all_paper_trades() or []
    if trades:
        st.markdown("### 최근 20건")
        st.dataframe(
            [
                {
                    "시각": str(
                        trade.get("exit_time")
                        or trade.get("closed_at")
                        or trade.get("timestamp")
                        or "-"
                    )[:19],
                    "심볼": symbol_kr(str(trade.get("symbol", ""))),
                    "지갑": str(trade.get("wallet", "")).replace("_wallet", ""),
                    "손익": fmt_won(float(trade.get("realized_pnl", trade.get("pnl", 0.0)) or 0.0)),
                }
                for trade in sorted(
                    trades,
                    key=lambda row: str(
                        row.get("exit_time") or row.get("closed_at") or row.get("timestamp") or ""
                    ),
                    reverse=True,
                )[:20]
            ],
            width="stretch",
            hide_index=True,
        )


def _render_strategy_research_tab() -> None:
    review_path = (
        Path(_repo_root)
        / "docs"
        / "research"
        / "2026-04-10-codex-strategy-review"
        / "00_README.md"
    )
    if not review_path.exists():
        _empty("전략 리뷰 문서가 없습니다.")
        return
    st.markdown(review_path.read_text(encoding="utf-8"))


def _render_funding_rate_research_tab() -> None:
    st.info("펀딩레이트 연구 탭은 카드형 대시보드 개편 이후 재연결 중입니다.")


def _render_alerts_history_tab() -> None:
    trades = load_all_paper_trades() or []
    if not trades:
        _empty("표시할 히스토리가 없습니다.")
        return
    st.dataframe(
        [
            {
                "손익%": f"{float(trade_pnl_pct) :+.2f}%",
                "시각": str(
                    trade.get("exit_time")
                    or trade.get("closed_at")
                    or trade.get("timestamp")
                    or "-"
                )[:19],
                "심볼": symbol_kr(str(trade.get("symbol", ""))),
                "지갑": str(trade.get("wallet", "")).replace("_wallet", ""),
                "종료사유": str(trade.get("exit_reason") or "-"),
            }
            for trade in sorted(
                trades,
                key=lambda row: str(
                    row.get("exit_time") or row.get("closed_at") or row.get("timestamp") or ""
                ),
                reverse=True,
            )[:50]
            for trade_pnl_pct in [
                trade.get("realized_pnl_pct", trade.get("pnl_pct", 0.0)) or 0.0
            ]
        ],
        width="stretch",
        hide_index=True,
    )


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
    render_header()
    render_regime_and_health()
    render_pnl_summary()
    render_positions()
    render_wallets()
    render_recent_trades()

with tab_portfolio_risk:
    _render_portfolio_risk_tab()
    _render_fear_greed_gauge(load_regime_panel_data() or {"available": False})

with tab_signal_monitor:
    _render_signal_monitor(load_signal_monitor_data() or {})

with tab_edge_analysis:
    _render_edge_analysis_tab()

with tab_reports:
    _render_reports_tab()

with tab_strategy_research:
    _render_strategy_research_tab()

with tab_funding_rate_research:
    _render_funding_rate_research_tab()

with tab_alerts_history:
    _render_alerts_history_tab()
