"""Mobile-first responsive CSS for the dashboard."""

from __future__ import annotations

import streamlit as st

MOBILE_CSS = """
<style>
/* ── Import Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── CSS Custom Properties ── */
:root {
    --bg-card: rgba(255, 255, 255, 0.04);
    --bg-card-hover: rgba(255, 255, 255, 0.07);
    --border-card: rgba(255, 255, 255, 0.08);
    --border-card-hover: rgba(255, 255, 255, 0.16);
    --text-primary: #f3f4f6;
    --text-muted: #9ca3af;
    --text-secondary: #6b7280;
    --green: #4ade80;
    --green-bg: #0d5f2c;
    --red: #f87171;
    --red-bg: #7f1d1d;
    --yellow: #fbbf24;
    --yellow-bg: #5c4d1a;
    --blue: #60a5fa;
    --bg-app: #0e1117;
    --font-body: 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
}

/* ── Base Reset ── */
html, body, [data-testid="stAppViewContainer"] {
    font-family: var(--font-body) !important;
    font-size: 16px;
    -webkit-text-size-adjust: 100%;
}

/* ── Monospace for numbers ── */
[data-testid="stMetricValue"] {
    font-family: var(--font-mono) !important;
    font-variant-numeric: tabular-nums;
}

/* ── Centered Layout ── */
.block-container {
    max-width: 100% !important;
    padding: 1rem !important;
}

/* ── Touch Targets (WCAG 2.5.8 — 48px minimum) ── */
button, [role="tab"], .stSelectbox, .stButton > button {
    min-height: 48px !important;
    min-width: 48px !important;
    font-size: 1rem !important;
}

/* ── Tab Navigation: horizontal scroll on mobile ── */
[data-testid="stTabs"] [role="tablist"] {
    gap: 0 !important;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    flex-wrap: nowrap;
    position: relative;
}
[data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar {
    display: none;
}
[data-testid="stTabs"] [role="tab"] {
    min-height: 48px !important;
    padding: 0.5rem 0.75rem !important;
    font-size: 0.875rem !important;
    white-space: nowrap;
    transition: color 0.15s ease;
}

/* ── Tab Content Transition ── */
[data-testid="stTabContent"] {
    animation: fadeIn 0.2s ease-in;
}
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}

/* ── Metric Cards ── */
[data-testid="stMetric"] {
    background: var(--bg-card);
    border: 1px solid var(--border-card);
    border-radius: 12px;
    padding: 1rem;
    min-width: 0;
    overflow: hidden;
    transition: border-color 0.2s ease, background 0.2s ease;
}
[data-testid="stMetric"]:hover {
    background: var(--bg-card-hover);
    border-color: var(--border-card-hover);
}
[data-testid="stMetricLabel"] {
    font-size: 0.8125rem !important;
    color: var(--text-muted) !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
[data-testid="stMetricDelta"] {
    font-size: 0.75rem !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* ── Status Badges ── */
.regime-badge {
    display: inline-block;
    padding: 0.375rem 1rem;
    border-radius: 999px;
    font-weight: 600;
    font-size: 0.875rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.regime-bull { background: var(--green-bg); color: var(--green); }
.regime-sideways { background: var(--yellow-bg); color: var(--yellow); }
.regime-bear { background: var(--red-bg); color: var(--red); }

.status-badge {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 999px;
    font-size: 0.8125rem;
    font-weight: 600;
}
.status-ok { background: var(--green-bg); color: var(--green); }
.status-warn { background: var(--yellow-bg); color: var(--yellow); }
.status-fail { background: var(--red-bg); color: var(--red); }

/* ── Signal Colors ── */
.signal-buy { color: var(--green); font-weight: 600; }
.signal-sell { color: var(--red); font-weight: 600; }
.signal-hold { color: var(--text-muted); }

/* ── Signal timeline compact on mobile ── */
.signal-row {
    padding: 0.625rem 0;
    line-height: 1.6;
    font-size: 0.9375rem;
    border-bottom: 1px solid var(--border-card);
}
.signal-row:last-child {
    border-bottom: none;
}
.signal-container {
    max-height: 65vh;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
}

/* ── Confidence Bar ── */
.conf-track {
    display: inline-block;
    width: 3rem;
    height: 4px;
    background: #333;
    border-radius: 2px;
    vertical-align: middle;
    margin-left: 0.25rem;
}
.conf-fill {
    display: block;
    height: 100%;
    border-radius: 2px;
}

/* ── DataFrames: horizontal scroll, compact font ── */
[data-testid="stDataFrame"], .dataframe-container {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch;
    font-size: 0.8125rem !important;
}
[data-testid="stDataFrame"] table {
    font-size: 0.8125rem !important;
    min-width: 100%;
}

/* ── Position cards: full-width on mobile ── */
.position-card {
    background: var(--bg-card);
    border: 1px solid var(--border-card);
    border-radius: 10px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
    line-height: 1.6;
    font-size: 0.9375rem;
    transition: border-color 0.2s ease;
}
.position-card:hover {
    border-color: var(--border-card-hover);
}

/* ── Login Card ── */
.login-container {
    max-width: 380px;
    margin: 0 auto;
    padding: 2rem 1.5rem;
}
.login-brand {
    text-align: center;
    padding: 3rem 1rem 1.5rem;
}
.login-brand h2 {
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 0.25rem;
}
.login-brand p {
    color: var(--text-secondary);
    font-size: 0.875rem;
}

/* ── Header Layout ── */
.header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
}

/* ── Responsive: Mobile < 600px (base) ── */
@media (max-width: 599px) {
    .block-container {
        max-width: 100% !important;
        padding: 0.5rem !important;
    }
    [data-testid="stTabs"] [role="tab"] {
        padding: 0.5rem 0.5rem !important;
        font-size: 0.75rem !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.125rem !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.6875rem !important;
    }
    /* 3 cols → 1 col stack */
    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
        gap: 0.5rem !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlock"] {
        width: 100% !important;
        min-width: 100% !important;
    }
    .js-plotly-plot .plotly {
        height: 220px !important;
    }
}

/* ── Galaxy Z Fold7 cover (≤375px) ── */
@media (max-width: 375px) {
    .block-container {
        padding: 0.375rem !important;
    }
    [data-testid="stTabs"] [role="tab"] {
        padding: 0.375rem 0.4rem !important;
        font-size: 0.6875rem !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.6875rem !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.625rem !important;
    }
    .signal-row { font-size: 0.8125rem; }
    h2, h3 { font-size: 1.1rem !important; }
    h4 { font-size: 0.9375rem !important; }
}

/* ── Tablet 600-768px ── */
@media (min-width: 600px) and (max-width: 768px) {
    .block-container {
        max-width: 100% !important;
        padding: 0.75rem !important;
    }
    /* 3 cols → 2 cols */
    [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlock"] {
        flex: 1 1 calc(50% - 0.5rem) !important;
        min-width: calc(50% - 0.5rem) !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.25rem !important;
    }
}

/* ── Tablet 768-960px ── */
@media (min-width: 769px) and (max-width: 959px) {
    .block-container {
        max-width: 720px !important;
        margin: 0 auto !important;
        padding: 1rem !important;
    }
}

/* ── Desktop 960px+ ── */
@media (min-width: 960px) {
    .block-container {
        max-width: 960px !important;
        margin: 0 auto !important;
        padding: 1.5rem 2rem !important;
    }
}

/* ── Plotly Charts Responsive ── */
.js-plotly-plot, .plotly {
    width: 100% !important;
}

/* ── Hide Streamlit Branding ── */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { visibility: hidden; }
</style>
"""


def inject_css() -> None:
    """Inject mobile-first responsive CSS into the page."""
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)


# ── Unified Chart Theme ─────────────────────────────────────
# Consistent color palette for all Plotly charts.
COLORS = {
    "green": "#4ade80",
    "green_bg": "#0d5f2c",
    "red": "#f87171",
    "red_bg": "#7f1d1d",
    "blue": "#60a5fa",
    "yellow": "#fbbf24",
    "purple": "#a78bfa",
    "pink": "#f472b6",
    "teal": "#34d399",
    "orange": "#fb923c",
    "indigo": "#818cf8",
    "muted": "#6b7280",
    "bg_dark": "#1f2937",
}

# Ordered palette for categorical data (pie charts, multi-series).
PALETTE = [
    COLORS["red"], COLORS["yellow"], COLORS["green"], COLORS["blue"],
    COLORS["purple"], COLORS["pink"], COLORS["teal"], COLORS["orange"],
    COLORS["indigo"], "#e879f9", COLORS["muted"],
]


def chart_layout(
    *,
    title: str = "",
    height: int = 280,
    yaxis_title: str = "",
    xaxis_title: str = "",
    show_legend: bool = True,
    legend_below: bool = True,
) -> dict:
    """Return a unified Plotly layout dict for dark-themed charts."""
    layout: dict = {
        "template": "plotly_dark",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "margin": dict(l=16, r=16, t=40 if title else 16, b=24),
        "height": height,
        "font": dict(size=11, family="'Noto Sans KR', sans-serif"),
    }
    if title:
        layout["title"] = dict(text=title, font=dict(size=14))
    if yaxis_title:
        layout["yaxis_title"] = yaxis_title
    if xaxis_title:
        layout["xaxis_title"] = xaxis_title
    if show_legend and legend_below:
        layout["legend"] = dict(
            orientation="h", yanchor="bottom", y=-0.25,
            xanchor="center", x=0.5,
        )
    elif not show_legend:
        layout["showlegend"] = False
    return layout


def pnl_color(value: float) -> str:
    """Return green for positive, red for negative values."""
    return COLORS["green"] if value >= 0 else COLORS["red"]


def pnl_colors(values: list[float]) -> list[str]:
    """Return color list based on sign of each value."""
    return [pnl_color(v) for v in values]
