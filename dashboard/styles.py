"""Unified responsive styles for the dashboard."""

from __future__ import annotations

import streamlit as st

MOBILE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Noto+Sans+KR:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-app: #09121b;
    --bg-app-alt: #0f1d2a;
    --bg-card: rgba(10, 22, 33, 0.78);
    --bg-card-strong: rgba(12, 27, 41, 0.92);
    --bg-card-hover: rgba(17, 37, 56, 0.95);
    --border-card: rgba(137, 196, 244, 0.18);
    --border-card-hover: rgba(137, 196, 244, 0.32);
    --text-primary: #edf5fb;
    --text-muted: #9fb4c7;
    --text-secondary: #7b95ab;
    --green: #61f2a2;
    --green-bg: rgba(11, 93, 54, 0.42);
    --red: #ff7d8e;
    --red-bg: rgba(122, 28, 49, 0.42);
    --yellow: #ffc75f;
    --yellow-bg: rgba(118, 83, 16, 0.42);
    --blue: #77b8ff;
    --blue-soft: rgba(119, 184, 255, 0.18);
    --teal: #42d9c8;
    --purple: #97a2ff;
    --mono: 'JetBrains Mono', monospace;
    --font-body: 'Noto Sans KR', sans-serif;
    --font-display: 'Space Grotesk', 'Noto Sans KR', sans-serif;
}

html, body, [data-testid="stAppViewContainer"] {
    font-family: var(--font-body) !important;
    color: var(--text-primary);
    background:
        radial-gradient(circle at top left, rgba(66, 217, 200, 0.12), transparent 26%),
        radial-gradient(circle at top right, rgba(119, 184, 255, 0.18), transparent 24%),
        linear-gradient(180deg, #071018 0%, #0b1723 55%, #0c1a28 100%);
}

.stApp {
    background: transparent;
}

h1, h2, h3, h4 {
    font-family: var(--font-display) !important;
    letter-spacing: -0.03em;
}

[data-testid="stMetricValue"] {
    font-family: var(--mono) !important;
    font-variant-numeric: tabular-nums;
}

.block-container {
    max-width: 1180px !important;
    padding: 1.1rem 1rem 2.4rem !important;
}

button, [role="tab"], .stSelectbox, .stButton > button {
    min-height: 46px !important;
    border-radius: 14px !important;
}

.dashboard-hero {
    display: grid;
    grid-template-columns: 1.5fr 0.9fr;
    gap: 1rem;
    padding: 1.35rem;
    margin: 0.4rem 0 1rem;
    border: 1px solid var(--border-card);
    border-radius: 24px;
    background:
        linear-gradient(135deg, rgba(18, 40, 58, 0.95), rgba(8, 21, 33, 0.95)),
        radial-gradient(circle at top right, rgba(119, 184, 255, 0.22), transparent 35%);
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.24);
}

.dashboard-hero h2 {
    margin: 0.1rem 0 0.55rem;
    font-size: 1.7rem;
}

.dashboard-hero p {
    margin: 0;
    color: var(--text-muted);
    line-height: 1.7;
}

.eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    font-size: 0.72rem;
    color: var(--teal);
}

.hero-chip-stack {
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
    justify-content: center;
}

.hero-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.8rem 0.95rem;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.09);
    color: var(--text-primary);
    font-weight: 600;
}

.dashboard-panel {
    padding: 0.9rem 1rem;
    margin-bottom: 0.65rem;
    background: var(--bg-card);
    border: 1px solid var(--border-card);
    border-radius: 18px;
    line-height: 1.7;
    transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}

.dashboard-panel:hover {
    background: var(--bg-card-hover);
    border-color: var(--border-card-hover);
    transform: translateY(-1px);
}

[data-testid="stMetric"] {
    background: var(--bg-card);
    border: 1px solid var(--border-card);
    border-radius: 18px;
    padding: 1rem;
    min-width: 0;
}

[data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
}

[data-testid="stMetricValue"] {
    font-size: 1.4rem !important;
    font-weight: 700 !important;
}

[data-testid="stTabs"] [role="tablist"] {
    gap: 0.35rem !important;
    overflow-x: auto;
    scrollbar-width: none;
    flex-wrap: nowrap;
    padding-bottom: 0.2rem;
}

[data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar {
    display: none;
}

[data-testid="stTabs"] [role="tab"] {
    padding: 0.65rem 1rem !important;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.06);
    color: var(--text-muted) !important;
}

[data-testid="stTabs"] [aria-selected="true"] {
    color: var(--text-primary) !important;
    border-color: rgba(119, 184, 255, 0.35) !important;
    background:
        linear-gradient(180deg, rgba(119, 184, 255, 0.18), rgba(119, 184, 255, 0.06))
        !important;
}

[data-testid="stTabContent"] {
    animation: fadeIn 0.2s ease-in;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}

.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.35rem 0.85rem;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 700;
}

.status-ok { background: var(--green-bg); color: var(--green); }
.status-warn { background: var(--yellow-bg); color: var(--yellow); }
.status-fail { background: var(--red-bg); color: var(--red); }

[data-testid="stDataFrame"] {
    background: var(--bg-card-strong);
    border: 1px solid var(--border-card);
    border-radius: 18px;
    overflow: hidden;
}

[data-testid="stDataFrame"] table {
    font-size: 0.84rem !important;
}

.js-plotly-plot, .plotly {
    width: 100% !important;
}

#MainMenu, footer, header {
    visibility: hidden;
}

@media (max-width: 900px) {
    .dashboard-hero {
        grid-template-columns: 1fr;
    }
}

@media (max-width: 640px) {
    .block-container {
        padding: 0.65rem 0.5rem 1.4rem !important;
    }

    .dashboard-hero {
        padding: 1rem;
        border-radius: 18px;
    }

    .dashboard-hero h2 {
        font-size: 1.3rem;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.12rem !important;
    }

    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
        gap: 0.55rem !important;
    }

    [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlock"] {
        width: 100% !important;
        min-width: 100% !important;
    }

    .dashboard-panel {
        padding: 0.8rem 0.85rem;
        border-radius: 14px;
    }
}

@media (max-width: 375px) {
    .dashboard-hero h2 {
        font-size: 1.14rem;
    }

    [data-testid="stTabs"] [role="tab"] {
        padding: 0.55rem 0.75rem !important;
        font-size: 0.76rem !important;
    }
}
</style>
"""


def inject_css() -> None:
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)


COLORS = {
    "green": "#61f2a2",
    "green_bg": "rgba(11, 93, 54, 0.42)",
    "red": "#ff7d8e",
    "red_bg": "rgba(122, 28, 49, 0.42)",
    "blue": "#77b8ff",
    "yellow": "#ffc75f",
    "purple": "#97a2ff",
    "pink": "#ff8ccf",
    "teal": "#42d9c8",
    "orange": "#ff9d5c",
    "indigo": "#8b92ff",
    "muted": "#7b95ab",
    "bg_dark": "#122334",
}

PALETTE = [
    COLORS["blue"],
    COLORS["teal"],
    COLORS["green"],
    COLORS["yellow"],
    COLORS["purple"],
    COLORS["pink"],
    COLORS["orange"],
    COLORS["indigo"],
    COLORS["red"],
    COLORS["muted"],
]


def chart_layout(
    *,
    title: str = "",
    height: int = 280,
    yaxis_title: str = "",
    xaxis_title: str = "",
    show_legend: bool = True,
    legend_below: bool = True,
) -> dict[str, object]:
    layout: dict[str, object] = {
        "template": "plotly_dark",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "margin": {"l": 18, "r": 18, "t": 42 if title else 18, "b": 28},
        "height": height,
        "font": {"size": 11, "family": "'Noto Sans KR', sans-serif"},
    }
    if title:
        layout["title"] = {"text": title, "font": {"size": 15}}
    if yaxis_title:
        layout["yaxis_title"] = yaxis_title
    if xaxis_title:
        layout["xaxis_title"] = xaxis_title
    if show_legend and legend_below:
        layout["legend"] = {
            "orientation": "h",
            "yanchor": "bottom",
            "y": -0.24,
            "xanchor": "center",
            "x": 0.5,
        }
    elif not show_legend:
        layout["showlegend"] = False
    return layout


def pnl_color(value: float) -> str:
    return COLORS["green"] if value >= 0 else COLORS["red"]
