"""Mobile-first responsive CSS for the dashboard."""

from __future__ import annotations

import streamlit as st

MOBILE_CSS = """
<style>
/* ── Base Reset ── */
html, body, [data-testid="stAppViewContainer"] {
    font-size: 16px;
    -webkit-text-size-adjust: 100%;
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

/* ── Tab Navigation ── */
[data-testid="stTabs"] [role="tablist"] {
    gap: 0 !important;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    flex-wrap: nowrap;
}
[data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar {
    display: none;
}
[data-testid="stTabs"] [role="tab"] {
    min-height: 48px !important;
    padding: 0.5rem 0.75rem !important;
    font-size: 0.875rem !important;
    white-space: nowrap;
}

/* ── Metric Cards ── */
[data-testid="stMetric"] {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 1rem;
}
[data-testid="stMetricLabel"] {
    font-size: 0.8125rem !important;
    color: #888 !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
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
.regime-bull { background: #0d5f2c; color: #4ade80; }
.regime-sideways { background: #5c4d1a; color: #fbbf24; }
.regime-bear { background: #7f1d1d; color: #f87171; }

.status-badge {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 999px;
    font-size: 0.8125rem;
    font-weight: 600;
}
.status-ok { background: #0d5f2c; color: #4ade80; }
.status-warn { background: #5c4d1a; color: #fbbf24; }
.status-fail { background: #7f1d1d; color: #f87171; }

/* ── Signal Colors ── */
.signal-buy { color: #4ade80; font-weight: 600; }
.signal-sell { color: #f87171; font-weight: 600; }
.signal-hold { color: #9ca3af; }

/* ── Responsive Breakpoints ── */
/* Mobile < 600px (Galaxy Z Fold7 cover: 375px) */
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
        font-size: 1.25rem !important;
    }
    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
    }
}

/* Tablet 600-960px (Galaxy Z Fold7 inner: 600px) */
@media (min-width: 600px) and (max-width: 959px) {
    .block-container {
        max-width: 720px !important;
        margin: 0 auto !important;
        padding: 1rem !important;
    }
}

/* Desktop 960px+ */
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
